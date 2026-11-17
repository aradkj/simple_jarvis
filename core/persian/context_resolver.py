"""Context Resolver & Reference Resolution Engine for Persian conversational intelligence.

Resolves anaphora (صداش, همون, اون یکی), active project/file bindings,
user corrections, and negative constraints across multi-turn dialogues.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from core.persian.models import PersianEntity, PersianEntityType, PersianIntentType
from infrastructure.logging import get_logger

logger = get_logger("persian.context_resolver")


class ConversationTurn(BaseModel):
    """Represents a single conversational turn stored in context history."""

    turn_index: int
    user_raw_text: str
    normalized_text: str
    intent: PersianIntentType
    entities: list[PersianEntity] = Field(default_factory=list)
    active_project: str | None = None
    active_file: str | None = None
    read_only: bool = False
    prohibitions: list[str] = Field(default_factory=list)
    response_language: str = "en"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReferenceResolutionEngine:
    """Resolves anaphoric expressions and references back to previous entities."""

    # Pronoun & deictic patterns in Persian
    ANAPHORA_PATTERNS = [
        (
            re.compile(
                r"\b(همون|همان)\s+(فایل|پروژه|دستور|اسکریپت|تابع|متد|خطا|باگ)\b", re.IGNORECASE
            ),
            "the_same",
        ),
        (
            re.compile(r"\b(اون|آن|این)\s+(یکی|دیگه|دومی|اولیه|قبلی)\b", re.IGNORECASE),
            "alternative",
        ),
        (
            re.compile(r"\b(روش|راه|گزینه|آپشن|راهکار)\s+(دوم|اول|سوم|بعدی|قبلی)\b", re.IGNORECASE),
            "referenced_option",
        ),
        (
            re.compile(
                r"\b(همون|همان)\s+(چیزی|موضوعی|بحثی|کاری)\s+که\s+(قبلتر|قبلاً|قبلا)\s+گفتیم\b",
                re.IGNORECASE,
            ),
            "resume_previous_topic",
        ),
        (re.compile(r"\b(توش|توی\s+اون|داخلش|داخل\s+آن)\b", re.IGNORECASE), "inside_target"),
        (re.compile(r"\b(روش|روی\s+اون|روی\s+آن)\b", re.IGNORECASE), "on_target"),
        (re.compile(r"\b(صداش|ولومش|صدای\s+اون)\b", re.IGNORECASE), "voice_volume"),
        (re.compile(r"\b(اون|آن|این)\s+(?:رو|را)\b", re.IGNORECASE), "the_same"),
        (re.compile(r"\b(اون|آن)\b", re.IGNORECASE), "the_same"),
        (re.compile(r"\b(تست‌هاش|تست هاش|تستاش)\b", re.IGNORECASE), "target_tests"),
        (re.compile(r"\b(لاگ‌هاش|لاگ هاش|لاگاش)\b", re.IGNORECASE), "target_logs"),
        (re.compile(r"\b(کدش|سورسش)\b", re.IGNORECASE), "target_code"),
        (re.compile(r"\b(نتیجه‌اش|نتیجش|خروجیش)\b", re.IGNORECASE), "target_output"),
    ]

    CORRECTION_PATTERNS = [
        re.compile(r"نه\s*،?\s*منظورم\s+(.+?)\s+بود(?:\s*،?\s*نه\s+(.+))?", re.IGNORECASE),
        re.compile(r"نه\s*،?\s*(?:اشتباه\s+شد|اشتباهه)\s*،?\s*(.+)", re.IGNORECASE),
        re.compile(r"نه\s+اون\s*(?:فایل|پروژه|برنامه)?\s*نه\s*،?\s*(.+)", re.IGNORECASE),
        re.compile(
            r"(?:نه\s*،?\s*)?منظورم\s+(.+?)\s+نیست\s*،?\s*(.+?)\s+(?:رو|را)\s+میگم", re.IGNORECASE
        ),
    ]

    def resolve(
        self,
        current_text: str,
        entities: list[PersianEntity],
        history: list[ConversationTurn],
        fallback_project: str | None = None,
        fallback_file: str | None = None,
    ) -> tuple[dict[str, str], list[str], str | None, str | None]:
        """Resolve references in current turn using dialogue history.

        Returns:
            resolved_references: Dict of ref-name to resolved value
            unresolved_references: List of references that could not be resolved
            active_project: Resolved active project name
            active_file: Resolved active file path/name
        """
        resolved: dict[str, str] = {}
        unresolved: list[str] = []

        active_project: str | None = None
        active_file: str | None = None

        # 1. Determine active project & file from current entities first
        project_map = {
            "جارویس": "jarvis",
            "پیسیشاپ": "pc shop",
            "پی‌سی‌شاپ": "pc shop",
            "pc-shop": "pc shop",
            "pc shop": "pc shop",
        }
        for ent in entities:
            if ent.entity_type in (PersianEntityType.PROJECT, PersianEntityType.PROJECT_NAME):
                raw_val = str(ent.normalized_value).lower()
                active_project = project_map.get(raw_val, raw_val)
            elif ent.entity_type in (
                PersianEntityType.FILE,
                PersianEntityType.FILE_PATH,
                PersianEntityType.FILE_NAME,
            ):
                active_file = str(ent.normalized_value)

        # 2. If not in current turn, inherit from recent history
        if not active_project:
            for turn in reversed(history):
                if turn.active_project:
                    active_project = turn.active_project
                    resolved["inherited_project"] = turn.active_project
                    break

        if not active_file:
            for turn in reversed(history):
                if turn.active_file:
                    active_file = turn.active_file
                    resolved["inherited_file"] = turn.active_file
                    break

        if not active_project and fallback_project:
            active_project = fallback_project
            resolved["inherited_project"] = fallback_project

        if not active_file and fallback_file:
            active_file = fallback_file
            resolved["inherited_file"] = fallback_file

        # 3. Check anaphora patterns
        for pattern, ref_type in self.ANAPHORA_PATTERNS:
            match = pattern.search(current_text)
            if not match:
                continue

            ref_phrase = match.group(0)
            if ref_type == "voice_volume":
                resolved[ref_phrase] = "voice_system"
            elif ref_type in (
                "the_same",
                "inside_target",
                "on_target",
                "target_code",
                "target_output",
            ):
                if active_file:
                    resolved[ref_phrase] = active_file
                elif active_project:
                    resolved[ref_phrase] = active_project
                else:
                    unresolved.append(ref_phrase)
            elif ref_type in ("target_tests", "target_logs"):
                if active_project:
                    resolved[ref_phrase] = f"{active_project}:{ref_type}"
                elif active_file:
                    resolved[ref_phrase] = f"{active_file}:{ref_type}"
                else:
                    unresolved.append(ref_phrase)
            elif ref_type == "alternative":
                # User wants the other option / alternative
                resolved[ref_phrase] = "alternative_target"
            elif ref_type == "referenced_option":
                resolved[ref_phrase] = "referenced_option_target"
            elif ref_type == "resume_previous_topic":
                resolved[ref_phrase] = "previous_topic_resumed"

        # 4. Check user corrections
        for corr_pat in self.CORRECTION_PATTERNS:
            corr_match = corr_pat.search(current_text)
            if corr_match:
                groups = [g.strip() for g in corr_match.groups() if g]
                if groups:
                    resolved["correction_target"] = groups[0]
                    if len(groups) > 1:
                        resolved["correction_rejected"] = groups[1]

        return resolved, unresolved, active_project, active_file


class ConversationContextResolver:
    """Manages multi-turn conversation context, state tracking, and constraints."""

    # Prohibitions & negative constraints in Persian
    PROHIBITION_PATTERNS = [
        (re.compile(r"\b(فعلاً|فعلا)\s+کاری\s+نکن\b", re.IGNORECASE), "no_action"),
        (
            re.compile(r"\bفقط\s+(بررسی|چک|نگاه|آنالیز|بخون|ببین)\s*(کن|بکن)?\b", re.IGNORECASE),
            "read_only",
        ),
        (
            re.compile(
                r"\b(دست\s*نزن|تغییری\s+نده|تغییر\s+نده|ویرایش\s+نکن|عوض\s+نکن)\b", re.IGNORECASE
            ),
            "no_modify",
        ),
        (re.compile(r"\b(پاک\s+نکن|حذف\s+نکن|دیلیت\s+نکن)\b", re.IGNORECASE), "no_delete"),
        (
            re.compile(r"\bدست\s+به\s+(دیتابیس|دیتابیسش|دیتا|پایگاه داده)\s+نزن\b", re.IGNORECASE),
            "protect_db",
        ),
        (
            re.compile(
                r"\bبدون\s+(اجازه|تایید|هماهنگی)\s+(کاری\s+نکن|پاک\s+نکن|تغییر\s+نده)\b",
                re.IGNORECASE,
            ),
            "require_confirmation",
        ),
        (re.compile(r"\bکامیت\s+نکن\b", re.IGNORECASE), "no_git_commit"),
        (
            re.compile(
                r"\b(کیفیت|دقت|سرعت)\s+(?:درکش\s+)?(پایین\s+نیاد|افت\s+نکنه|کم\s+نشه|بدتر\s+نشه)\b",
                re.IGNORECASE,
            ),
            "maintain_quality",
        ),
        (
            re.compile(
                r"\bفقط\s+(بخش|قسمت|پروژه)\s+(.+?)\s+(?:رو|را)\s+(تغییر\s+بده|عوض\s+کن|دستکاری\s+کن)\b",
                re.IGNORECASE,
            ),
            "scope_restriction",
        ),
        (
            re.compile(
                r"\b(?:فعلاً|فعلا)?\s*(?:بیخیال\s+شو|صرف\s*نظر\s+کن|ولش\s+کن|بریم\s+سراغ\s+یه\s+چیز\s+دیگه)\b",
                re.IGNORECASE,
            ),
            "pivot_topic",
        ),
    ]

    def __init__(self, max_history: int = 15) -> None:
        self.max_history = max_history
        self.history: list[ConversationTurn] = []
        self.reference_engine = ReferenceResolutionEngine()
        self.active_project: str | None = None
        self.active_file: str | None = None
        self.current_read_only: bool = False
        self.active_prohibitions: set[str] = set()

    def resolve_turn(
        self,
        raw_text: str,
        normalized_text: str,
        intent: PersianIntentType,
        entities: list[PersianEntity],
    ) -> tuple[dict[str, str], list[str], list[str], bool]:
        """Process turn context, resolve references, and extract operational constraints.

        Returns:
            resolved_refs: Dict mapping reference tokens to target entities/values
            unresolved_refs: References that could not be safely resolved
            prohibitions: Operational constraints active for this turn
            read_only: Whether the operation must be restricted to inspection only
        """
        # 1. Resolve references
        resolved_refs, unresolved_refs, active_proj, active_file = self.reference_engine.resolve(
            normalized_text,
            entities,
            self.history,
            fallback_project=self.active_project,
            fallback_file=self.active_file,
        )

        if active_proj:
            self.active_project = active_proj
        if active_file:
            self.active_file = active_file

        # 2. Extract constraints and prohibitions
        turn_prohibitions: set[str] = set()
        read_only = False

        for pattern, constraint_tag in self.PROHIBITION_PATTERNS:
            if pattern.search(normalized_text):
                turn_prohibitions.add(constraint_tag)
                if constraint_tag in ("read_only", "no_action", "no_modify"):
                    read_only = True

        # Cumulative prohibition state
        if read_only:
            self.current_read_only = True
        elif (
            intent in (PersianIntentType.CODE_EXECUTION, PersianIntentType.FILE_OPERATION)
            and "read_only" not in turn_prohibitions
        ):
            self.current_read_only = False

        all_prohibitions = sorted(self.active_prohibitions.union(turn_prohibitions))

        return resolved_refs, unresolved_refs, all_prohibitions, self.current_read_only

    def record_turn(
        self,
        user_raw_text: str,
        normalized_text: str,
        intent: PersianIntentType,
        entities: list[PersianEntity],
        response_language: str = "en",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store the completed turn in context history."""
        turn = ConversationTurn(
            turn_index=len(self.history) + 1,
            user_raw_text=user_raw_text,
            normalized_text=normalized_text,
            intent=intent,
            entities=entities,
            active_project=self.active_project,
            active_file=self.active_file,
            read_only=self.current_read_only,
            prohibitions=sorted(self.active_prohibitions),
            response_language=response_language,
            metadata=metadata or {},
        )
        self.history.append(turn)
        if len(self.history) > self.max_history:
            self.history.pop(0)

    def reset(self) -> None:
        """Reset conversation context history and state."""
        self.history.clear()
        self.active_project = None
        self.active_file = None
        self.current_read_only = False
        self.active_prohibitions.clear()
