"""Structured planning, task decomposition, and dynamic replanning for JARVIS Phase 3."""

from __future__ import annotations

import contextlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ai.manager import ProviderManager
from config import Settings, get_settings
from core.events import AgentEvent, AgentEventType, EventBus
from core.execution_context import ExecutionContext
from core.tool_proposal import ToolDefinition
from infrastructure.logging import get_logger
from memory.base import ConversationMessage

logger = get_logger("planner")


class StepType(StrEnum):
    """Categorized purpose of an individual plan step."""

    THOUGHT = "thought"  # Logical reasoning or deduction
    TOOL_CALL = "tool_call"  # Action to be proposed to tool registry
    INFORMATION = "information"  # Data retrieval or context lookup
    REPLAN = "replan"  # Corrective replanning step
    SYNTHESIS = "synthesis"  # Consolidating intermediate results into final response


class StepStatus(StrEnum):
    """Execution status of a single plan step."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_APPROVAL = "waiting_approval"


class PlanValidationError(Exception):
    """Raised when structured plan payload fails validation rules."""


@dataclass
class PlanStep:
    """Represents a discrete, bounded step in an execution plan."""

    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    step_type: StepType = StepType.THOUGHT
    tool_name: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)  # step_ids that must complete first
    required_capability: str | None = None
    status: StepStatus = StepStatus.PENDING
    retry_count: int = 0
    max_retries: int = 2
    result: Any = None
    error: str | None = None
    tool_proposal_id: str | None = None

    def can_execute(self, completed_step_ids: set[str]) -> bool:
        """Check whether all prerequisite dependencies for this step have completed."""
        if self.status != StepStatus.PENDING:
            return False
        return all(dep in completed_step_ids for dep in self.dependencies)

    def to_dict(self) -> dict[str, Any]:
        """Convert step to dictionary."""
        return {
            "step_id": self.step_id,
            "description": self.description,
            "step_type": self.step_type.value,
            "tool_name": self.tool_name,
            "parameters": self.parameters,
            "dependencies": self.dependencies,
            "required_capability": self.required_capability,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "result": self.result,
            "error": self.error,
        }


@dataclass
class Plan:
    """Represents an ordered, validated sequence of plan steps for an agent task."""

    goal: str
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    estimated_complexity: str = "medium"
    missing_information: list[str] = field(default_factory=list)
    completion_condition: str = "Goal fully satisfied"
    is_completed: bool = False
    iteration: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def add_step(self, step: PlanStep) -> None:
        """Add a step to the plan."""
        self.steps.append(step)

    def get_step(self, step_id: str) -> PlanStep | None:
        """Find a step by ID."""
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None

    def get_completed_step_ids(self) -> set[str]:
        """Return set of IDs for completed steps."""
        return {s.step_id for s in self.steps if s.status == StepStatus.COMPLETED}

    def get_executable_steps(self) -> list[PlanStep]:
        """Return pending steps whose dependencies are all satisfied."""
        completed = self.get_completed_step_ids()
        return [s for s in self.steps if s.can_execute(completed)]

    def is_blocked(self) -> bool:
        """True if there are pending steps, but none can execute due to unmet dependencies or failures."""
        pending = [s for s in self.steps if s.status == StepStatus.PENDING]
        if not pending:
            return False
        executable = self.get_executable_steps()
        return len(executable) == 0

    def all_completed(self) -> bool:
        """True if all steps are completed or skipped."""
        return all(s.status in (StepStatus.COMPLETED, StepStatus.SKIPPED) for s in self.steps)

    def has_failed_steps(self) -> bool:
        """True if any step has failed without remaining retries."""
        return any(s.status == StepStatus.FAILED for s in self.steps)

    def validate_acyclic(self) -> None:
        """Verify the plan dependency graph contains no cycles."""
        step_ids = {s.step_id for s in self.steps}
        # Check invalid dependency references
        for s in self.steps:
            for dep in s.dependencies:
                if dep not in step_ids:
                    raise PlanValidationError(
                        f"Step '{s.step_id}' depends on non-existent step '{dep}'."
                    )
                if dep == s.step_id:
                    raise PlanValidationError(f"Step '{s.step_id}' cannot depend on itself.")

        # Cycle detection via topological sort
        visited: set[str] = set()
        rec_stack: set[str] = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            rec_stack.add(node)
            step = self.get_step(node)
            if step:
                for dep in step.dependencies:
                    if dep not in visited:
                        if dfs(dep):
                            return True
                    elif dep in rec_stack:
                        return True
            rec_stack.remove(node)
            return False

        for sid in step_ids:
            if sid not in visited and dfs(sid):
                raise PlanValidationError(
                    "Plan dependency graph contains a circular dependency cycle."
                )

    def to_dict(self) -> dict[str, Any]:
        """Convert full plan to dictionary representation."""
        return {
            "plan_id": self.plan_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "goal": self.goal,
            "estimated_complexity": self.estimated_complexity,
            "completion_condition": self.completion_condition,
            "missing_information": self.missing_information,
            "iteration": self.iteration,
            "is_completed": self.is_completed,
            "steps": [s.to_dict() for s in self.steps],
        }


class AgentPlanner:
    """Reasoning planner decomposing user requests into validated multi-step plans."""

    def __init__(
        self,
        provider_manager: ProviderManager,
        settings: Settings | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.provider_manager = provider_manager
        self.settings = settings or get_settings()
        self.event_bus = event_bus

    def should_plan(
        self,
        prompt: str,
        history: list[ConversationMessage] | None = None,
    ) -> bool:
        """Analyze user input to determine whether multi-step planning is required."""
        cleaned = prompt.strip().lower()

        # Action cues for tools (audio, volume, system control, files, inspection)
        action_cues = [
            # Audio & Sound (English & Persian)
            "mute",
            "unmute",
            "volume",
            "sound",
            "audio",
            "speaker",
            "headphone",
            "quiet",
            "silent",
            "loud",
            "louder",
            "quieter",
            "صدا",
            "صوت",
            "ولوم",
            "میزان صدا",
            "بلندی صدا",
            "بیصدا",
            "بی‌صدا",
            "صامت",
            "میوت",
            "قطع",
            "وصل",
            # Windows & Desktop Control
            "app",
            "application",
            "window",
            "program",
            "launch",
            "open",
            "close",
            "kill",
            "minimize",
            "maximize",
            "restore",
            "focus",
            "display",
            "brightness",
            "monitor",
            "screen",
            "power",
            "battery",
            "sleep",
            "lock",
            "restart",
            "reboot",
            "shutdown",
            "status",
            "overview",
            "info",
            "notepad",
            "calc",
            "calculator",
            "برنامه",
            "اپلیکیشن",
            "نرم‌افزار",
            "پنجره",
            "روشنایی",
            "نور صفحه",
            "باتری",
            "خواب",
            "قفل",
            "ریستارت",
            "ریبوت",
            "خاموش",
            "نوتپد",
            "یادداشت",
            "ماشین حساب",
            "باز کن",
            "بازکن",
            "ببند",
            "اجرا کن",
            # System Inspection & File
            "calculate",
            "search",
            "find out",
            "compare",
            "step by step",
            "first",
            "and then",
            "plan",
            "investigate",
            "weather",
            "check",
            "compute",
            "analyze",
            "cpu",
            "memory",
            "ram",
            "disk",
            "drive",
            "network",
            "interface",
            "spec",
            "specification",
            "hardware",
            "file",
            "directory",
            "read",
            "list",
            "در مرحله اول",
            "محاسبه کن",
            "جستجو کن",
            "سیستم",
            "دستگاه",
            "لپتاپ",
            "لپ‌تاپ",
            "کامپیوتر",
            "پردازنده",
            "رم",
            "حافظه",
            "دیسک",
            "شبکه",
            "فایل",
            "پوشه",
            # Browser & Web (Phase 7)
            "browse",
            "browser",
            "website",
            "webpage",
            "web page",
            "url",
            "http",
            "https",
            "search the web",
            "search internet",
            "tab",
            "tabs",
            "screenshot",
            "scroll",
            "refresh",
            "reload",
            "headings",
            "links",
            "مرورگر",
            "سایت",
            "وبسایت",
            "صفحه وب",
            "آدرس",
            "جستجو در اینترنت",
            "جستجو در وب",
            "سرچ در اینترنت",
            "اسکرینشات",
            "اسکرین شات",
            "اسکرول",
            "تب",
            "زبانه",
            "رفرش",
            "بارگذاری مجدد",
            "تیترها",
            "سرفصل‌ها",
            "پیوندها",
        ]
        if any(cue in cleaned for cue in action_cues):
            return True

        # Simple conversational queries and greetings do not require multi-step planning
        simple_patterns = [
            r"^(hi|hello|hey|greetings|howdy)\b",
            r"^who are you\b",
            r"^what is your name\b",
            r"^how are you\b",
            r"^what time is it\b",
            r"^thank(s| you)\b",
            r"^bye|goodbye\b",
            r"^(سلام|درود|چطوری|خوبی|خسته نباشید|ممنون|تشکر)\b",
        ]
        for pat in simple_patterns:
            if re.match(pat, cleaned):
                return False

        # Complex multi-clause requests (multiple sentences or punctuation indicators)
        return bool(len(prompt.split()) > 15 or "\n" in prompt)

    def _extract_json_payload(self, text: str) -> dict[str, Any]:
        """Safely extract and parse JSON object from LLM response text."""
        # 1. Check for markdown code fences
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if match:
            raw_json = match.group(1)
        else:
            # 2. Extract first matching curly brace block
            match_bare = re.search(r"(\{.*\})", text, re.DOTALL)
            raw_json = match_bare.group(1) if match_bare else text.strip()

        try:
            parsed = json.loads(raw_json)
            if not isinstance(parsed, dict):
                raise PlanValidationError("Plan payload must be a JSON object.")
            return parsed
        except json.JSONDecodeError as exc:
            raise PlanValidationError(f"Malformed JSON plan output: {exc}") from exc

    def create_plan(
        self,
        goal: str,
        context: ExecutionContext,
        available_tools: list[ToolDefinition] | None = None,
        history: list[ConversationMessage] | None = None,
    ) -> Plan:
        """Decompose goal into a validated structured Plan via ProviderManager."""
        if context.is_cancelled():
            raise PlanValidationError("Planning cancelled before generation.")

        if self.event_bus:
            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.ANALYSIS_STARTED,
                    payload={"goal": goal, "session_id": context.session_id},
                )
            )

        tools_desc = ""
        if available_tools:
            tools_desc = "\nAvailable Tools:\n" + "\n".join(
                [
                    f"- {t.name}: {t.description} (params: {json.dumps(t.parameters_schema)})"
                    for t in available_tools
                ]
            )

        allow_cloud_mem = getattr(self.settings, "memory_allow_cloud_transmission", False)
        mem_ctx = getattr(context, "memory_context", "") if allow_cloud_mem else ""
        mem_block = f"\n{mem_ctx}\n" if mem_ctx else ""
        planning_prompt = (
            f"You are JARVIS's task decomposition planner. Analyze the user's goal and generate a structured JSON execution plan.\n"
            f"{mem_block}"
            f"User Goal: {goal}\n"
            f"{tools_desc}\n\n"
            f"You MUST respond ONLY with a valid JSON object matching this exact structure:\n"
            f"{{\n"
            f'  "goal": "{goal}",\n'
            f'  "estimated_complexity": "low|medium|high",\n'
            f'  "completion_condition": "exact condition verifying completion",\n'
            f'  "missing_information": [],\n'
            f'  "steps": [\n'
            f"    {{\n"
            f'      "description": "Clear description of action",\n'
            f'      "step_type": "thought|tool_call|information|synthesis",\n'
            f'      "tool_name": "tool_name_if_applicable_or_null",\n'
            f'      "parameters": {{}},\n'
            f'      "dependencies": []\n'
            f"    }}\n"
            f"  ]\n"
            f"}}\n"
            f"Rules:\n"
            f"1. Maximum {self.settings.agent_max_execution_steps} steps.\n"
            f"2. Never use tools not listed above.\n"
            f"3. Final step should usually be synthesis.\n"
            f"4. Output JSON ONLY without conversational filler."
        )

        try:
            resp = self.provider_manager.generate_text(
                prompt=planning_prompt,
                history=history,
                cancellation_token=context.cancellation_token,
            )
            data = self._extract_json_payload(resp.text)
        except Exception as exc:
            logger.warning(
                f"Structured plan generation via model failed: {exc}. Falling back to default deterministic decomposition."
            )
            data = self._build_fallback_plan_dict(goal, available_tools)

        plan = self._build_and_validate_plan(data, goal, context)

        if self.event_bus:
            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.PLAN_CREATED,
                    payload={
                        "plan_id": plan.plan_id,
                        "task_id": plan.task_id,
                        "session_id": plan.session_id,
                        "step_count": len(plan.steps),
                        "goal": plan.goal,
                    },
                )
            )

        return plan

    def replan(
        self,
        current_plan: Plan,
        failed_step: PlanStep,
        error_reason: str,
        context: ExecutionContext,
        available_tools: list[ToolDefinition] | None = None,
    ) -> Plan:
        """Dynamically adapt and revise the plan after an execution step failure."""
        if context.is_cancelled():
            raise PlanValidationError("Replanning cancelled by user.")

        if current_plan.iteration >= self.settings.agent_max_planning_iterations:
            raise PlanValidationError(
                f"Maximum planning iterations ({self.settings.agent_max_planning_iterations}) exceeded."
            )

        if self.event_bus:
            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.REPLANNING_STARTED,
                    payload={
                        "plan_id": current_plan.plan_id,
                        "failed_step_id": failed_step.step_id,
                        "error_reason": error_reason,
                        "iteration": current_plan.iteration + 1,
                    },
                )
            )

        # Mark failed step
        failed_step.status = StepStatus.FAILED
        failed_step.error = error_reason

        # Create revised plan
        revised_plan = Plan(
            goal=current_plan.goal,
            task_id=current_plan.task_id,
            session_id=current_plan.session_id,
            iteration=current_plan.iteration + 1,
            completion_condition=current_plan.completion_condition,
        )

        # Preserve already completed steps
        completed_steps = [s for s in current_plan.steps if s.status == StepStatus.COMPLETED]
        for s in completed_steps:
            revised_plan.add_step(s)

        # Append replan corrective thought step
        replan_step = PlanStep(
            description=f"Analyze failure in '{failed_step.description}' ({error_reason}) and attempt alternate recovery",
            step_type=StepType.REPLAN,
            status=StepStatus.COMPLETED,
            result={"failed_step": failed_step.description, "error": error_reason},
        )
        revised_plan.add_step(replan_step)

        # Append final synthesis fallback step to conclude gracefully
        recovery_step = PlanStep(
            description=f"Synthesize response explaining partial completion due to: {error_reason}",
            step_type=StepType.SYNTHESIS,
            dependencies=[replan_step.step_id],
            status=StepStatus.PENDING,
        )
        revised_plan.add_step(recovery_step)

        if self.event_bus:
            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.PLAN_UPDATED,
                    payload={
                        "plan_id": revised_plan.plan_id,
                        "task_id": revised_plan.task_id,
                        "iteration": revised_plan.iteration,
                        "new_step_count": len(revised_plan.steps),
                    },
                )
            )

        return revised_plan

    def _normalize_persian_digits(self, text: str) -> str:
        """Convert Persian and Arabic numerals to ASCII digits."""
        fa_digits = "۰۱۲۳۴۵۶۷۸۹"
        ar_digits = "٠١٢٣٤٥٦٧٨٩"
        en_digits = "0123456789"
        trans = str.maketrans(fa_digits + ar_digits, en_digits + en_digits)
        return text.translate(trans)

    def _detect_audio_intent(self, goal: str, tool_names: set[str]) -> dict[str, Any] | None:
        """Deterministically detect Persian and English audio control intents and parameters."""
        normalized = self._normalize_persian_digits(goal.strip().lower())

        # 1. Check Unmute
        unmute_cues = [
            "unmute",
            "un-mute",
            "از حالت بیصدا",
            "از حالت بی صدا",
            "از بیصدا",
            "خارج کن از بیصدا",
            "آنمیوت",
            "restore sound",
            "restore audio",
            "restore system audio",
            "restore the audio",
            "turn on sound",
            "turn on the sound",
            "sound on",
            "صدا رو باز کن",
            "صدا را باز",
            "صدا را وصل",
            "صدا رو وصل",
            "صدای سیستم رو وصل",
            "صدای لپتاپ رو وصل",
            "صدای دستگاه رو وصل",
        ]
        if "windows_audio_set_mute" in tool_names and any(cue in normalized for cue in unmute_cues):
            return {
                "description": "Unmute Windows master audio output and verify state",
                "step_type": "tool_call",
                "tool_name": "windows_audio_set_mute",
                "parameters": {"mute": False},
                "dependencies": [],
            }

        # 2. Check Mute
        mute_cues = [
            "mute",
            "میوت",
            "قطع کن",
            "قطعش کن",
            "بیصدا",
            "بی‌صدا",
            "بی صدا",
            "صامت",
            "turn off sound",
            "turn off the sound",
            "silence audio",
            "silence the audio",
            "sound off",
            "kill sound",
            "صدا رو ببند",
            "صدا را قطع",
            "صدای سیستم رو قطع",
            "صدای لپتاپ رو قطع",
            "صدای دستگاه رو قطع",
        ]
        if "windows_audio_set_mute" in tool_names and any(cue in normalized for cue in mute_cues):
            return {
                "description": "Mute Windows master audio output and verify state",
                "step_type": "tool_call",
                "tool_name": "windows_audio_set_mute",
                "parameters": {"mute": True},
                "dependencies": [],
            }

        # 3. Check Set Volume Percentage
        vol_cues = ["volume", "sound", "صدا", "ولوم", "میزان صدا", "درصد", "%"]
        if "windows_audio_set_volume" in tool_names and any(c in normalized for c in vol_cues):
            m = re.search(r"(\d{1,3})\s*(?:%|درصد|percent)?", normalized)
            if m:
                with contextlib.suppress(ValueError):
                    val = float(m.group(1))
                    if 0.0 <= val <= 100.0:
                        return {
                            "description": f"Set Windows master audio volume to {val}% and verify state",
                            "step_type": "tool_call",
                            "tool_name": "windows_audio_set_volume",
                            "parameters": {"percent": val},
                            "dependencies": [],
                        }

        # 4. Check Relative Volume (Increase / Decrease)
        if "windows_audio_set_volume" in tool_names:
            if any(
                k in normalized
                for k in (
                    "زیاد کن",
                    "بلندتر کن",
                    "بالا ببر",
                    "increase",
                    "volume up",
                    "louder",
                    "زیاد",
                    "بلند",
                )
            ) and any(
                c in normalized
                for c in ("volume", "sound", "audio", "صدا", "ولوم", "لپتاپ", "سیستم")
            ):
                return {
                    "description": "Increase Windows master audio volume and verify state",
                    "step_type": "tool_call",
                    "tool_name": "windows_audio_set_volume",
                    "parameters": {"percent": 75.0},
                    "dependencies": [],
                }
            if any(
                k in normalized
                for k in (
                    "کم کن",
                    "آهسته‌تر کن",
                    "پایین بیار",
                    "decrease",
                    "volume down",
                    "quieter",
                    "کم",
                    "آهسته",
                )
            ) and any(
                c in normalized
                for c in ("volume", "sound", "audio", "صدا", "ولوم", "لپتاپ", "سیستم")
            ):
                return {
                    "description": "Decrease Windows master audio volume and verify state",
                    "step_type": "tool_call",
                    "tool_name": "windows_audio_set_volume",
                    "parameters": {"percent": 25.0},
                    "dependencies": [],
                }

        # 5. Check Audio Status Query
        if "windows_audio_get_status" in tool_names and any(
            k in normalized
            for k in (
                "وضعیت صدا",
                "میزان صدا چقدره",
                "چقدره صدا",
                "audio status",
                "what is the volume",
                "is audio muted",
            )
        ):
            return {
                "description": "Query Windows master audio volume percentage and mute state",
                "step_type": "tool_call",
                "tool_name": "windows_audio_get_status",
                "parameters": {},
                "dependencies": [],
            }

        return None

    def _detect_system_intent(self, goal: str, tool_names: set[str]) -> dict[str, Any] | None:
        """Detect system diagnostic requests (CPU, RAM, Disk, Network, System overview)."""
        norm = self._normalize_persian_digits(goal.strip().lower())
        cpu_tool = next(
            (t for t in ("system_get_cpu_info", "system_cpu_info") if t in tool_names), None
        )
        if cpu_tool and any(k in norm for k in ("cpu", "پردازنده", "مصرف پردازنده", "پردازشگر")):
            return {
                "description": "Query Windows CPU usage and clock frequency",
                "step_type": "tool_call",
                "tool_name": cpu_tool,
                "parameters": {},
                "dependencies": [],
            }
        mem_tool = next(
            (t for t in ("system_get_memory_info", "system_memory_info") if t in tool_names), None
        )
        if mem_tool and any(k in norm for k in ("ram", "memory", "رم", "حافظه")):
            return {
                "description": "Query Windows physical and virtual memory usage",
                "step_type": "tool_call",
                "tool_name": mem_tool,
                "parameters": {},
                "dependencies": [],
            }
        disk_tool = next(
            (t for t in ("system_get_disk_info", "system_disk_info") if t in tool_names), None
        )
        if disk_tool and any(
            k in norm for k in ("disk", "drive", "دیسک", "فضای دیسک", "حافظه داخلی")
        ):
            return {
                "description": "Query Windows disk drives and partition usage",
                "step_type": "tool_call",
                "tool_name": disk_tool,
                "parameters": {},
                "dependencies": [],
            }
        net_tool = next(
            (t for t in ("system_get_network_info", "system_network_info") if t in tool_names), None
        )
        if net_tool and any(k in norm for k in ("network", "شبکه", "اینترنت", "اتصال شبکه")):
            return {
                "description": "Query Windows network adapters and IP configurations",
                "step_type": "tool_call",
                "tool_name": net_tool,
                "parameters": {},
                "dependencies": [],
            }
        overview_tool = next(
            (t for t in ("system_get_overview", "system_overview") if t in tool_names), None
        )
        if overview_tool and any(
            k in norm
            for k in ("system status", "status", "وضعیت سیستم", "مشخصات سیستم", "نمای کلی سیستم")
        ):
            return {
                "description": "Query comprehensive Windows OS, hardware, and uptime overview",
                "step_type": "tool_call",
                "tool_name": overview_tool,
                "parameters": {},
                "dependencies": [],
            }
        return None

    def _detect_desktop_intent(self, goal: str, tool_names: set[str]) -> dict[str, Any] | None:
        """Detect desktop actions (App launch, window minimize, display, power)."""
        norm = self._normalize_persian_digits(goal.strip().lower())
        if (
            "windows_app_launch" in tool_names
            and any(k in norm for k in ("notepad", "نوتپد", "یادداشت"))
            and any(
                w in norm for w in ("open", "launch", "start", "run", "باز کن", "اجرا کن", "بازکن")
            )
        ):
            return {
                "description": "Launch Notepad application",
                "step_type": "tool_call",
                "tool_name": "windows_app_launch",
                "parameters": {"app_id": "notepad"},
                "dependencies": [],
            }
        if "windows_display_get_brightness" in tool_names and any(
            k in norm for k in ("brightness", "روشنایی", "نور صفحه", "نور مانیتور")
        ):
            return {
                "description": "Query display brightness level",
                "step_type": "tool_call",
                "tool_name": "windows_display_get_brightness",
                "parameters": {},
                "dependencies": [],
            }
        if "windows_power_get_status" in tool_names and any(
            k in norm for k in ("battery", "power", "باتری", "شارژ", "وضعیت برق", "وضعیت باتری")
        ):
            return {
                "description": "Query Windows power and battery status",
                "step_type": "tool_call",
                "tool_name": "windows_power_get_status",
                "parameters": {},
                "dependencies": [],
            }
        if "windows_window_minimize" in tool_names and any(
            k in norm for k in ("minimize", "کوچک کن", "کمینه کن", "مینیمایز")
        ):
            return {
                "description": "Minimize window",
                "step_type": "tool_call",
                "tool_name": "windows_window_minimize",
                "parameters": {},
                "dependencies": [],
            }
        return None

    def _detect_browser_intent(self, goal: str, tool_names: set[str]) -> dict[str, Any] | None:
        """Detect browser actions (Navigate, Search, Read, Links, Headings, Screenshot, Tabs, Scroll)."""
        norm = self._normalize_persian_digits(goal.strip().lower())

        # 1. Search the web
        if "browser_search" in tool_names and any(
            cue in norm
            for cue in (
                "search the web for",
                "search the web",
                "search internet for",
                "search internet",
                "در اینترنت جستجو کن",
                "در اینترنت درباره",
                "در اینترنت سرچ کن",
                "در وب جستجو کن",
                "در وب سرچ کن",
                "جستجو در اینترنت",
                "جستجو در وب",
            )
        ):
            clean_query = goal
            for prefix in (
                "search the web for",
                "search the web",
                "search internet for",
                "search internet",
                "در اینترنت درباره",
                "در اینترنت جستجو کن",
                "در اینترنت سرچ کن",
                "در وب جستجو کن",
                "در وب سرچ کن",
                "جستجو در اینترنت",
                "جستجو در وب",
            ):
                if prefix in norm:
                    idx = norm.find(prefix) + len(prefix)
                    clean_query = goal[idx:].strip(" :.-،")
                    for suffix in ("رو جستجو کن", "رو سرچ کن", "جستجو کن", "سرچ کن", "بگرد"):
                        if clean_query.endswith(suffix):
                            clean_query = clean_query[: -len(suffix)].strip()
                    break
            if not clean_query:
                clean_query = goal
            return {
                "description": f"Search the web for '{clean_query}'",
                "step_type": "tool_call",
                "tool_name": "browser_search",
                "parameters": {"query": clean_query, "num_results": 5},
                "dependencies": [],
            }

        # 2. Screenshot
        if "browser_screenshot" in tool_names and any(
            cue in norm
            for cue in (
                "screenshot",
                "اسکرینشات",
                "اسکرین شات",
                "عکس از صفحه",
                "عکس صفحه",
                "تصویر صفحه",
                "capture page",
            )
        ):
            return {
                "description": "Capture screenshot of the current web page",
                "step_type": "tool_call",
                "tool_name": "browser_screenshot",
                "parameters": {"full_page": False},
                "dependencies": [],
            }

        # 3. Headings
        if "browser_get_headings" in tool_names and any(
            cue in norm
            for cue in (
                "headings",
                "تیترها",
                "تیترهای صفحه",
                "عنوان و تیترهای صفحه",
                "سرفصل‌ها",
                "سرفصلهای صفحه",
                "show page headings",
                "page headings",
            )
        ):
            return {
                "description": "Extract heading structure and outline from the web page",
                "step_type": "tool_call",
                "tool_name": "browser_get_headings",
                "parameters": {"max_depth": 3},
                "dependencies": [],
            }

        # 4. Links
        if "browser_get_links" in tool_names and any(
            cue in norm
            for cue in (
                "links",
                "لینک‌ها",
                "لینکها",
                "پیوندها",
                "پیوندهای صفحه",
                "لینک‌های این صفحه",
                "لینکهای این صفحه",
                "extract all relevant links",
                "extract links",
            )
        ):
            return {
                "description": "Extract links from the web page",
                "step_type": "tool_call",
                "tool_name": "browser_get_links",
                "parameters": {"max_links": 50},
                "dependencies": [],
            }

        # 5. Page Content / Summarize
        if "browser_get_page_content" in tool_names and any(
            cue in norm
            for cue in (
                "محتوای این صفحه",
                "محتوای صفحه",
                "متن این صفحه",
                "متن صفحه",
                "خلاصه کن این صفحه",
                "صفحه رو خلاصه کن",
                "اطلاعات این جدول",
                "اطلاعات جدول",
                "summarize this page",
                "summarize page",
                "extract page text",
                "page content",
                "read page",
                "extract the table",
            )
        ):
            return {
                "description": "Extract visible text content from the current web page",
                "step_type": "tool_call",
                "tool_name": "browser_get_page_content",
                "parameters": {"max_chars": 16000},
                "dependencies": [],
            }

        # 6. Tab Management
        if "browser_tab_new" in tool_names and any(
            cue in norm
            for cue in ("تب جدید", "زبانه جدید", "new tab", "open a new tab", "open new tab")
        ):
            return {
                "description": "Open a new browser tab",
                "step_type": "tool_call",
                "tool_name": "browser_tab_new",
                "parameters": {},
                "dependencies": [],
            }

        if "browser_tab_close" in tool_names and any(
            cue in norm
            for cue in (
                "ببند تب",
                "تب رو ببند",
                "تب را ببند",
                "این تب رو ببند",
                "تب فعلی رو ببند",
                "close tab",
                "close the tab",
                "close this tab",
                "close current tab",
            )
        ):
            return {
                "description": "Close the active browser tab",
                "step_type": "tool_call",
                "tool_name": "browser_tab_close",
                "parameters": {},
                "dependencies": [],
            }

        if "browser_tab_list" in tool_names and any(
            cue in norm
            for cue in (
                "لیست تب‌ها",
                "لیست تبها",
                "تب‌های باز",
                "تبهای باز",
                "list tabs",
                "show tabs",
                "open tabs",
            )
        ):
            return {
                "description": "List all open browser tabs",
                "step_type": "tool_call",
                "tool_name": "browser_tab_list",
                "parameters": {},
                "dependencies": [],
            }

        if "browser_tab_switch" in tool_names and any(
            cue in norm
            for cue in (
                "تب قبلی",
                "تب بعدی",
                "سوییچ کن به تب",
                "برو به تب",
                "switch to tab",
                "switch tab",
            )
        ):
            target_idx = 0
            if "قبلی" in norm or "previous" in norm:
                target_idx = 0
            elif "بعدی" in norm or "next" in norm:
                target_idx = 1
            else:
                m = re.search(r"\d+", norm)
                if m:
                    target_idx = int(m.group(0))
            return {
                "description": f"Switch to browser tab {target_idx}",
                "step_type": "tool_call",
                "tool_name": "browser_tab_switch",
                "parameters": {"tab_index": target_idx},
                "dependencies": [],
            }

        # 7. Navigation History (Back, Forward, Reload)
        if "browser_go_back" in tool_names and any(
            cue in norm
            for cue in (
                "به تب قبلی برگرد",
                "به صفحه قبلی برگرد",
                "صفحه قبل",
                "برگرد عقب",
                "برو عقب",
                "go back",
                "back to previous",
            )
        ):
            return {
                "description": "Navigate back in browser history",
                "step_type": "tool_call",
                "tool_name": "browser_go_back",
                "parameters": {"steps": 1},
                "dependencies": [],
            }

        if "browser_go_forward" in tool_names and any(
            cue in norm for cue in ("صفحه بعد", "برو جلو", "go forward")
        ):
            return {
                "description": "Navigate forward in browser history",
                "step_type": "tool_call",
                "tool_name": "browser_go_forward",
                "parameters": {"steps": 1},
                "dependencies": [],
            }

        if "browser_reload" in tool_names and any(
            cue in norm
            for cue in (
                "رفرش کن",
                "بارگذاری مجدد",
                "دوباره لود کن",
                "reload",
                "refresh the page",
                "refresh page",
            )
        ):
            return {
                "description": "Reload the current web page",
                "step_type": "tool_call",
                "tool_name": "browser_reload",
                "parameters": {"ignore_cache": False},
                "dependencies": [],
            }

        # 8. Scroll
        if "browser_scroll" in tool_names and any(
            cue in norm for cue in ("scroll", "اسکرول", "برو پایین", "برو بالا", "پایین صفحه")
        ):
            direction = "down"
            if "بالا" in norm or "up" in norm or "top" in norm:
                direction = "up"
            return {
                "description": f"Scroll page {direction}",
                "step_type": "tool_call",
                "tool_name": "browser_scroll",
                "parameters": {"direction": direction, "amount": 500},
                "dependencies": [],
            }

        # 9. Navigate to URL / Website
        if "browser_navigate" in tool_names and any(
            cue in norm
            for cue in (
                "باز کن",
                "بازکن",
                "برو به",
                "سایت",
                "وبسایت",
                "صفحه",
                "open",
                "navigate to",
                "go to",
                "http://",
                "https://",
                "://",
                "www.",
                ".com",
                ".org",
                ".io",
                ".ir",
                ".net",
            )
        ):
            target_url = ""
            url_match = re.search(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+", goal)
            if url_match:
                target_url = url_match.group(0).rstrip(".,;")
            else:
                domain_match = re.search(r"([a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)", goal)
                if domain_match:
                    target_url = f"https://{domain_match.group(1).rstrip('.,;')}"
                elif any(k in norm for k in ("گوگل", "google")):
                    target_url = "https://www.google.com"
                elif any(k in norm for k in ("گیت‌هاب", "گیت هاب", "github")):
                    target_url = "https://github.com"
                elif any(k in norm for k in ("ویکی‌پدیا", "wikipedia")):
                    target_url = "https://en.wikipedia.org"
                elif any(k in norm for k in ("fastapi",)):
                    target_url = "https://fastapi.tiangolo.com"
                elif any(k in norm for k in ("python",)):
                    target_url = "https://www.python.org"

            if target_url:
                return {
                    "description": f"Navigate browser to '{target_url}'",
                    "step_type": "tool_call",
                    "tool_name": "browser_navigate",
                    "parameters": {"url": target_url},
                    "dependencies": [],
                }

        return None

    def _build_fallback_plan_dict(
        self, goal: str, available_tools: list[ToolDefinition] | None = None
    ) -> dict[str, Any]:
        """Produce safe deterministic fallback plan when LLM structured generation fails."""
        steps: list[dict[str, Any]] = [
            {
                "description": f"Analyze goal: {goal}",
                "step_type": "thought",
                "tool_name": None,
                "parameters": {},
                "dependencies": [],
            }
        ]
        tool_names = {t.name for t in (available_tools or [])}

        # Priority 1: Check audio control intent
        audio_step = self._detect_audio_intent(goal, tool_names)
        if audio_step:
            steps.append(audio_step)
        # Priority 2: Check browser agent intent
        elif browser_step := self._detect_browser_intent(goal, tool_names):
            steps.append(browser_step)
        # Priority 3: Check system diagnostic intent
        elif sys_step := self._detect_system_intent(goal, tool_names):
            steps.append(sys_step)
        # Priority 4: Check desktop control intent
        elif desk_step := self._detect_desktop_intent(goal, tool_names):
            steps.append(desk_step)
        # Priority 4: Match mock search if query mentions search/find
        elif "mock_search" in tool_names and any(
            k in goal.lower() for k in ("search", "find", "who", "what")
        ):
            steps.append(
                {
                    "description": f"Search information for: {goal}",
                    "step_type": "tool_call",
                    "tool_name": "mock_search",
                    "parameters": {"query": goal},
                    "dependencies": [],
                }
            )
        elif "mock_calculator" in tool_names and any(
            k in goal.lower() for k in ("calculate", "math", "+", "*")
        ):
            steps.append(
                {
                    "description": "Calculate math expression",
                    "step_type": "tool_call",
                    "tool_name": "mock_calculator",
                    "parameters": {"expression": goal},
                    "dependencies": [],
                }
            )

        steps.append(
            {
                "description": "Synthesize final answer for the user",
                "step_type": "synthesis",
                "tool_name": None,
                "parameters": {},
                "dependencies": [],
            }
        )
        return {
            "goal": goal,
            "estimated_complexity": "low",
            "completion_condition": "Response formulated",
            "missing_information": [],
            "steps": steps,
        }

    def _build_and_validate_plan(
        self, data: dict[str, Any], goal: str, context: ExecutionContext
    ) -> Plan:
        """Parse dictionary and validate all plan constraints."""
        plan = Plan(
            goal=data.get("goal") or goal,
            task_id=context.task_id or str(uuid.uuid4()),
            session_id=context.session_id,
            estimated_complexity=str(data.get("estimated_complexity", "medium")),
            completion_condition=str(data.get("completion_condition", "Goal achieved")),
            missing_information=data.get("missing_information", []),
        )

        raw_steps = data.get("steps", [])
        if not isinstance(raw_steps, list) or not raw_steps:
            raise PlanValidationError("Plan must contain a non-empty list of 'steps'.")

        if len(raw_steps) > self.settings.agent_max_execution_steps:
            raise PlanValidationError(
                f"Plan step count ({len(raw_steps)}) exceeds maximum allowed limit ({self.settings.agent_max_execution_steps})."
            )

        # Mapping to resolve integer indices or string step_ids to new UUIDs
        step_id_map: dict[str, str] = {}
        parsed_steps: list[PlanStep] = []

        for idx, s_data in enumerate(raw_steps):
            if not isinstance(s_data, dict):
                continue
            desc = str(s_data.get("description", "")).strip()
            if not desc:
                desc = f"Step {idx + 1}"

            stype_str = str(s_data.get("step_type", "thought")).lower()
            try:
                stype = StepType(stype_str)
            except ValueError:
                stype = StepType.THOUGHT

            new_id = str(uuid.uuid4())
            step_id_map[str(idx)] = new_id
            step_id_map[str(idx + 1)] = new_id
            if "step_id" in s_data:
                step_id_map[str(s_data["step_id"])] = new_id

            tool_name = s_data.get("tool_name")
            if tool_name and not isinstance(tool_name, str):
                tool_name = str(tool_name)

            params = s_data.get("parameters") or {}
            if not isinstance(params, dict):
                params = {}

            step = PlanStep(
                step_id=new_id,
                description=desc,
                step_type=stype,
                tool_name=tool_name,
                parameters=params,
                status=StepStatus.PENDING,
                max_retries=self.settings.agent_max_step_retries,
            )
            parsed_steps.append(step)

        # Remap dependencies
        for idx, s_data in enumerate(raw_steps):
            raw_deps = s_data.get("dependencies", [])
            if isinstance(raw_deps, list):
                mapped_deps: list[str] = []
                for dep in raw_deps:
                    s_dep = str(dep)
                    if s_dep in step_id_map:
                        mapped_deps.append(step_id_map[s_dep])
                parsed_steps[idx].dependencies = mapped_deps

        plan.steps = parsed_steps
        plan.validate_acyclic()
        return plan
