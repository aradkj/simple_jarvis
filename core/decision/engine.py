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

from core.persian.models import (
    ConfidenceLevel,
    DecisionRecord,
    RiskLevel,
    SemanticInterpretation,
    TaskComplexity,
)
from infrastructure.logging import get_logger

logger = get_logger("core.decision")


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

    DESTRUCTIVE_KEYWORDS = ("delete", "remove", "drop", "wipe", "format", "پاک", "حذف", "دیلیت")
    SENSITIVE_KEYWORDS = (
        "password",
        "secret",
        "token",
        "credential",
        "private_key",
        "پسورد",
        "رمز",
    )
    EXTERNAL_COMM_KEYWORDS = ("email", "send_email", "whatsapp", "post_message", "ارسال")

    def classify_risk(self, tool_name: str, params: dict[str, Any] | None = None) -> RiskLevel:
        """Classify tool and parameters into strong RiskLevel enum."""
        t_lower = tool_name.lower()
        p_str = str(params or {}).lower()

        # 1. Destructive operations
        if any(k in t_lower or k in p_str for k in self.DESTRUCTIVE_KEYWORDS):
            if "force" in p_str or "all" in p_str:
                return RiskLevel.IRREVERSIBLE_OPERATION
            return RiskLevel.DESTRUCTIVE_OPERATION

        # 2. Sensitive data access
        if any(k in p_str for k in self.SENSITIVE_KEYWORDS):
            return RiskLevel.SENSITIVE_DATA_ACCESS

        # 3. External communications
        if any(k in t_lower for k in self.EXTERNAL_COMM_KEYWORDS):
            return RiskLevel.EXTERNAL_COMMUNICATION

        # 4. Modifications
        if any(
            k in t_lower for k in ("write", "create", "modify", "update", "rename", "edit", "touch")
        ):
            return RiskLevel.REVERSIBLE_MODIFICATION

        # 5. Default: Read-only
        return RiskLevel.READ_ONLY


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
