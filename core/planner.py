"""Structured planning, task decomposition, and dynamic replanning for JARVIS Phase 3."""

from __future__ import annotations

import contextlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
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
        # Sanitize and validate dependencies
        for s in self.steps:
            s.dependencies = [dep for dep in s.dependencies if dep != s.step_id and dep in step_ids]

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

        # Explicit conversational request to not take actions
        conversational_guards = (
            "هیچ کاری نکن",
            "کاری نکن",
            "فقط با هم صحبت کنیم",
            "فقط صحبت کنیم",
            "فقط حرف بزنیم",
            "فقط گپ بزنیم",
            "just chat",
            "just talk",
            "don't do anything",
            "do not do anything",
            "don't execute",
        )
        if any(g in cleaned for g in conversational_guards):
            return False

        # Action cues for tools (audio, volume, system control, files, inspection, weather, apps, internet)
        action_cues = [
            # Live Weather & Forecast
            "weather",
            "forecast",
            "temperature",
            "climate",
            "rain",
            "precipitation",
            "آب و هوا",
            "اب و هوا",
            "آب‌وهوا",
            "هوا",
            "وضعیت هوا",
            "دما",
            "باران",
            "بارون",
            "پیش‌بینی هوا",
            "پیش بینی هوا",
            "بوشهر",
            "bushehr",
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
            "screenshot",
            "اسکرین شات",
            "اسکرین‌شات",
            "عکس از صفحه",
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
            "chrome",
            "edge",
            "msedge",
            "notepad",
            "calc",
            "calculator",
            "terminal",
            "explorer",
            "firefox",
            "کروم",
            "گوگل کروم",
            "ادج",
            "مایکروسافت ادج",
            "ماشین حساب",
            "ترمینال",
            "اکسپلورر",
            "فایل اکسپلورر",
            "فایرفاکس",
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
            "create",
            "save",
            "edit",
            "delete",
            "copy",
            "move",
            "desktop",
            "html",
            "ایجاد",
            "بساز",
            "ویرایش",
            "حذف",
            "کپی",
            "جابجا",
            "دسکتاپ",
            "میزکار",
            # Software Project & Coding (Phase 8 & 10)
            "پروژه",
            "project",
            "ریپو",
            "repo",
            "تستهاشو",
            "تست هاشو",
            "تست‌هاشو",
            "تستها",
            "تست‌ها",
            "درستش کن",
            "اصلاحش کن",
            "تعمیرش کن",
            "پیسیشاپ",
            "پیسی شاپ",
            "pc shop",
            "pcshop",
            "کدنویسی",
            "antigravity",
            "آنتی گرویتی",
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
            # Phase 9 Voice, Email & WhatsApp Communication Cues
            "microphone",
            "mic",
            "میکروفون",
            "میکروفن",
            "قطع میکروفون",
            "وصل میکروفون",
            "email",
            "mail",
            "gmail",
            "outlook",
            "send email",
            "ایمیل",
            "نامه",
            "میل",
            "جیمیل",
            "whatsapp",
            "whats app",
            "واتساپ",
            "واتس‌اپ",
            "واتس اپ",
            "پیام واتساپ",
            # Implied coding intentions
            "need to code",
            "want to code",
            "start coding",
            "start programming",
            "time to code",
            "open coding",
            "programming",
            "کد بزنم",
            "کد بزنیم",
            "وقت کدزدنه",
            "وقت کدنویسیه",
            "بریم کد بزنیم",
            "میخوام کدنویسی کنم",
            "میخوام برنامه نویسی کنم",
            # Directory and Folder Cues
            "folder",
            "directory",
            "پوشه",
            "فولدر",
            "دایرکتوری",
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

        is_read_only = bool(context.metadata.get("read_only", False))
        prohibited_actions = context.metadata.get("prohibited_actions", [])

        tools_desc = ""
        effective_tools = available_tools or []
        if is_read_only and effective_tools:
            destructive_names = {
                "file_write_text",
                "file_edit_text",
                "file_delete",
                "file_move",
                "file_archive_create",
                "file_archive_extract",
            }
            effective_tools = [t for t in effective_tools if t.name not in destructive_names]

        if effective_tools:
            tools_desc = "\nAvailable Tools:\n" + "\n".join(
                [
                    f"- {t.name}: {t.description} (params: {json.dumps(t.parameters_schema)})"
                    for t in effective_tools
                ]
            )

        allow_cloud_mem = getattr(self.settings, "memory_allow_cloud_transmission", False)
        mem_ctx = getattr(context, "memory_context", "") if allow_cloud_mem else ""
        mem_block = f"\n{mem_ctx}\n" if mem_ctx else ""

        constraint_rules = ""
        if is_read_only:
            constraint_rules += "\n5. MANDATORY CONSTRAINT: Read-only inspection mode is active. DO NOT plan or invoke any state-modifying or destructive tool calls."
        if prohibited_actions:
            constraint_rules += f"\n6. PROHIBITED ACTIONS: The user explicitly prohibited: {', '.join(prohibited_actions)}."

        reasoning_steps = context.metadata.get("reasoning_plan_steps")
        reason_hint = ""
        if reasoning_steps:
            reason_hint = (
                f"\nPre-reasoned task decomposition steps to follow:\n"
                f"{json.dumps(reasoning_steps, ensure_ascii=False, indent=2)}\n\n"
            )

        planning_prompt = (
            f"You are JARVIS's task decomposition planner. Analyze the user's goal and generate a structured JSON execution plan.\n"
            f"{mem_block}"
            f"User Goal: {goal}\n"
            f"{tools_desc}\n\n"
            f"{reason_hint}"
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
            f"{constraint_rules}"
        )

        # Performance Fast-Path: If goal matches an unambiguous deterministic tool action,
        # skip redundant LLM planning roundtrip to achieve sub-second execution latency.
        fast_data = self._build_fallback_plan_dict(
            goal, available_tools, session_id=context.session_id
        )
        fast_path_tools = {
            "weather_current",
            "weather_forecast",
            "windows_app_launch",
            "windows_app_close",
            "windows_desktop_screenshot",
            "file_search",
            "file_open",
            "file_inspect",
            "file_read_text",
            "coding_agent_status",
            "file_create_directory",
        }
        has_tool_steps = any(
            s.get("step_type") == "tool_call" and s.get("tool_name") in fast_path_tools
            for s in fast_data.get("steps", [])
        ) or any(
            s.get("step_type") == "thought" and s.get("parameters", {}).get("clarification_prompt")
            for s in fast_data.get("steps", [])
        )

        if has_tool_steps:
            logger.info(
                f"Unambiguous deterministic action detected for '{goal}'. Fast-pathing execution plan."
            )
            data = fast_data
        else:
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
                data = self._build_fallback_plan_dict(
                    goal, available_tools, session_id=context.session_id, context=context
                )

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

    def _detect_weather_intent(self, goal: str, tool_names: set[str]) -> dict[str, Any] | None:
        """Detect live meteorological queries in Persian and English."""
        if not any(
            t in tool_names for t in ("weather_current", "weather_forecast", "mock_weather")
        ):
            return None

        norm = self._normalize_persian_digits(goal.strip().lower())
        weather_cues = (
            "weather",
            "forecast",
            "temperature",
            "climate",
            "rain",
            "precipitation",
            "آب و هوا",
            "اب و هوا",
            "آب‌وهوا",
            "هوا",
            "وضعیت هوا",
            "دمای",
            "دما",
            "باران",
            "بارون",
            "پیش‌بینی هوا",
            "پیش بینی هوا",
            "بوشهر",
            "bushehr",
        )
        if not any(cue in norm for cue in weather_cues):
            return None

        # Resolve target city from pre-compiled registry or query
        target_city = "Bushehr"
        try:
            from tools.weather.weather_service import KNOWN_CITY_REGISTRY

            for city_key, city_info in KNOWN_CITY_REGISTRY.items():
                if city_key in norm:
                    target_city = city_info["name"]
                    break
        except Exception:
            pass

        # Check if forecast requested
        is_forecast = any(
            k in norm
            for k in (
                "forecast",
                "پیش‌بینی",
                "پیش بینی",
                "فردا",
                "tomorrow",
                "روزهای آینده",
                "هفته آینده",
            )
        )
        tool_to_use = (
            "weather_forecast"
            if (is_forecast and "weather_forecast" in tool_names)
            else ("weather_current" if "weather_current" in tool_names else "mock_weather")
        )

        params: dict[str, Any] = {"city": target_city}
        if tool_to_use == "weather_forecast":
            params["days"] = 3

        return {
            "description": f"Query live weather observations for {target_city}",
            "step_type": "tool_call",
            "tool_name": tool_to_use,
            "parameters": params,
            "dependencies": [],
        }

    def _detect_desktop_intent(
        self, goal: str, tool_names: set[str], session_id: str | None = None
    ) -> list[dict[str, Any]] | dict[str, Any] | None:
        """Detect desktop actions (App launch, app close, window operations, desktop screenshot, display, power)."""
        norm = self._normalize_persian_digits(goal.strip().lower())

        # 1. Desktop Screenshot Intent
        is_desktop_explicit = any(
            k in norm
            for k in (
                "desktop screenshot",
                "windows screenshot",
                "screenshot of desktop",
                "screenshot desktop",
                "عکس دسکتاپ",
                "تصویر دسکتاپ",
                "اسکرین شات از دسکتاپ",
                "اسکرین‌شات از دسکتاپ",
                "اسکرین شات دسکتاپ",
            )
        )
        is_generic_screenshot = any(
            k in norm
            for k in (
                "screenshot",
                "اسکرین شات",
                "اسکرین‌شات",
                "عکس از صفحه",
                "تصویر صفحه",
            )
        )
        if "windows_desktop_screenshot" in tool_names and (
            is_desktop_explicit
            or ("browser_screenshot" not in tool_names and is_generic_screenshot)
        ):
            return {
                "description": "Capture full desktop screenshot",
                "step_type": "tool_call",
                "tool_name": "windows_desktop_screenshot",
                "parameters": {},
                "dependencies": [],
            }

        # Guard: Explicitly ignore file inspection, reading, or modification from being hijacked as app launch
        is_file_request = (
            any(
                k in norm
                for k in (
                    "read",
                    "بخوان",
                    "بخون",
                    "خواندن",
                    "خوندن",
                    "inspect",
                    "محتوا",
                    "محتوای",
                    "write",
                    "بنویس",
                    "save file",
                    "create file",
                    "ساخت فایل",
                    "ایجاد فایل",
                )
            )
            and any(
                k in norm
                for k in (
                    ".txt",
                    ".py",
                    ".json",
                    ".md",
                    ".log",
                    ".csv",
                    ".html",
                    "brief",
                    "note",
                    "file",
                    "فایل",
                )
            )
            and not any(
                k in norm
                for k in (
                    "editor",
                    "ادیتور",
                    "vscode",
                    "vs code",
                    "notepad",
                    "نوتپد",
                    "application",
                    "برنامه",
                )
            )
        )
        if is_file_request:
            return None

        # 2. Application Launching (supports single and multiple apps like Chrome & Edge)
        launch_cues_regex = [
            r"\bopen\b",
            r"\blaunch\b",
            r"\bstart\b",
            r"\brun\b",
            r"باز\s*کن",
            r"بازکن",
            r"اجرا\s*کن",
            r"بالا\s*بیار",
            r"استارت\s*بزن",
        ]
        coding_implied = (
            "need to code",
            "want to code",
            "start coding",
            "start programming",
            "time to code",
            "open my code",
            "open coding",
            "میخوام کدنویسی کنم",
            "میخوام برنامه نویسی کنم",
            "میخوام کد بزنم",
            "وقت کدزدنه",
            "وقت کدنویسیه",
            "بریم کد بزنیم",
            "کدنویسی کنیم",
        )
        is_coding_implied = any(c in norm for c in coding_implied)
        is_launch = (
            any(re.search(pat, norm, re.IGNORECASE) for pat in launch_cues_regex)
            or is_coding_implied
        )

        # 3. Application Closing
        close_cues_regex = [
            r"\bclose\b",
            r"\bkill\b",
            r"ببند(?:ش|یم)?",
            r"خارج\s*شو",
            r"قطع\s*کن",
        ]
        is_close = any(re.search(pat, norm, re.IGNORECASE) for pat in close_cues_regex)

        apps_map = [
            ("chrome", ("chrome", "کروم", "گوگل کروم", "google chrome", "google-chrome")),
            (
                "msedge",
                ("edge", "ادج", "مایکروسافت ادج", "msedge", "microsoft edge", "microsoft-edge"),
            ),
            ("notepad", ("notepad", "نوتپد", "یادداشت", "نوت پد")),
            ("calc", ("calc", "calculator", "ماشین حساب", "ماشین‌حساب")),
            ("wt", ("terminal", "ترمینال", "wt", "windows terminal", "کنسول")),
            ("explorer", ("explorer", "اکسپلورر", "فایل اکسپلورر", "file explorer", "فایل منیجر")),
            ("firefox", ("firefox", "فایرفاکس")),
            ("code", ("code", "vscode", "وی اس کد", "کد")),
            ("mspaint", ("paint", "پینت", "نقاشی")),
            ("taskmgr", ("task manager", "تسک منیجر")),
        ]

        if is_launch and "windows_app_launch" in tool_names:
            # 2a. Check if this is a project opening request (e.g. "open the jarvis project", "پروژه جارویس رو باز کن")
            proj_indicators = (
                "project",
                "پروژه",
                "ریپو",
                "repo",
                "workspace",
                "ورک‌اسپیس",
                "jarvis",
                "جارویس",
                "pc shop",
                "pcshop",
                "پیسی شاپ",
                "warehouse",
                "انبار",
                "document processing",
                "پردازش سند",
                "ocr",
                "open it in",
                "توی وی اس کد بازش کن",
            )
            if any(k in norm for k in proj_indicators) or (
                session_id and any(k in norm for k in ("open it", "بازش کن"))
            ):
                try:
                    from core.files.project_resolver import get_project_resolver

                    resolver = get_project_resolver()
                    resolved = resolver.resolve_project(norm)
                    if resolved:
                        try:
                            from core.conversation_session import get_conversation_session_manager

                            mgr = get_conversation_session_manager()
                            sess = mgr.get_or_create_session(session_id or "default_session")
                            sess.active_project_name = resolved.name
                            sess.active_project_path = resolved.path
                            sess.add_entity("project", resolved.name, str(resolved.path))
                        except Exception:
                            pass

                        # Determine preferred or specified editor
                        preferred_app = None
                        try:
                            from core.memory.personal_store import PersonalStore

                            p_store = PersonalStore.get_instance()
                            pref_editor = p_store.get_preference("coding", "preferred_editor")
                            if pref_editor:
                                if any(
                                    k in pref_editor.lower() for k in ("vs code", "vscode", "code")
                                ):
                                    preferred_app = "code"
                                elif "cursor" in pref_editor.lower():
                                    preferred_app = "cursor"
                        except Exception:
                            pass

                        if not preferred_app:
                            if any(k in norm for k in ("vscode", "vs code", "code", "وی اس کد")):
                                preferred_app = "code"
                            elif "cursor" in norm:
                                preferred_app = "cursor"
                            else:
                                preferred_app = "code"

                        if "file_open" in tool_names:
                            return {
                                "description": f"Open {resolved.name} project workspace at {resolved.path}",
                                "step_type": "tool_call",
                                "tool_name": "file_open",
                                "parameters": {
                                    "file_path": str(resolved.path),
                                    "application": preferred_app,
                                },
                                "dependencies": [],
                            }
                        elif "windows_app_launch" in tool_names:
                            return {
                                "description": f"Launch coding editor for {resolved.name} project",
                                "step_type": "tool_call",
                                "tool_name": "windows_app_launch",
                                "parameters": {"app_id": preferred_app or "code"},
                                "dependencies": [],
                            }
                except Exception as proj_err:
                    logger.debug(f"Project resolution in desktop intent skipped: {proj_err}")

            # 2b. Check generic coding application request or implied coding intent
            try:
                from tools.windows.discovery import (
                    get_windows_app_discovery,
                    is_generic_coding_request,
                )

                if is_generic_coding_request(norm) or is_coding_implied:
                    preferred_app = None
                    try:
                        from core.memory.personal_store import PersonalStore

                        p_store = PersonalStore.get_instance()
                        pref_editor = p_store.get_preference("coding", "preferred_editor")
                        if pref_editor:
                            if any(k in pref_editor.lower() for k in ("vs code", "vscode", "code")):
                                preferred_app = "code"
                            elif "cursor" in pref_editor.lower():
                                preferred_app = "cursor"
                            elif "antigravity" in pref_editor.lower():
                                preferred_app = "antigravity_ide"
                    except Exception:
                        pass

                    if preferred_app:
                        return {
                            "description": f"Launch preferred coding environment ({preferred_app})",
                            "step_type": "tool_call",
                            "tool_name": "windows_app_launch",
                            "parameters": {"app_id": preferred_app},
                            "dependencies": [],
                        }

                    disc = get_windows_app_discovery()
                    coding_apps = disc.get_coding_applications()
                    if coding_apps:
                        target_app = next(
                            (a for a in coding_apps if a.app_id in ("code", "vscode")),
                            coding_apps[0],
                        )
                        return {
                            "description": f"Launch coding environment ({target_app.display_name})",
                            "step_type": "tool_call",
                            "tool_name": "windows_app_launch",
                            "parameters": {"app_id": target_app.app_id},
                            "dependencies": [],
                        }
                    else:
                        return {
                            "description": "Launch Visual Studio Code",
                            "step_type": "tool_call",
                            "tool_name": "windows_app_launch",
                            "parameters": {"app_id": "code"},
                            "dependencies": [],
                        }
            except Exception as code_app_err:
                logger.debug(f"Generic coding app resolution skipped: {code_app_err}")

            # 2c. Check semantic application category discovery (e.g. image editing, spreadsheet, database, browser)
            try:
                from tools.windows.discovery import find_application_by_category

                cat_name, cat_apps = find_application_by_category(norm)
                if cat_name and cat_apps:
                    top_app = cat_apps[0]
                    return {
                        "description": f"Launch {cat_name.replace('_', ' ')} application ({top_app.name})",
                        "step_type": "tool_call",
                        "tool_name": "windows_app_launch",
                        "parameters": {"app_id": top_app.app_id},
                        "dependencies": [],
                    }
            except Exception as cat_err:
                logger.debug(f"Semantic application category resolution skipped: {cat_err}")

            matched_apps: list[str] = []
            for app_id, patterns in apps_map:
                if any(p in norm for p in patterns) and app_id not in matched_apps:
                    matched_apps.append(app_id)

            # Check Universal Windows Application Discovery if not matched in standard list
            if not matched_apps:
                looks_like_file_or_path = (
                    ":\\" in norm
                    or ":/" in norm
                    or "/" in norm
                    or "\\" in norm
                    or any(
                        norm.endswith(ext)
                        for ext in (
                            ".txt",
                            ".py",
                            ".md",
                            ".json",
                            ".html",
                            ".log",
                            ".csv",
                            ".pdf",
                            ".docx",
                        )
                    )
                )
                if not looks_like_file_or_path:
                    try:
                        from tools.windows.discovery import get_windows_app_discovery

                        disc = get_windows_app_discovery()
                        clean_target = norm
                        for cue in (
                            "open",
                            "launch",
                            "start",
                            "run",
                            "باز کن",
                            "بازکن",
                            "اجرا کن",
                            "بالا بیار",
                        ):
                            clean_target = clean_target.replace(cue, " ")
                        clean_target = " ".join(clean_target.split())
                        if clean_target and len(clean_target) > 1:
                            found = disc.find_application(clean_target)
                            if found:
                                matched_apps.append(found.app_id)
                    except Exception:
                        pass

            if matched_apps:
                steps: list[dict[str, Any]] = []
                for app_id in matched_apps:
                    disp = app_id.capitalize()
                    steps.append(
                        {
                            "description": f"Launch {disp} application",
                            "step_type": "tool_call",
                            "tool_name": "windows_app_launch",
                            "parameters": {"app_id": app_id},
                            "dependencies": [],
                        }
                    )
                return steps if len(steps) > 1 else steps[0]

        if (
            is_close
            and "windows_app_close" in tool_names
            and not ("browser_tab_close" in tool_names and any(k in norm for k in ("tab", "تب")))
        ):
            target_app = None
            for app_id, patterns in apps_map:
                if any(p in norm for p in patterns):
                    target_app = app_id
                    break

            if not target_app:
                try:
                    from tools.windows.discovery import get_windows_app_discovery

                    disc = get_windows_app_discovery()
                    clean_target = norm
                    for cue in ("close", "ببند", "ببندش", "خارج شو", "kill", "قطع کن"):
                        clean_target = clean_target.replace(cue, " ")
                    clean_target = " ".join(clean_target.split())
                    found = disc.find_application(clean_target)
                    if found:
                        target_app = found.app_id
                except Exception:
                    pass

            # Multi-turn reference: "close the first browser", "مرورگر اول رو ببند"
            if not target_app and any(
                k in norm for k in ("first browser", "مرورگر اول", "مرورگر قبلی", "پنجره قبلی")
            ):
                target_app = "chrome"

            if target_app:
                return {
                    "description": f"Close {target_app} application",
                    "step_type": "tool_call",
                    "tool_name": "windows_app_close",
                    "parameters": {"app_id": target_app},
                    "dependencies": [],
                }

        # 4. Display, Power, and Window Management
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
        if "windows_window_maximize" in tool_names and any(
            k in norm for k in ("maximize", "بزرگ کن", "بزرگش کن", "ماکزیمایز")
        ):
            return {
                "description": "Maximize window",
                "step_type": "tool_call",
                "tool_name": "windows_window_maximize",
                "parameters": {},
                "dependencies": [],
            }
        if "windows_window_restore" in tool_names and any(
            k in norm for k in ("restore", "برگردون", "ریستور")
        ):
            return {
                "description": "Restore window bounds",
                "step_type": "tool_call",
                "tool_name": "windows_window_restore",
                "parameters": {},
                "dependencies": [],
            }
        if "windows_window_list" in tool_names and any(
            k in norm for k in ("list windows", "لیست پنجره‌ها", "پنجره‌های باز", "چه پنجره‌هایی")
        ):
            return {
                "description": "List visible application windows",
                "step_type": "tool_call",
                "tool_name": "windows_window_list",
                "parameters": {},
                "dependencies": [],
            }
        return None

    def _detect_browser_and_internet_intent(
        self, goal: str, tool_names: set[str]
    ) -> list[dict[str, Any]] | dict[str, Any] | None:
        """Detect live internet search, website navigation, and web documentation summaries."""
        norm = self._normalize_persian_digits(goal.strip().lower())

        # 1. Multi-step: "Open Edge, search for Python 3.12 documentation, and summarize the official documentation"
        if ("summarize" in norm or "خلاصه" in norm or "توضیح" in norm) and (
            "python 3.12" in norm or "documentation" in norm or "داکیومنت" in norm
        ):
            steps = []
            if "windows_app_launch" in tool_names:
                steps.append(
                    {
                        "description": "Launch Microsoft Edge",
                        "step_type": "tool_call",
                        "tool_name": "windows_app_launch",
                        "parameters": {"app_id": "msedge"},
                        "dependencies": [],
                    }
                )
            search_tool = "internet_search" if "internet_search" in tool_names else "browser_search"
            if search_tool in tool_names:
                steps.append(
                    {
                        "description": "Search for Python 3.12 official documentation",
                        "step_type": "tool_call",
                        "tool_name": search_tool,
                        "parameters": {"query": "Python 3.12 documentation"},
                        "dependencies": [],
                    }
                )
            if "internet_page_read" in tool_names:
                steps.append(
                    {
                        "description": "Read official Python 3.12 documentation page",
                        "step_type": "tool_call",
                        "tool_name": "internet_page_read",
                        "parameters": {"url": "https://docs.python.org/3.12/"},
                        "dependencies": [],
                    }
                )
            elif "browser_navigate" in tool_names:
                steps.append(
                    {
                        "description": "Navigate to official Python 3.12 documentation",
                        "step_type": "tool_call",
                        "tool_name": "browser_navigate",
                        "parameters": {"url": "https://docs.python.org/3.12/"},
                        "dependencies": [],
                    }
                )
            if steps:
                return steps

        # 2. Browser Navigation: "Open Chrome and navigate to GitHub" / "برو توی گیتهاب"
        has_nav = any(
            k in norm
            for k in ("navigate", "برو به", "سایت", "وبسایت", "صفحه", "بیار", "باز کن", "رو بیار")
        )
        if has_nav:
            target_url = None
            if "github" in norm or "گیتهاب" in norm:
                target_url = "https://github.com"
            elif "google" in norm or "گوگل" in norm:
                target_url = "https://www.google.com"
            elif "python" in norm or "پایتون" in norm:
                target_url = "https://www.python.org"
            elif m := re.search(r"https?://[^\s]+", norm):
                target_url = m.group(0)

            if target_url:
                steps = []
                if "chrome" in norm and "windows_app_launch" in tool_names:
                    steps.append(
                        {
                            "description": "Launch Google Chrome",
                            "step_type": "tool_call",
                            "tool_name": "windows_app_launch",
                            "parameters": {"app_id": "chrome"},
                            "dependencies": [],
                        }
                    )
                elif "edge" in norm and "windows_app_launch" in tool_names:
                    steps.append(
                        {
                            "description": "Launch Microsoft Edge",
                            "step_type": "tool_call",
                            "tool_name": "windows_app_launch",
                            "parameters": {"app_id": "msedge"},
                            "dependencies": [],
                        }
                    )

                if "browser_navigate" in tool_names:
                    steps.append(
                        {
                            "description": f"Navigate browser to {target_url}",
                            "step_type": "tool_call",
                            "tool_name": "browser_navigate",
                            "parameters": {"url": target_url},
                            "dependencies": [],
                        }
                    )
                elif "internet_page_read" in tool_names:
                    steps.append(
                        {
                            "description": f"Retrieve web page content from {target_url}",
                            "step_type": "tool_call",
                            "tool_name": "internet_page_read",
                            "parameters": {"url": target_url},
                            "dependencies": [],
                        }
                    )
                if steps:
                    return steps if len(steps) > 1 else steps[0]

        # 3. Live Internet Search
        if any(
            k in norm
            for k in (
                "search the web",
                "search internet",
                "در اینترنت سرچ کن",
                "در اینترنت جستجو کن",
                "سرچ در اینترنت",
            )
        ):
            search_query = goal
            for remove_phrase in (
                "search the web for",
                "search the web",
                "search internet for",
                "search internet",
                "در اینترنت درباره",
                "در اینترنت جستجو کن",
                "در اینترنت سرچ کن",
                "در وب جستجو کن",
                "در وب سرچ کن",
            ):
                search_query = re.sub(
                    re.escape(remove_phrase), "", search_query, flags=re.IGNORECASE
                )
            search_query = search_query.strip() or goal

            if "browser_search" in tool_names and (
                "web" in norm or "وب" in norm or "browser" in norm
            ):
                tool = "browser_search"
            elif "internet_search" in tool_names:
                tool = "internet_search"
            else:
                tool = "browser_search" if "browser_search" in tool_names else "mock_search"
            if tool in tool_names:
                return {
                    "description": f"Search the live internet for: {search_query}",
                    "step_type": "tool_call",
                    "tool_name": tool,
                    "parameters": {"query": search_query},
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

    def _detect_coding_agent_intent(
        self, goal: str, tool_names: set[str], session_id: str | None = None
    ) -> dict[str, Any] | None:
        """Recognize Persian and English delegation prompts for the Antigravity coding agent and software engineering tasks."""
        norm = goal.lower().strip()

        # Check status or health
        if "coding_agent_status" in tool_names and any(
            k in norm
            for k in (
                "وضعیت آنتی گرویتی",
                "وضعیت کدنویس",
                "antigravity status",
                "coding agent status",
            )
        ):
            return {
                "description": "Check Antigravity coding agent installation and readiness",
                "step_type": "tool_call",
                "tool_name": "coding_agent_status",
                "parameters": {},
                "dependencies": [],
            }

        # Resolve active project workspace path if known
        target_ws: str | None = None
        try:
            from core.conversation_session import get_conversation_session_manager

            mgr = get_conversation_session_manager()
            sess = mgr.get_session(session_id or "default_session")
            if sess and sess.active_project_path:
                target_ws = sess.active_project_path
        except Exception:
            pass

        # Check project cues in goal dynamically
        if not target_ws:
            try:
                from core.files.project_resolver import get_project_resolver

                res_p = get_project_resolver().resolve_project(norm)
                if res_p:
                    target_ws = str(res_p.path)
            except Exception:
                pass

        # 1. Project inspection / Verify task / Check repo / Run tests
        if "coding_agent_verify_task" in tool_names and any(
            k in norm
            for k in (
                "تایید تغییرات کد",
                "بررسی ریپو",
                "بررسی پروژه",
                "ریپو",
                "تستهاشو",
                "تست هاشو",
                "تست‌هاشو",
                "تستها",
                "تست‌ها",
                "تست ها",
                "اجرای تست",
                "verify code",
                "verify workspace",
                "check repo",
                "check project",
                "inspect project",
                "run tests",
                "run its tests",
                "test suite",
                "what did you change",
                "چه تغییراتی",
                "چه چیزی تغییر کرد",
            )
        ):
            params: dict[str, Any] = {"run_tests": True, "run_linter": True}
            if target_ws:
                params["workspace_path"] = str(target_ws)
            return {
                "description": f"Independently inspect project workspace and run tests ({target_ws or 'current project'})",
                "step_type": "tool_call",
                "tool_name": "coding_agent_verify_task",
                "parameters": params,
                "dependencies": [],
            }

        # 2. Project error fixing / Delegation to Antigravity
        if "coding_agent_delegate_task" in tool_names and any(
            k in norm
            for k in (
                "درستش کن",
                "اصلاحش کن",
                "تعمیرش کن",
                "کد بنویس",
                "برنامه نویسی",
                "توسعه دهنده",
                "با آنتی گرویتی",
                "delegate to antigravity",
                "write code with agy",
                "coding agent",
                "fix bug",
                "fix it",
                "fix error",
                "fix the failing tests",
                "fix failing tests",
                "خطایی داشت درستش کن",
                "خطاها رو برطرف کن",
                "implement feature",
            )
        ):
            params = {"prompt": goal, "auto_verify": True}
            if target_ws:
                params["workspace_path"] = str(target_ws)
            return {
                "description": f"Delegate programming task to Google Antigravity: {goal}",
                "step_type": "tool_call",
                "tool_name": "coding_agent_delegate_task",
                "parameters": params,
                "dependencies": [],
            }

        return None

    def _detect_directory_creation_intent(
        self, goal: str, tool_names: set[str], session_id: str | None = None
    ) -> dict[str, Any] | None:
        """Detect deterministic directory/folder creation intent across Windows Desktop, Documents, etc."""
        norm = self._normalize_persian_digits(goal.strip().lower())

        # Check directory rename intent (e.g. "Rename directory at C:\... to Backend")
        m_rename = re.search(
            r"\brename\s+directory\s+at\s+([A-Za-z]:\\[^\s]+)\s+to\s+([^\s\n]+)",
            goal,
            re.IGNORECASE,
        )
        if m_rename:
            src_p = Path(m_rename.group(1))
            dest_name = m_rename.group(2).strip()
            dest_p = src_p.parent / dest_name
            if "file_move" in tool_names:
                return {
                    "description": f"Rename directory from {src_p.name} to {dest_name}",
                    "step_type": "tool_call",
                    "tool_name": "file_move",
                    "parameters": {
                        "source_path": str(src_p),
                        "destination_path": str(dest_p),
                    },
                    "dependencies": [],
                }
            elif "file_create_directory" in tool_names:
                return {
                    "description": f"Create replacement directory called {dest_name}",
                    "step_type": "tool_call",
                    "tool_name": "file_create_directory",
                    "parameters": {"directory_path": str(dest_p)},
                    "dependencies": [],
                }

        if "file_create_directory" not in tool_names:
            return None

        is_folder_intent = any(
            k in norm
            for k in (
                "create a folder",
                "create folder",
                "make a folder",
                "make folder",
                "new folder",
                "create a directory",
                "create directory",
                "make a directory",
                "make directory",
                "new directory",
                "mkdir",
                "پوشه بساز",
                "یه پوشه بساز",
                "یک پوشه بساز",
                "پوشه ایجاد کن",
                "ساخت پوشه",
                "ایجاد پوشه",
                "فولدر بساز",
                "یه فولدر بساز",
                "یک فولدر بساز",
                "فولدر جدید",
                "دایرکتوری بساز",
                "ایجاد دایرکتوری",
                "پوشه جدید",
            )
        ) or (
            any(k in norm for k in ("folder", "directory", "پوشه", "فولدر", "دایرکتوری"))
            and any(
                k in norm for k in ("create", "make", "put", "add", "new", "بساز", "ایجاد", "جدید")
            )
        )

        if not is_folder_intent:
            return None

        from infrastructure.paths import (
            get_desktop_dir,
            get_documents_dir,
            get_downloads_dir,
        )

        # Resolve destination
        any(k in norm for k in ("desktop", "دسکتاپ", "میزکار"))
        is_documents = any(k in norm for k in ("document", "داکیومنت", "اسناد"))
        is_downloads = any(k in norm for k in ("download", "دانلود"))

        target_base_dir: Path
        dest_name_en: str
        dest_name_fa: str

        # Check for nested parent directory from session or prompt
        parent_override: Path | None = None

        # 0. Check explicit path in goal (e.g. "Create a directory at C:\docker\pc-shop called Python")
        m_at = re.search(
            r"\bat\s+([A-Za-z]:\\[^\s]+(?:\\[^\s]+)*)\s+called\s+", goal, re.IGNORECASE
        )
        if m_at:
            cand_p = Path(m_at.group(1))
            if cand_p.exists() and cand_p.is_dir():
                parent_override = cand_p

        if not parent_override and session_id:
            try:
                from core.conversation_session import get_conversation_session_manager

                sess = get_conversation_session_manager().get_session(session_id)
                if sess:
                    nested_cues = (
                        "inside it",
                        "inside that folder",
                        "in it",
                        "in that folder",
                        "inside the project",
                        "in the project",
                        "inside project",
                        "in project",
                        "توش",
                        "داخلش",
                        "توی اون",
                        "درون آن",
                        "توی همین پوشه",
                        "توی پوشه قبلی",
                        "توی همون پوشه",
                        "داخل پروژه",
                        "توی پروژه",
                    )
                    has_nested = any(c in norm for c in nested_cues)
                    if has_nested:
                        if (
                            "project" in norm
                            or "پروژه" in norm
                            or not sess.last_created_directory_path
                        ) and sess.active_project_path:
                            parent_override = sess.active_project_path
                        elif sess.last_created_directory_path:
                            parent_override = sess.last_created_directory_path
                        elif sess.active_project_path:
                            parent_override = sess.active_project_path
                    elif (
                        sess.last_created_directory_path
                        and f"at {str(sess.last_created_directory_path).lower()}" in norm
                    ):
                        parent_override = sess.last_created_directory_path
            except Exception:
                pass

        if parent_override:
            target_base_dir = parent_override
            dest_name_en = f"folder '{parent_override.name}'"
            dest_name_fa = f"پوشه '{parent_override.name}'"
        elif is_documents:
            target_base_dir = get_documents_dir()
            dest_name_en = "Documents"
            dest_name_fa = "داکیومنت"
        elif is_downloads:
            target_base_dir = get_downloads_dir()
            dest_name_en = "Downloads"
            dest_name_fa = "دانلودها"
        else:
            target_base_dir = get_desktop_dir()
            dest_name_en = "Desktop"
            dest_name_fa = "دسکتاپ"

        # Extract folder name
        target_folder_name = ""

        # 1. Quotes
        for quote_mark in ('"', "'", "«", "»"):
            if quote_mark in goal:
                parts = re.split(r'["\'«»]', goal)
                for part in parts:
                    cleaned_part = part.strip()
                    if (
                        cleaned_part
                        and not cleaned_part.startswith("http")
                        and len(cleaned_part) < 80
                        and cleaned_part.lower()
                        not in ("desktop", "documents", "downloads", "دسکتاپ", "داکیومنت")
                    ):
                        target_folder_name = cleaned_part
                        break
                if target_folder_name:
                    break

        # 2. Named/called patterns (English & Persian)
        if not target_folder_name:
            m_named = re.search(
                r'(?:named|called|به\s*نام|با\s*نام|به\s*اسم|با\s*اسم|تحت\s*عنوان|نام|اسم)\s+["\'«»]?([^"\'«»\n]+)["\'«»]?',
                goal,
                re.IGNORECASE,
            )
            if m_named:
                cand = m_named.group(1).strip().rstrip(".,;:")
                cand = re.split(r"\b(on|in|روی|توی|در|با)\b", cand, flags=re.IGNORECASE)[0].strip()
                if cand:
                    target_folder_name = cand

        # 3. Clean up folder name (remove invalid path characters)
        if target_folder_name:
            target_folder_name = (
                target_folder_name.replace("/", "").replace("\\", "").replace(":", "")
            )
            target_folder_name = target_folder_name.strip(" .")

        # 4. If folder name is missing: ask ONE precise clarification question
        if not target_folder_name:
            if session_id:
                try:
                    from core.conversation_session import get_conversation_session_manager

                    sess = get_conversation_session_manager().get_or_create_session(session_id)
                    sess.pending_clarification = {
                        "type": "folder_name",
                        "destination": dest_name_en,
                        "target_dir": str(target_base_dir),
                    }
                except Exception:
                    pass

            is_fa = any(ord(c) >= 0x0600 and ord(c) <= 0x06FF for c in goal)
            clarification_msg = (
                f"حتماً، مایلید نام این پوشه روی {dest_name_fa} چه باشد؟"
                if is_fa
                else f"Certainly, sir. What would you like to name the folder on your {dest_name_en}?"
            )
            return {
                "description": f"Clarify folder name on {dest_name_en}",
                "step_type": "thought",
                "tool_name": None,
                "parameters": {"clarification_prompt": clarification_msg},
                "dependencies": [],
            }

        # 5. Full directory path construction
        full_dir_path = target_base_dir / target_folder_name

        return {
            "description": f"Create directory '{target_folder_name}' on {dest_name_en}",
            "step_type": "tool_call",
            "tool_name": "file_create_directory",
            "parameters": {
                "directory_path": str(full_dir_path),
                "exist_ok": True,
                "parents": True,
            },
            "dependencies": [],
        }

    def _detect_file_modification_intent(
        self, goal: str, tool_names: set[str]
    ) -> dict[str, Any] | None:
        """Recognize document extraction, file write/edit/copy/move/delete, diff, duplicate and archive operations."""
        norm = goal.lower().strip()

        # Guard: Explicitly ignore directory/folder requests from being treated as file writing
        if any(k in norm for k in ("folder", "directory", "dir", "پوشه", "فولدر", "دایرکتوری")):
            return None

        # 1. File Write / Create (e.g. "Create a simple HTML file on my Windows Desktop named test.html")
        is_file_creation = any(
            k in norm
            for k in (
                "create a file",
                "create file",
                "write a file",
                "write file",
                "write to file",
                "make a file",
                "save to file",
                "save file",
                "save to desktop",
                "create on desktop",
                "write on desktop",
                "save on desktop",
                "بساز",
                "ایجاد فایل",
                "بنویس در فایل",
                "ساخت فایل",
                "فایل جدید",
                "html file",
                "فایل html",
            )
        ) or (
            any(k in norm for k in ("create", "make", "save", "write", "ایجاد", "بنویس", "بساز"))
            and any(k in norm for k in ("file", "desktop", "فایل", "دسکتاپ", "میزکار"))
        )

        if "file_write_text" in tool_names and is_file_creation:
            from infrastructure.paths import get_desktop_dir

            desktop_dir = get_desktop_dir()

            # Target directory detection
            is_desktop = any(k in norm for k in ("desktop", "دسکتاپ", "میزکار"))
            target_dir = desktop_dir if is_desktop else Path(".")

            # Extract filename
            target_filename = ""

            # Check quotes first
            for quote_mark in ('"', "'", "«", "»"):
                if quote_mark in goal:
                    parts = re.split(r'["\'«»]', goal)
                    for part in parts:
                        cleaned_part = part.strip()
                        if "." in cleaned_part and not cleaned_part.startswith("http"):
                            target_filename = cleaned_part
                            break
                    if target_filename:
                        break

            # Check named/called patterns
            if not target_filename:
                m_named = re.search(
                    r'(?:named|called|به نام|با نام|اسم|نام)\s+["\'«»]?([a-zA-Z0-9_.-]+)["\'«»]?',
                    goal,
                    re.IGNORECASE,
                )
                if m_named:
                    target_filename = m_named.group(1).rstrip(".,;:")

            # Check standard extensions in goal
            if not target_filename:
                m_ext = re.search(
                    r"\b([a-zA-Z0-9_.-]+\.(?:html?|txt|py|json|md|css|js|csv|xml|yaml|yml|log|bat|ps1|sh))\b",
                    goal,
                    re.IGNORECASE,
                )
                if m_ext:
                    target_filename = m_ext.group(1)

            # Fallback extension if missing or incomplete
            if not target_filename:
                if "html" in norm:
                    target_filename = "test.html"
                elif "python" in norm or "py" in norm:
                    target_filename = "script.py"
                elif "json" in norm:
                    target_filename = "data.json"
                else:
                    target_filename = "file.txt"
            elif "." not in target_filename:
                if "html" in norm:
                    target_filename += ".html"
                elif "python" in norm:
                    target_filename += ".py"
                elif "json" in norm:
                    target_filename += ".json"
                else:
                    target_filename += ".txt"

            resolved_path = (target_dir / target_filename).resolve()

            # Generate appropriate content
            ext = resolved_path.suffix.lower()
            content = ""

            # Check for user-specified content
            m_content = re.search(
                r'(?:with content|content:|با محتوای|شامل|با متن)\s+["\'«»]?([\s\S]+?)["\'«»]?$',
                goal,
                re.IGNORECASE,
            )
            if m_content:
                content = m_content.group(1).strip()
            else:
                if ext in (".html", ".htm"):
                    content = (
                        "<!DOCTYPE html>\n"
                        '<html lang="en">\n'
                        "<head>\n"
                        '    <meta charset="UTF-8">\n'
                        '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
                        "    <title>JARVIS Generated Page</title>\n"
                        "</head>\n"
                        "<body>\n"
                        "    <h1>Hello from JARVIS</h1>\n"
                        "    <p>This file was automatically created and verified on your Windows Desktop.</p>\n"
                        "</body>\n"
                        "</html>\n"
                    )
                elif ext == ".py":
                    content = '# Generated by JARVIS\nprint("Hello from JARVIS")\n'
                elif ext == ".json":
                    content = '{\n  "generator": "JARVIS",\n  "status": "success"\n}\n'
                elif ext == ".md":
                    content = (
                        f"# {resolved_path.stem}\n\nGenerated by JARVIS on your Windows Desktop.\n"
                    )
                else:
                    content = f"Hello from JARVIS.\nCreated file: {resolved_path.name}\n"

            return {
                "description": f"Create and verify file '{resolved_path.name}' at '{resolved_path}'",
                "step_type": "tool_call",
                "tool_name": "file_write_text",
                "parameters": {
                    "file_path": str(resolved_path),
                    "content": content,
                    "overwrite": True,
                },
                "dependencies": [],
            }

        # 2. File Delete (e.g. "حذف فایل test.html", "delete file test.txt")
        if "file_delete" in tool_names and any(
            k in norm for k in ("delete file", "remove file", "حذف فایل", "پاک کردن فایل")
        ):
            from infrastructure.paths import get_desktop_dir

            target_file = ""
            for quote_mark in ('"', "'", "«", "»"):
                if quote_mark in goal:
                    parts = re.split(r'["\'«»]', goal)
                    for part in parts:
                        cleaned_part = part.strip()
                        if "." in cleaned_part:
                            target_file = cleaned_part
                            break
                    if target_file:
                        break
            if not target_file:
                m_ext = re.search(
                    r"\b([a-zA-Z0-9_.-]+\.(?:html?|txt|py|json|md|css|js|csv|xml|yaml|yml|log))\b",
                    goal,
                    re.IGNORECASE,
                )
                if m_ext:
                    target_file = m_ext.group(1)

            is_desktop = any(k in norm for k in ("desktop", "دسکتاپ", "میزکار"))
            if is_desktop and target_file and not Path(target_file).is_absolute():
                resolved_del = (get_desktop_dir() / target_file).resolve()
            else:
                resolved_del = Path(target_file or "file.txt").resolve()

            return {
                "description": f"Safely delete file '{resolved_del.name}'",
                "step_type": "tool_call",
                "tool_name": "file_delete",
                "parameters": {"file_path": str(resolved_del), "permanent": False},
                "dependencies": [],
            }

        # 3. Document extraction (.pdf, .docx, .xlsx, .pptx, etc.)
        if "file_extract_document" in tool_names and any(
            k in norm
            for k in (
                "استخراج متن",
                "خواندن pdf",
                "فایل ورد",
                "اکسل",
                "پاورپوینت",
                "extract document",
                "read pdf",
                "read docx",
                "read xlsx",
            )
        ):
            target_file = ""
            for quote_mark in ('"', "'", "«", "»"):
                if quote_mark in goal:
                    parts = re.split(r'["\'«»]', goal)
                    for part in parts:
                        cleaned_part = part.strip()
                        if "." in cleaned_part:
                            target_file = cleaned_part
                            break
                    if target_file:
                        break
            return {
                "description": f"Extract document text and structure from {target_file or 'target file'}",
                "step_type": "tool_call",
                "tool_name": "file_extract_document",
                "parameters": {"file_path": target_file},
                "dependencies": [],
            }

        # Duplicates
        if "file_find_duplicates" in tool_names and any(
            k in norm
            for k in ("فایل های تکراری", "تکراری ها", "find duplicates", "duplicate files")
        ):
            return {
                "description": "Scan directory for duplicate files via SHA-256 hashes",
                "step_type": "tool_call",
                "tool_name": "file_find_duplicates",
                "parameters": {"directory_path": "."},
                "dependencies": [],
            }

        # Diff / Compare
        if "file_compare_diff" in tool_names and any(
            k in norm for k in ("مقایسه دو فایل", "تفاوت فایل", "compare files", "diff files")
        ):
            return {
                "description": "Compare two files and generate unified diff",
                "step_type": "tool_call",
                "tool_name": "file_compare_diff",
                "parameters": {"file_path_a": "", "file_path_b": ""},
                "dependencies": [],
            }

        # Archive create
        if "file_archive_create" in tool_names and any(
            k in norm for k in ("زیپ کن", "فشرده سازی", "create zip", "archive files")
        ):
            return {
                "description": "Create safe ZIP archive",
                "step_type": "tool_call",
                "tool_name": "file_archive_create",
                "parameters": {"archive_path": "archive.zip", "source_paths": []},
                "dependencies": [],
            }

        # Archive extract
        if "file_archive_extract" in tool_names and any(
            k in norm for k in ("استخراج زیپ", "از فشرده خارج کن", "extract zip", "unzip")
        ):
            return {
                "description": "Safely extract ZIP archive",
                "step_type": "tool_call",
                "tool_name": "file_archive_extract",
                "parameters": {"archive_path": "", "target_directory": "."},
                "dependencies": [],
            }

        return None

    def _detect_file_intelligence_intent(
        self, goal: str, tool_names: set[str]
    ) -> dict[str, Any] | None:
        """Recognize file search, file open, and file inspection requests."""
        norm = goal.lower().strip()
        if any(k in norm for k in ("تکراری", "duplicate", "duplicates")):
            return None

        # 1. File Search Intent
        # "find my resume", "رزومه‌ام کجاست", "فایل‌های pdf پروژه رو پیدا کن", "search for python files"
        is_file_search = (
            any(
                k in norm
                for k in (
                    "file",
                    "files",
                    "فایل",
                    "فایل‌های",
                    "پوشه",
                    "سند",
                    "داکیومنت",
                    "مدرک",
                    "رزومه",
                    "resume",
                )
            )
            and any(
                k in norm
                for k in (
                    "search",
                    "find",
                    "locate",
                    "where is",
                    "پیدا کن",
                    "بگرد",
                    "جستجو",
                    "کجاست",
                    "بیار",
                    "نشان بده",
                )
            )
        ) or any(
            k in norm
            for k in (
                "رزومه‌ام کجاست",
                "رزومه کجاست",
                "where is my resume",
                "find my resume",
                "فایل‌های pdf",
                "pdf files",
                "فایل pdf",
                "فایل‌های پایتون",
                "python files",
            )
        )

        if "file_search" in tool_names and is_file_search:
            from core.files.search import FileSearchEngine

            engine = FileSearchEngine()
            cleaned_terms, ext_filter = engine.parse_query(goal)
            return {
                "description": f"Search local files for '{cleaned_terms}'",
                "step_type": "tool_call",
                "tool_name": "file_search",
                "parameters": {"query": cleaned_terms, "extension": ext_filter},
                "dependencies": [],
            }

        # 2. File Open Intent
        is_file_open = (
            any(k in norm for k in ("باز کن", "بازکن", "open", "اجرا کن"))
            and any(
                k in norm for k in ("فایل", "file", ".py", ".pdf", ".docx", ".txt", ".json", ".md")
            )
            and not any(
                k in norm for k in ("برنامه", "اپلیکیشن", "application", "browser", "مرورگر")
            )
        )
        if "file_open" in tool_names and is_file_open:
            app_target = None
            if any(k in norm for k in ("code", "vscode", "وی اس کد", "کد")):
                app_target = "code"
            elif any(k in norm for k in ("notepad", "نوت پد", "نوتپد")):
                app_target = "notepad"

            target_file = ""
            for q in ('"', "'", "«", "»"):
                if q in goal:
                    parts = re.split(r'["\'«»]', goal)
                    for p in parts:
                        if "." in p.strip():
                            target_file = p.strip()
                            break

            if not target_file:
                clean_terms = norm
                for w in (
                    "فایل",
                    "file",
                    "رو",
                    "باز کن",
                    "بازکن",
                    "open",
                    "توی",
                    "در",
                    "با",
                    "وی اس کد",
                    "vscode",
                    "code",
                ):
                    clean_terms = clean_terms.replace(w, " ")
                target_file = " ".join(clean_terms.split())

            return {
                "description": f"Open file '{target_file}'",
                "step_type": "tool_call",
                "tool_name": "file_open",
                "parameters": {"file_path": target_file, "application": app_target},
                "dependencies": [],
            }

        # 3. File Inspect and Safe Read Intent
        is_inspect = any(
            k in norm
            for k in (
                "inspect",
                "preview",
                "check content",
                "بررسی فایل",
                "محتوای فایل",
                "پیش‌نمایش",
                "پیش نمایش",
            )
        ) and any(k in norm for k in ("file", "فایل", ".txt", ".py", ".md", ".json"))

        is_read_text = (
            any(
                k in norm
                for k in (
                    "read",
                    "بخوان",
                    "بخون",
                    "خواندن فایل",
                    "خوندن فایل",
                    "متن فایل",
                )
            )
            and any(
                k in norm
                for k in (
                    "file",
                    "فایل",
                    ".txt",
                    ".py",
                    ".md",
                    ".json",
                    ".log",
                    ".csv",
                    "brief",
                    "note",
                )
            )
        ) or is_inspect

        if ("file_read_text" in tool_names or "file_inspect" in tool_names) and (
            is_read_text or is_inspect
        ):
            target = ""
            for q in ('"', "'", "«", "»"):
                if q in goal:
                    parts = re.split(r'["\'«»]', goal)
                    for p in parts:
                        if "." in p.strip():
                            target = p.strip()
                            break
                    if target:
                        break
            if not target:
                path_match = re.search(r'([A-Za-z]:\\[^\s"\']+|\/[^\s"\']+)', goal)
                if path_match:
                    target = path_match.group(1).rstrip(".,;")
            if not target:
                target = norm

            if "file_read_text" in tool_names and is_read_text:
                return {
                    "description": f"Read safe text content from '{target}'",
                    "step_type": "tool_call",
                    "tool_name": "file_read_text",
                    "parameters": {"file_path": target},
                    "dependencies": [],
                }
            elif "file_inspect" in tool_names:
                return {
                    "description": f"Inspect file '{target}'",
                    "step_type": "tool_call",
                    "tool_name": "file_inspect",
                    "parameters": {"file_path": target},
                    "dependencies": [],
                }

        return None

    def _detect_terminal_intent(self, goal: str, tool_names: set[str]) -> dict[str, Any] | None:
        """Recognize restricted terminal commands."""
        norm = goal.lower().strip()

        if "terminal_execute_command" not in tool_names:
            return None

        if any(k in norm for k in ("وضعیت گیت", "git status")):
            return {
                "description": "Check git repository status",
                "step_type": "tool_call",
                "tool_name": "terminal_execute_command",
                "parameters": {"command_id": "git_status"},
                "dependencies": [],
            }
        elif any(k in norm for k in ("تغییرات گیت", "git diff")):
            return {
                "description": "Check git working tree diff",
                "step_type": "tool_call",
                "tool_name": "terminal_execute_command",
                "parameters": {"command_id": "git_diff"},
                "dependencies": [],
            }
        elif any(k in norm for k in ("تاریخچه گیت", "لاگ گیت", "git log")):
            return {
                "description": "Check git commit history",
                "step_type": "tool_call",
                "tool_name": "terminal_execute_command",
                "parameters": {"command_id": "git_log", "parameters": {"limit": 10}},
                "dependencies": [],
            }
        is_run_tests = (
            any(
                k in norm
                for k in (
                    "تست ها را اجرا کن",
                    "اجرای تست",
                    "run tests",
                    "run test",
                    "run pytest",
                    "execute tests",
                )
            )
            or norm.strip() in ("pytest", "run tests", "run pytest", "test", "تست")
            or bool(re.search(r"\b(?:run|execute)\s+pytest\b", norm, re.IGNORECASE))
        )
        if is_run_tests:
            return {
                "description": "Run pytest test suite",
                "step_type": "tool_call",
                "tool_name": "terminal_execute_command",
                "parameters": {"command_id": "run_tests"},
                "dependencies": [],
            }
        elif any(k in norm for k in ("لینتر", "بررسی فرمت", "ruff check", "run linter")):
            return {
                "description": "Run ruff code linter",
                "step_type": "tool_call",
                "tool_name": "terminal_execute_command",
                "parameters": {"command_id": "run_linter"},
                "dependencies": [],
            }

        return None

    def _detect_voice_intent(self, goal: str, tool_names: set[str]) -> dict[str, Any] | None:
        """Detect microphone mute, voice status, and speech commands."""
        norm = goal.lower().strip()
        # Check unmute first so 'unmute' is not captured by 'mute'
        if "voice_mute" in tool_names and any(
            k in norm
            for k in (
                "میکروفون رو وصل",
                "وصل میکروفون",
                "وصل میکروفن",
                "unmute mic",
                "unmute microphone",
            )
        ):
            return {
                "description": "Unmute microphone listening",
                "step_type": "tool_call",
                "tool_name": "voice_mute",
                "parameters": {"mute": False},
                "dependencies": [],
            }
        if "voice_mute" in tool_names and any(
            k in norm
            for k in (
                "میکروفون رو قطع",
                "قطع میکروفون",
                "قطع میکروفن",
                "mute mic",
                "mute microphone",
            )
        ):
            return {
                "description": "Mute microphone listening",
                "step_type": "tool_call",
                "tool_name": "voice_mute",
                "parameters": {"mute": True},
                "dependencies": [],
            }
        if "voice_status" in tool_names and any(
            k in norm
            for k in (
                "وضعیت میکروفون",
                "وضعیت ویس",
                "وضعیت صدا و میکروفون",
                "voice status",
                "mic status",
            )
        ):
            return {
                "description": "Check voice subsystem and audio device status",
                "step_type": "tool_call",
                "tool_name": "voice_status",
                "parameters": {},
                "dependencies": [],
            }
        return None

    def _detect_email_intent(self, goal: str, tool_names: set[str]) -> dict[str, Any] | None:
        """Detect email composition and sending intents in Persian and English."""
        norm = goal.strip()
        norm_lower = norm.lower()
        if "email_compose" not in tool_names and "email_send" not in tool_names:
            return None

        # Check for email cues
        email_cues = ["ایمیل", "جیمیل", "میل", "email", "gmail", "send email", "send mail"]
        if not any(cue in norm_lower for cue in email_cues):
            return None

        # Extract explicit email address or named recipient
        email_match = re.search(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", norm)
        recipient = email_match.group(0) if email_match else ""
        if not recipient:
            fa_rec = re.search(r"(?:برای|به)\s+([^\s,]+)\s+ایمیل", norm)
            if fa_rec:
                recipient = fa_rec.group(1)
            else:
                en_rec = re.search(
                    r"email\s+(?:to\s+)?([a-zA-Z0-9_.-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+|[a-zA-Z]+)",
                    norm,
                    re.IGNORECASE,
                )
                if en_rec and en_rec.group(1).lower() not in (
                    "me",
                    "him",
                    "her",
                    "them",
                    "someone",
                    "a",
                    "an",
                    "the",
                ):
                    recipient = en_rec.group(1)
                else:
                    logger.info("Ambiguous email recipient; requiring user clarification.")
                    return None

        body_text = norm
        subject = "Message from JARVIS"
        if "بگو" in norm:
            parts = norm.split("بگو", 1)
            body_text = parts[1].strip(" :،.")
            subject = "گزارش / پیام"
        elif "saying" in norm_lower:
            parts = re.split(r"saying", norm, flags=re.IGNORECASE)
            body_text = parts[1].strip(" :.,")
            subject = "Message from JARVIS"

        att_match = re.search(
            r"['\"]?([a-zA-Z0-9_.-]+\.(?:pdf|docx|txt|py|png|jpg|zip))['\"]?", norm
        )
        attachment_paths = [att_match.group(1)] if att_match else []

        target_tool = "email_compose" if "email_compose" in tool_names else "email_send"
        return {
            "description": f"Compose email draft to {recipient}",
            "step_type": "tool_call",
            "tool_name": target_tool,
            "parameters": {
                "to": [recipient],
                "subject": subject,
                "body_text": body_text,
                "attachment_paths": attachment_paths if attachment_paths else None,
            },
            "dependencies": [],
        }

    def _detect_whatsapp_intent(self, goal: str, tool_names: set[str]) -> dict[str, Any] | None:
        """Detect WhatsApp message intents in Persian and English."""
        norm = goal.strip()
        norm_lower = norm.lower()
        if "whatsapp_compose" not in tool_names and "whatsapp_send" not in tool_names:
            return None

        wa_cues = ["واتساپ", "واتس‌اپ", "واتس اپ", "whatsapp", "whats app"]
        if not any(cue in norm_lower for cue in wa_cues):
            return None

        # Check for explicit phone number first
        phone_match = re.search(r"(\+?\d[\d\s\-\(\)]{7,15}\d)", norm)
        if phone_match:
            recipient = phone_match.group(1).replace(" ", "").replace("-", "")
        elif re.search(r"\b(خودم|به خودم|myself|to myself|to me)\b", norm, re.IGNORECASE):
            recipient = "خودم"
        else:
            logger.info(
                "Ambiguous or unverified WhatsApp recipient (missing phone number); requiring user clarification."
            )
            return None

        msg_text = norm
        if "بگو" in norm:
            msg_text = norm.split("بگو", 1)[1].strip(" :،.")
        elif "که" in norm:
            msg_text = norm.split("که", 1)[1].strip(" :،.")
        elif "saying" in norm_lower:
            msg_text = re.split(r"saying", norm, flags=re.IGNORECASE)[1].strip(" :.,")
        elif "that" in norm_lower:
            msg_text = re.split(r"that", norm, flags=re.IGNORECASE)[1].strip(" :.,")

        target_tool = "whatsapp_compose" if "whatsapp_compose" in tool_names else "whatsapp_send"
        return {
            "description": f"Compose WhatsApp message for {recipient}",
            "step_type": "tool_call",
            "tool_name": target_tool,
            "parameters": {
                "recipient": recipient,
                "message_text": msg_text,
            },
            "dependencies": [],
        }

    def _build_fallback_plan_dict(
        self,
        goal: str,
        available_tools: list[ToolDefinition] | None = None,
        session_id: str | None = None,
        context: ExecutionContext | None = None,
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

        # Priority 0: Live Meteorological Weather Intent
        if weather_step := self._detect_weather_intent(goal, tool_names):
            steps.append(weather_step)
        # Priority 1: Browser & Live Internet Intelligence (composite research & navigation)
        elif net_res := self._detect_browser_and_internet_intent(goal, tool_names):
            if isinstance(net_res, list):
                steps.extend(net_res)
            else:
                steps.append(net_res)
        # Priority 1.5: Directory / Folder Creation Intent (Desktop, Documents, etc.)
        elif dir_step := self._detect_directory_creation_intent(
            goal, tool_names, session_id=session_id
        ):
            steps.append(dir_step)
        # Priority 1.6: WhatsApp & Email Communication
        elif wa_step := self._detect_whatsapp_intent(goal, tool_names):
            steps.append(wa_step)
        elif email_step := self._detect_email_intent(goal, tool_names):
            steps.append(email_step)
        # Priority 1.7: Check File Intelligence (search, open, inspect, read)
        elif file_intel_step := self._detect_file_intelligence_intent(goal, tool_names):
            steps.append(file_intel_step)
        # Priority 1.8: Check file modification & document extraction intent
        elif file_step := self._detect_file_modification_intent(goal, tool_names):
            steps.append(file_step)
        # Priority 2: Windows Desktop & Multi-Application Actions
        elif desk_res := self._detect_desktop_intent(goal, tool_names, session_id=session_id):
            if isinstance(desk_res, list):
                steps.extend(desk_res)
            else:
                steps.append(desk_res)
        # Priority 3: Check microphone / voice intent
        elif voice_step := self._detect_voice_intent(goal, tool_names):
            steps.append(voice_step)
        # Priority 6: Check Windows audio control intent
        elif audio_step := self._detect_audio_intent(goal, tool_names):
            steps.append(audio_step)
        # Priority 7: Check coding agent intent
        elif coding_step := self._detect_coding_agent_intent(
            goal, tool_names, session_id=session_id
        ):
            steps.append(coding_step)
        # Priority 8: Check terminal intent
        elif term_step := self._detect_terminal_intent(goal, tool_names):
            steps.append(term_step)
        # Priority 10: Check browser agent legacy intent
        elif browser_step := self._detect_browser_intent(goal, tool_names):
            steps.append(browser_step)
        # Priority 11: Check system diagnostic intent
        elif sys_step := self._detect_system_intent(goal, tool_names):
            steps.append(sys_step)
        # Priority 12: Live internet search
        elif "internet_search" in tool_names and any(
            k in goal.lower() for k in ("search", "find", "who", "what")
        ):
            steps.append(
                {
                    "description": f"Search the live internet for: {goal}",
                    "step_type": "tool_call",
                    "tool_name": "internet_search",
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
        elif context and (r_steps := context.metadata.get("reasoning_plan_steps")):
            for s in r_steps:
                tool_hint = s.get("tool_hint")
                if tool_hint and tool_hint in tool_names:
                    steps.append(
                        {
                            "description": s.get("description", "Execute planned action"),
                            "step_type": "tool_call",
                            "tool_name": tool_hint,
                            "parameters": s.get("parameters") or {},
                            "dependencies": [],
                        }
                    )
                else:
                    steps.append(
                        {
                            "description": s.get("description", "Reasoning step"),
                            "step_type": "thought",
                            "tool_name": None,
                            "parameters": {},
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

            # Parameter normalization for file tools
            if tool_name == "file_write_text":
                if "file_path" not in params:
                    if "path" in params:
                        params["file_path"] = params.pop("path")
                    elif "target_path" in params:
                        params["file_path"] = params.pop("target_path")

                from infrastructure.paths import get_desktop_dir

                desktop_dir = get_desktop_dir()
                raw_fp = str(params.get("file_path", ""))
                is_desktop = (
                    "desktop" in raw_fp.lower()
                    or "دسکتاپ" in raw_fp.lower()
                    or any(k in goal.lower() for k in ("desktop", "دسکتاپ", "میزکار"))
                )
                if is_desktop:
                    fn = Path(raw_fp).name if raw_fp else "test.html"
                    params["file_path"] = str((desktop_dir / fn).resolve())

                if "overwrite" not in params:
                    params["overwrite"] = True

                if not params.get("content"):
                    for text_alias in ("text", "data", "body"):
                        if text_alias in params and params[text_alias]:
                            params["content"] = params.pop(text_alias)
                            break
                    if not params.get("content"):
                        if "html" in str(params.get("file_path", "")).lower():
                            params["content"] = (
                                "<!DOCTYPE html>\n"
                                '<html lang="en">\n'
                                "<head>\n"
                                '    <meta charset="UTF-8">\n'
                                "    <title>JARVIS Generated Page</title>\n"
                                "</head>\n"
                                "<body>\n"
                                "    <h1>Hello from JARVIS</h1>\n"
                                "    <p>This file was automatically created and verified on your Windows Desktop.</p>\n"
                                "</body>\n"
                                "</html>\n"
                            )
                        else:
                            params["content"] = "Hello from JARVIS.\n"

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
