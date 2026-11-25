"""Decision Engine & Bounded Autonomy Framework for JARVIS (Section 8).

Implements:
- Action Selection (Section 8.1)
- Risk Classification (Section 8.2)
- Autonomous Task Continuation (Section 8.3)
- Safe Failure Recovery (Section 8.4)
"""

from __future__ import annotations

import time
from enum import StrEnum
from typing import Any

from core.permissions import PermissionCategory
from core.persian.models import (
    ConfidenceLevel,
    DecisionRecord,
    RiskLevel,
    SemanticInterpretation,
    TaskComplexity,
)
from core.tool_proposal import RiskLevel as ProposalRiskLevel
from infrastructure.logging import get_logger

logger = get_logger("core.decision")


def map_to_proposal_risk(risk: RiskLevel | str) -> ProposalRiskLevel:
    """Map Phase B domain RiskLevel to tool proposal RiskLevel."""
    val = risk.value if isinstance(risk, (RiskLevel, ProposalRiskLevel)) else str(risk)
    if val in (
        RiskLevel.IRREVERSIBLE_OPERATION.value,
        ProposalRiskLevel.CRITICAL.value,
        "critical",
    ):
        return ProposalRiskLevel.CRITICAL
    if val in (
        RiskLevel.DESTRUCTIVE_OPERATION.value,
        RiskLevel.SENSITIVE_DATA_ACCESS.value,
        RiskLevel.EXTERNAL_COMMUNICATION.value,
        ProposalRiskLevel.HIGH.value,
        "high",
    ):
        return ProposalRiskLevel.HIGH
    if val in (RiskLevel.REVERSIBLE_MODIFICATION.value, ProposalRiskLevel.MEDIUM.value, "medium"):
        return ProposalRiskLevel.MEDIUM
    return ProposalRiskLevel.LOW


def map_from_proposal_risk(risk: ProposalRiskLevel | str) -> RiskLevel:
    """Map tool proposal RiskLevel to Phase B domain RiskLevel."""
    val = risk.value if isinstance(risk, ProposalRiskLevel) else str(risk)
    if val == ProposalRiskLevel.CRITICAL.value:
        return RiskLevel.DESTRUCTIVE_OPERATION
    if val == ProposalRiskLevel.HIGH.value:
        return RiskLevel.SENSITIVE_DATA_ACCESS
    if val == ProposalRiskLevel.MEDIUM.value:
        return RiskLevel.REVERSIBLE_MODIFICATION
    return RiskLevel.READ_ONLY


class ActionType(StrEnum):
    """Categorized actionable decision path chosen by Decision Engine."""

    ANSWER_DIRECTLY = "answer_directly"
    SEARCH_MEMORY = "search_memory"
    SEARCH_PROJECT_FILES = "search_project_files"
    ASK_CLARIFICATION = "ask_clarification"
    CREATE_PLAN = "create_plan"
    EXECUTE_TOOL = "execute_tool"
    DELEGATE_TO_ANTIGRAVITY = "delegate_to_antigravity"
    REQUEST_USER_APPROVAL = "request_user_approval"
    REFUSE_UNSAFE_OPERATION = "refuse_unsafe_operation"
    REPORT_IMPOSSIBLE = "report_impossible"


class RiskClassifier:
    """Classifies actions into risk tiers to enforce bounded autonomy (Section 8.2)."""

    DESTRUCTIVE_KEYWORDS = (
        "delete",
        "remove",
        "drop",
        "wipe",
        "format",
        "destroy",
        "truncate",
        "unlink",
        "پاک",
        "حذف",
        "دیلیت",
        "نابود",
    )
    SENSITIVE_KEYWORDS = (
        "password",
        "secret",
        "token",
        "credential",
        "private_key",
        "api_key",
        "auth_token",
        "cvv",
        "ssn",
        "credit_card",
        "پسورد",
        "رمز",
        "کلید",
    )
    EXTERNAL_COMM_KEYWORDS = (
        "email",
        "send_email",
        "whatsapp",
        "post_message",
        "cloud_transmit",
        "ارسال",
        "پیام",
    )
    IRREVERSIBLE_FLAGS = ("force", "all", "recursive", "permanent", "purge", "hard")

    SAFE_READ_ONLY_TOOLS = {
        "weather_current",
        "weather_forecast",
        "file_search",
        "file_inspect",
        "system_info",
        "windows_window_read",
        "windows_display_read",
        "windows_audio_read",
        "windows_app_read",
        "browser_read",
        "browser_tab",
        "coding_agent_status",
        "system_diagnostics",
        "memory_search",
        "datetime_query",
    }

    @classmethod
    def _has_irreversible_flags(
        cls, tool_name: str = "", params: dict[str, Any] | None = None
    ) -> bool:
        """Check if tool or parameters specify irreversible or unconstrained destructive flags."""
        t_lower = (tool_name or "").lower().strip()
        t_tokens = set(t_lower.replace("-", "_").split("_"))
        if any(f in t_tokens for f in cls.IRREVERSIBLE_FLAGS):
            return True

        if not params:
            return False
        for k, v in params.items():
            k_lower = str(k).lower().strip()
            # If parameter key is an irreversible flag with truthy value
            if k_lower in cls.IRREVERSIBLE_FLAGS and bool(v):
                return True
            # If parameter value is a discrete word token representing an irreversible flag
            if isinstance(v, str) and k_lower not in (
                "content",
                "text",
                "query",
                "body",
                "html",
                "file_path",
                "path",
                "target_path",
                "description",
                "goal",
            ):
                v_words = set(v.lower().replace("-", "_").split())
                if any(f in v_words for f in cls.IRREVERSIBLE_FLAGS):
                    return True
        return False

    @classmethod
    def _has_sensitive_credentials(cls, params: dict[str, Any] | None) -> bool:
        """Inspect parameters for sensitive credentials, secret keys, or authentication tokens."""
        if not params:
            return False
        for k, v in params.items():
            k_lower = str(k).lower().strip()
            if k_lower in cls.SENSITIVE_KEYWORDS:
                return True
            if isinstance(v, str):
                v_lower = v.lower()
                if any(hdr in v for hdr in ("-----BEGIN ", "bearer eyJ", "sk-", "ghp_")):
                    return True
                if k_lower not in (
                    "path",
                    "file_path",
                    "directory",
                    "dir",
                    "folder",
                    "url",
                    "query",
                    "text",
                    "goal",
                    "description",
                ) and any(w in v_lower for w in cls.SENSITIVE_KEYWORDS):
                    return True
        return False

    def classify_risk(
        self,
        tool_name: str,
        params: dict[str, Any] | None = None,
        tool_instance: Any = None,
        tool_metadata: dict[str, Any] | None = None,
    ) -> RiskLevel:
        """Classify tool and parameters into strong RiskLevel enum with capability inspection and fail-closed security."""
        t_lower = (tool_name or "").lower().strip()
        p_str = str(params or {}).lower()

        # 0. Check explicit tool definition risk level if present
        explicit_risk = None
        if tool_instance and hasattr(tool_instance, "get_definition"):
            try:
                t_def = tool_instance.get_definition()
                if hasattr(t_def, "risk_level") and t_def.risk_level:
                    explicit_risk = t_def.risk_level
            except Exception:
                pass
        elif tool_metadata and "risk_level" in tool_metadata:
            explicit_risk = tool_metadata["risk_level"]

        if explicit_risk is not None:
            r_val = (
                explicit_risk.value
                if hasattr(explicit_risk, "value")
                else str(explicit_risk).lower()
            )
            # Parameter escalation checks
            if self._has_sensitive_credentials(params):
                return RiskLevel.SENSITIVE_DATA_ACCESS
            if self._has_irreversible_flags(tool_name, params):
                return RiskLevel.IRREVERSIBLE_OPERATION
            if r_val in ("critical", RiskLevel.IRREVERSIBLE_OPERATION.value):
                return RiskLevel.IRREVERSIBLE_OPERATION
            if r_val in ("high", RiskLevel.DESTRUCTIVE_OPERATION.value):
                return RiskLevel.DESTRUCTIVE_OPERATION
            if r_val in ("medium", RiskLevel.REVERSIBLE_MODIFICATION.value):
                return RiskLevel.REVERSIBLE_MODIFICATION
            if r_val in ("low", RiskLevel.READ_ONLY.value):
                return RiskLevel.READ_ONLY

        # 1. Inspect capability category if available
        cat = None
        if tool_instance and hasattr(tool_instance, "category"):
            cat = tool_instance.category
        elif tool_metadata and "category" in tool_metadata:
            cat = tool_metadata["category"]

        if cat is not None:
            cat_val = cat.value if hasattr(cat, "value") else str(cat)
            if cat_val in (
                PermissionCategory.DESTRUCTIVE.value,
                PermissionCategory.FILE_DELETE.value,
                PermissionCategory.WINDOWS_POWER_CONTROL.value,
            ):
                if self._has_irreversible_flags(tool_name, params):
                    return RiskLevel.IRREVERSIBLE_OPERATION
                return RiskLevel.DESTRUCTIVE_OPERATION

            if cat_val == PermissionCategory.EXTERNAL_COMMUNICATION.value:
                return RiskLevel.EXTERNAL_COMMUNICATION

            if cat_val in (
                PermissionCategory.FILE_WRITE.value,
                PermissionCategory.FILE_ARCHIVE.value,
                PermissionCategory.FILE_MODIFICATION.value,
                PermissionCategory.REVERSIBLE.value,
                PermissionCategory.WINDOWS_WINDOW_CONTROL.value,
                PermissionCategory.WINDOWS_AUDIO_CONTROL.value,
                PermissionCategory.WINDOWS_DISPLAY_CONTROL.value,
                PermissionCategory.WINDOWS_APP_LAUNCH.value,
                PermissionCategory.WINDOWS_APP_CLOSE.value,
            ):
                return RiskLevel.REVERSIBLE_MODIFICATION

            if cat_val in (
                PermissionCategory.READ_ONLY.value,
                PermissionCategory.COMPUTATION.value,
                PermissionCategory.FILE_READ.value,
                PermissionCategory.FILE_SEARCH.value,
                PermissionCategory.SYSTEM_INFO.value,
                PermissionCategory.NETWORK_INSPECT.value,
                PermissionCategory.WINDOWS_WINDOW_READ.value,
                PermissionCategory.WINDOWS_AUDIO_READ.value,
                PermissionCategory.WINDOWS_DISPLAY_READ.value,
                PermissionCategory.WINDOWS_APP_READ.value,
            ):
                # Verify no sensitive keywords injected in parameters
                if self._has_sensitive_credentials(params):
                    return RiskLevel.SENSITIVE_DATA_ACCESS
                return RiskLevel.READ_ONLY

        # 2. Sensitive credential & key access check
        if any(k in t_lower for k in self.SENSITIVE_KEYWORDS) or self._has_sensitive_credentials(
            params
        ):
            return RiskLevel.SENSITIVE_DATA_ACCESS

        # 3. Destructive operations check
        if any(k in t_lower or k in p_str for k in self.DESTRUCTIVE_KEYWORDS):
            if self._has_irreversible_flags(tool_name, params):
                return RiskLevel.IRREVERSIBLE_OPERATION
            return RiskLevel.DESTRUCTIVE_OPERATION

        # 4. External communications
        if any(k in t_lower for k in self.EXTERNAL_COMM_KEYWORDS):
            return RiskLevel.EXTERNAL_COMMUNICATION

        # 5. Modifications
        if any(
            k in t_lower
            for k in ("write", "create", "modify", "update", "rename", "edit", "touch", "append")
        ):
            return RiskLevel.REVERSIBLE_MODIFICATION

        # 6. Explicitly recognized read-only tools
        if t_lower in self.SAFE_READ_ONLY_TOOLS or any(
            t_lower.startswith(s)
            for s in (
                "weather",
                "search",
                "inspect",
                "system_info",
                "read",
                "list",
                "get",
                "view",
                "check",
                "status",
                "git_status",
            )
        ):
            return RiskLevel.READ_ONLY

        # 7. Fail-closed for unknown or uninspected tools without metadata
        if not t_lower:
            return RiskLevel.DESTRUCTIVE_OPERATION

        # If completely unknown, fail closed to high risk
        return RiskLevel.DESTRUCTIVE_OPERATION


class FailureRecoveryStrategy(StrEnum):
    """Failure recovery options for bounded task continuation (Section 8.4)."""

    RETRY = "retry"
    USE_ALTERNATIVE = "use_alternative"
    ABORT_AND_REPORT = "abort_and_report"
    ASK_USER = "ask_user"


class FailureRecoveryEngine:
    """Evaluates errors and enforces non-looping failure recovery (Section 8.4)."""

    def __init__(self, max_retries: int = 2) -> None:
        self.max_retries = max_retries
        self._retry_counts: dict[str, int] = {}

    def handle_failure(
        self,
        task_id: str,
        step_index: int,
        tool_name: str,
        error_message: str,
        is_permission_denied: bool = False,
    ) -> tuple[FailureRecoveryStrategy, str]:
        """Classify failure and determine next safe action without infinite loops."""
        key = f"{task_id}:{step_index}:{tool_name}"
        current_retries = self._retry_counts.get(key, 0)

        # Permanent failure: permission denied
        if (
            is_permission_denied
            or "permission" in error_message.lower()
            or "unauthorized" in error_message.lower()
        ):
            return (
                FailureRecoveryStrategy.ABORT_AND_REPORT,
                "Action blocked by safety or permission policy.",
            )

        # Permanent failure: file not found or invalid syntax
        if any(
            k in error_message.lower()
            for k in ("not found", "no such file", "syntaxerror", "importerror")
        ):
            return (
                FailureRecoveryStrategy.USE_ALTERNATIVE,
                "Deterministic error detected; switching to alternative approach.",
            )

        # Transient network / timeout errors
        if (
            any(
                k in error_message.lower()
                for k in ("timeout", "timed out", "connection reset", "temporary")
            )
            and current_retries < self.max_retries
        ):
            self._retry_counts[key] = current_retries + 1
            return (
                FailureRecoveryStrategy.RETRY,
                f"Transient network error; retry attempt {current_retries + 1}/{self.max_retries}.",
            )

        return FailureRecoveryStrategy.ABORT_AND_REPORT, f"Permanent tool failure: {error_message}"


class DecisionEngine:
    """Central decision-making coordinator integrating action selection, risk, and autonomy."""

    def __init__(
        self,
        risk_classifier: RiskClassifier | None = None,
        recovery_engine: FailureRecoveryEngine | None = None,
    ) -> None:
        self.risk_classifier = risk_classifier or RiskClassifier()
        self.recovery_engine = recovery_engine or FailureRecoveryEngine()

    def select_action(
        self,
        goal: str,
        semantic_interp: SemanticInterpretation | None = None,
        complexity: TaskComplexity = TaskComplexity.SIMPLE_CONVERSATIONAL,
        context: dict[str, Any] | None = None,
    ) -> tuple[ActionType, dict[str, Any]]:
        """Determine what action to take next (Section 8.1)."""
        # 1. Ambiguity or clarification needed
        if semantic_interp and (
            semantic_interp.requires_clarification or semantic_interp.ambiguities
        ):
            return ActionType.ASK_CLARIFICATION, {
                "reason": "Request contains ambiguities or missing parameters.",
                "prompt": semantic_interp.clarification_prompt or "Could you clarify your request?",
            }

        # 2. Hypothetical discussion: strictly answer directly without execution
        if semantic_interp and semantic_interp.is_hypothetical:
            return ActionType.ANSWER_DIRECTLY, {
                "reason": "Hypothetical scenario requires theoretical explanation only.",
            }

        # 3. High-risk operations: user approval gate
        if complexity == TaskComplexity.HIGH_RISK_OPERATION or (
            semantic_interp and any("destructive" in r for r in semantic_interp.potential_risks)
        ):
            return ActionType.REQUEST_USER_APPROVAL, {
                "reason": "High-risk or destructive operation requires explicit user confirmation.",
                "risk_level": RiskLevel.DESTRUCTIVE_OPERATION.value,
            }

        # 4. Multi-step complex tasks
        if complexity in (TaskComplexity.MULTI_STEP_PLANNING, TaskComplexity.TECHNICAL_DIAGNOSIS):
            return ActionType.CREATE_PLAN, {
                "reason": "Complex task requires structured multi-step planning.",
            }

        # 5. Antigravity delegation requests
        if any(k in goal.lower() for k in ("antigravity", "انتی گراویتی", "آنتی‌گراویتی", "agy")):
            return ActionType.DELEGATE_TO_ANTIGRAVITY, {
                "reason": "Request specifies delegation to Antigravity coding agent.",
            }

        # 6. File operations
        if semantic_interp and semantic_interp.primary_intent == "file_operation":
            return ActionType.EXECUTE_TOOL, {
                "reason": "Permitted file operation within authorized workspace.",
            }

        # 7. Memory recall
        if semantic_interp and semantic_interp.primary_intent == "memory_recall":
            return ActionType.SEARCH_MEMORY, {
                "reason": "User is querying stored memories or preferences.",
            }

        # 8. Web search
        if semantic_interp and semantic_interp.primary_intent == "web_research":
            return ActionType.EXECUTE_TOOL, {
                "reason": "Web research query.",
                "tool": "web_search",
            }

        # Default: direct conversational reply
        return ActionType.ANSWER_DIRECTLY, {
            "reason": "Conversational request resolved directly without tools.",
        }

    def evaluate_tool_execution(
        self,
        tool_name: str,
        params: dict[str, Any] | None = None,
        context: Any = None,
        tool_instance: Any = None,
        tool_metadata: dict[str, Any] | None = None,
    ) -> tuple[bool, RiskLevel, bool, str]:
        """Mandatory execution gateway evaluating tool authorization, risk, and approval requirement.

        Enforces Section 7 & 8 bounded autonomy and capability-driven risk classification.

        Returns:
            (allowed: bool, risk_level: RiskLevel, requires_approval: bool, rationale: str)
        """
        risk_level = self.risk_classifier.classify_risk(
            tool_name=tool_name,
            params=params,
            tool_instance=tool_instance,
            tool_metadata=tool_metadata,
        )

        auto_approve = getattr(context, "auto_approve", False) if context else False
        agent_mode = getattr(context, "agent_mode", "balanced") if context else "balanced"

        # 0. Active Context Policy & Prohibition Verification
        if context:
            ctx_meta = getattr(context, "metadata", {}) or {}
            is_read_only = bool(
                getattr(context, "read_only", False) or ctx_meta.get("read_only", False)
            )
            if is_read_only and risk_level != RiskLevel.READ_ONLY:
                return (
                    False,
                    risk_level,
                    False,
                    f"Action '{tool_name}' blocked: Execution context is restricted to read-only operations.",
                )

            prohibitions = ctx_meta.get("prohibited_actions", [])
            # Priority 1: Check specific targeted resource prohibitions first
            for p in prohibitions:
                p_lower = str(p).lower().strip()
                if p_lower.startswith("do_not_touch_"):
                    target_token = p_lower.replace("do_not_touch_", "").strip()
                    p_str_val = str(params or {}).lower()
                    if target_token in p_str_val or target_token in (tool_name or "").lower():
                        return (
                            False,
                            risk_level,
                            False,
                            f"Action '{tool_name}' blocked: Access to '{target_token}' is explicitly prohibited.",
                        )

            # Priority 2: Check general action and modification prohibitions
            for p in prohibitions:
                p_lower = str(p).lower().strip()
                if p_lower in ("no_unauthorized_deletion", "no_deletion") and risk_level in (
                    RiskLevel.DESTRUCTIVE_OPERATION,
                    RiskLevel.IRREVERSIBLE_OPERATION,
                ):
                    return (
                        False,
                        risk_level,
                        False,
                        f"Action '{tool_name}' blocked by prohibition policy: {p}",
                    )
                if (
                    p_lower in ("no_modifications", "read_only")
                    and risk_level != RiskLevel.READ_ONLY
                ):
                    return (
                        False,
                        risk_level,
                        False,
                        f"Action '{tool_name}' blocked by prohibition policy: {p}",
                    )

        cat = None
        if tool_instance and hasattr(tool_instance, "category"):
            cat = tool_instance.category
        elif tool_metadata and "category" in tool_metadata:
            cat = tool_metadata["category"]
        cat_val = cat.value if hasattr(cat, "value") else str(cat) if cat is not None else None

        # Rule 1: Irreversible / Destructive / Sensitive operations ALWAYS require user confirmation
        if risk_level in (
            RiskLevel.IRREVERSIBLE_OPERATION,
            RiskLevel.DESTRUCTIVE_OPERATION,
            RiskLevel.SENSITIVE_DATA_ACCESS,
        ):
            return (
                True,
                risk_level,
                True,
                f"Action involves {risk_level.value}; mandatory user confirmation required.",
            )

        # Rule 2: External communication requires approval unless explicit auto-approve context
        if risk_level == RiskLevel.EXTERNAL_COMMUNICATION:
            req_app = not auto_approve
            return (
                True,
                risk_level,
                req_app,
                "Action transmits data externally."
                + (" Approval required." if req_app else " Authorized."),
            )

        # Rule 3: Reversible modification
        if risk_level == RiskLevel.REVERSIBLE_MODIFICATION:
            tool_def = (
                tool_instance.get_definition() if hasattr(tool_instance, "get_definition") else None
            )
            if tool_def is not None and hasattr(tool_def, "requires_approval"):
                req_app = tool_def.requires_approval or (
                    agent_mode == "strict" and not auto_approve
                )
            elif cat_val in (
                PermissionCategory.WINDOWS_AUDIO_CONTROL.value,
                PermissionCategory.WINDOWS_DISPLAY_CONTROL.value,
                PermissionCategory.WINDOWS_WINDOW_CONTROL.value,
            ):
                req_app = not auto_approve and agent_mode == "strict"
            else:
                req_app = not auto_approve and agent_mode != "autonomous"
            return (
                True,
                risk_level,
                req_app,
                f"Reversible modification under {agent_mode} mode."
                + (" Confirmation requested." if req_app else ""),
            )

        # Rule 4: Read-only safe execution
        return (
            True,
            RiskLevel.READ_ONLY,
            False,
            "Read-only inspection permitted autonomously.",
        )

    def record_decision(
        self,
        objective: str,
        action: ActionType,
        reasons: list[str],
        risk_level: RiskLevel = RiskLevel.READ_ONLY,
        constraints: list[str] | None = None,
        confidence: ConfidenceLevel = ConfidenceLevel.PROBABLE,
    ) -> DecisionRecord:
        """Create a verifiable structured decision record (Section 7.4)."""
        return DecisionRecord(
            decision_id=f"dec_{int(time.time() * 1000)}",
            objective=objective,
            available_evidence=[f"Selected action: {action.value}"],
            relevant_constraints=constraints or [],
            candidate_options=[],
            selected_option=action.value,
            reasons_for_selection=reasons,
            risks=[risk_level.value],
            rejected_alternatives=[],
            verification_requirements=["Verify execution outcome against post-conditions"],
            confidence_level=confidence,
            timestamp=time.time(),
        )
