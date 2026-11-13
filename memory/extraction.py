"""Consent-controlled candidate extraction and explicit memory command parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from infrastructure.logging import get_logger
from memory.models import MemoryCategory, MemoryRecord, MemoryStatus
from memory.privacy import MemoryPrivacyManager, SensitiveDataFilter

logger = get_logger("memory.extraction")


@dataclass
class ExtractionResult:
    """Outcome of parsing user input for memory candidates or commands."""

    candidates: list[MemoryRecord]
    forget_requests: list[str]
    is_explicit_command: bool = False


class MemoryExtractor:
    """Extracts memory candidates from user input while enforcing explicit consent and safety."""

    # Explicit memory capture triggers (English and Persian)
    _EXPLICIT_REMEMBER_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(
            r"^\s*(?:please\s+)?remember\s+(?:that\s+|this\s*:\s*|this\s+)?(.+)", re.IGNORECASE
        ),
        re.compile(
            r"^\s*(?:save\s+(?:this\s+)?preference\s*:\s*|save\s+to\s+memory\s*:\s*)(.+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:do\s+not\s+forget\s+(?:that\s+)?|don't\s+forget\s+(?:that\s+)?)(.+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:یادت\s+(?:باشه|بمونه)\s+(?:که\s+)?|فراموش\s+نکن\s+(?:که\s+)?)(.+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:این\s+ترجیح\s+را\s+ذخیره\s+کن\s*:\s*|ذخیره\s+در\s+حافظه\s*:\s*)(.+)",
            re.IGNORECASE,
        ),
    ]

    # Explicit memory deletion triggers (English and Persian)
    _EXPLICIT_FORGET_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(
            r"^\s*(?:please\s+)?forget\s+(?:that\s+|this\s*:\s*|about\s+)?(.+)", re.IGNORECASE
        ),
        re.compile(
            r"^\s*(?:delete\s+(?:that\s+)?memory\s*:\s*|remove\s+from\s+memory\s*:\s*)(.+)",
            re.IGNORECASE,
        ),
        re.compile(
            r"^\s*(?:فراموش\s+کن\s+(?:که\s+|درباره\s+)?|این\s+را\s+از\s+حافظه\s+پاک\s+کن\s*:\s*)(.+)",
            re.IGNORECASE,
        ),
    ]

    # Key / Category heuristics
    _CATEGORY_RULES: ClassVar[list[tuple[MemoryCategory, str, re.Pattern[str]]]] = [
        (
            MemoryCategory.USER_PROFILE,
            "pref.language",
            re.compile(
                r"(?:prefer|language|زبان|انگلیسی|فارسی|english|persian|python|rust|c\+\+|typescript)",
                re.IGNORECASE,
            ),
        ),
        (
            MemoryCategory.PREFERENCE,
            "pref.style",
            re.compile(
                r"(?:concise|detailed|bullet|formal|casual|کوتاه|مختصر|توضیح)", re.IGNORECASE
            ),
        ),
        (
            MemoryCategory.PROJECT,
            "project.context",
            re.compile(
                r"(?:project|repository|architecture|stack|پروژه|مخزن|معماری)", re.IGNORECASE
            ),
        ),
        (
            MemoryCategory.EPISODIC,
            "episodic.decision",
            re.compile(r"(?:decided|resolved|completed|fix|حل شد|تصمیم)", re.IGNORECASE),
        ),
    ]

    def __init__(self, privacy_manager: MemoryPrivacyManager | None = None) -> None:
        self.privacy_manager = privacy_manager or MemoryPrivacyManager()

    def classify_category_and_key(self, text: str) -> tuple[MemoryCategory, str]:
        """Infer best memory category and structured key from text content."""
        for cat, key_name, pattern in self._CATEGORY_RULES:
            if pattern.search(text):
                return cat, key_name
        return MemoryCategory.PREFERENCE, "pref.general"

    def extract_from_user_text(
        self,
        text: str,
        session_id: str = "",
        message_id: str | None = None,
        project_id: str | None = None,
    ) -> ExtractionResult:
        """Parse user input for explicit memory commands or candidate proposals."""
        if not self.privacy_manager.is_storage_allowed():
            return ExtractionResult(candidates=[], forget_requests=[])

        clean_text = text.strip()
        if not clean_text:
            return ExtractionResult(candidates=[], forget_requests=[])

        # 1. Check explicit forget commands
        forget_requests: list[str] = []
        for pat in self._EXPLICIT_FORGET_PATTERNS:
            m = pat.match(clean_text)
            if m:
                target = m.group(1).strip()
                forget_requests.append(target)
                return ExtractionResult(
                    candidates=[],
                    forget_requests=forget_requests,
                    is_explicit_command=True,
                )

        # 2. Check explicit remember commands
        for pat in self._EXPLICIT_REMEMBER_PATTERNS:
            m = pat.match(clean_text)
            if m:
                content_to_save = m.group(1).strip()
                # Check for sensitive data
                if SensitiveDataFilter.contains_sensitive_data(content_to_save):
                    logger.warning(
                        "Rejected explicit memory command containing credentials or secrets."
                    )
                    return ExtractionResult(candidates=[], forget_requests=[])

                cat, key_name = self.classify_category_and_key(content_to_save)
                candidate = MemoryRecord(
                    category=cat,
                    key=key_name,
                    content=content_to_save,
                    project_id=project_id,
                    source_conversation_id=session_id,
                    source_message_id=message_id,
                    importance=0.8,
                    confidence=1.0,
                    status=MemoryStatus.PENDING_APPROVAL,
                    user_approved=False,
                )
                return ExtractionResult(
                    candidates=[candidate],
                    forget_requests=[],
                    is_explicit_command=True,
                )

        # 3. Implicit preference statements (e.g. "From now on, speak in Persian")
        implicit_preference_patterns = [
            re.compile(r"^(?:from\s+now\s+on|always|never|i\s+prefer)\s+(.+)", re.IGNORECASE),
            re.compile(r"^(?:از\s+این\s+به\s+بعد|همیشه|ترجیح\s+می‌دهم)\s+(.+)", re.IGNORECASE),
        ]
        for pat in implicit_preference_patterns:
            m = pat.match(clean_text)
            if m:
                content_to_save = clean_text
                if not SensitiveDataFilter.contains_sensitive_data(content_to_save):
                    cat, key_name = self.classify_category_and_key(content_to_save)
                    candidate = MemoryRecord(
                        category=cat,
                        key=key_name,
                        content=content_to_save,
                        project_id=project_id,
                        source_conversation_id=session_id,
                        source_message_id=message_id,
                        importance=0.6,
                        confidence=0.8,
                        status=MemoryStatus.PENDING_APPROVAL,
                        user_approved=False,
                    )
                    return ExtractionResult(
                        candidates=[candidate],
                        forget_requests=[],
                        is_explicit_command=False,
                    )

        return ExtractionResult(candidates=[], forget_requests=[])
