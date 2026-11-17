"""Language Policy Manager for bilingual English-Persian assistant interaction.

Enforces the default policy:
- Understand Persian input completely.
- Respond in refined, natural British English by default.
- Switch to Persian ONLY upon explicit user instruction.
- Remember and maintain language choice across multi-turn conversations.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from infrastructure.logging import get_logger

logger = get_logger("persian.language_policy")


class ResponseLanguage(StrEnum):
    """Supported response languages."""

    ENGLISH = "en"
    PERSIAN = "fa"


class LanguageSwitchType(StrEnum):
    """Scope of a requested language switch."""

    NONE = "none"
    SESSION_PERSISTENT = "session_persistent"
    ONE_TURN = "one_turn"


class LanguagePolicyState(BaseModel):
    """Current state of language policy."""

    current_language: ResponseLanguage = ResponseLanguage.ENGLISH
    is_session_overridden: bool = False
    turn_counter: int = 0
    switch_history: list[dict[str, Any]] = Field(default_factory=list)


class LanguagePolicyManager:
    """Manages conversational response language policies and explicit language switching."""

    # Explicit requests to switch to Persian
    PERSIAN_PERSISTENT_PATTERNS = [
        re.compile(
            r"\b(از\s+این\s+به\s+بعد|از\s+الان\s+به\s+بعد|همیشه)\s+(به\s+)?فارسی\s+(حرف\s+بزن|صحبت\s+کن|جواب\s+بده|پاسخ\s+بده|بگو)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(فارسی\s+صحبت\s+کن|فارسی\s+حرف\s+بزن|به\s+فارسی\s+صحبت\s+کن|فارسی\s+جواب\s+بده)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(switch\s+to\s+persian|speak\s+persian|speak\s+in\s+farsi|reply\s+in\s+persian)\b",
            re.IGNORECASE,
        ),
    ]

    PERSIAN_ONE_TURN_PATTERNS = [
        re.compile(
            r"\b(به\s+فارسی\s+بگو|فارسی\s+بگو|به\s+فارسی\s+توضیح\s+بده|فارسیش\s+چی\s+میشه|ترجمه\s+کن\s+به\s+فارسی)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(explain\s+(this\s+)?in\s+persian|say\s+(it\s+)?in\s+persian|translate\s+to\s+persian)\b",
            re.IGNORECASE,
        ),
    ]

    # Explicit requests to switch back to English
    ENGLISH_PERSISTENT_PATTERNS = [
        re.compile(
            r"\b(از\s+این\s+به\s+بعد|از\s+الان\s+به\s+بعد|دوباره|برگرد\s+به)\s+(به\s+)?(انگلیسی|اینگلیسی)\s+(حرف\s+بزن|صحبت\s+کن|جواب\s+بده|پاسخ\s+بده|بگو)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(انگلیسی\s+صحبت\s+کن|انگلیسی\s+حرف\s+بزن|به\s+انگلیسی\s+صحبت\s+کن|اینگلیسی\s+صحبت\s+کن|انگلیسی\s+جواب\s+بده)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(switch\s+(back\s+)?to\s+english|speak\s+english|speak\s+in\s+english|reply\s+in\s+english)\b",
            re.IGNORECASE,
        ),
    ]

    ENGLISH_ONE_TURN_PATTERNS = [
        re.compile(
            r"\b(به\s+انگلیسی\s+بگو|انگلیسی\s+بگو|به\s+انگلیسی\s+توضیح\s+بده|انگلیسیش\s+چی\s+میشه)\b",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(explain\s+(this\s+)?in\s+english|say\s+(it\s+)?in\s+english|translate\s+to\s+english)\b",
            re.IGNORECASE,
        ),
    ]

    def __init__(self, default_language: ResponseLanguage = ResponseLanguage.ENGLISH) -> None:
        self.default_language = default_language
        self.state = LanguagePolicyState(current_language=default_language)

    @property
    def current_language(self) -> ResponseLanguage:
        """Return currently active response language."""
        return self.state.current_language

    def evaluate_request(self, user_text: str) -> tuple[ResponseLanguage, LanguageSwitchType, str]:
        """Evaluate user utterance for explicit language instructions.

        Returns:
            target_language: The language to use for the response
            switch_type: Type of switch (session_persistent, one_turn, or none)
            reason: Explanation of the policy decision
        """
        self.state.turn_counter += 1
        text = user_text.strip()

        # Check English switch commands first (if currently Persian)
        for pattern in self.ENGLISH_PERSISTENT_PATTERNS:
            if pattern.search(text):
                self.state.current_language = ResponseLanguage.ENGLISH
                self.state.is_session_overridden = False
                self._record_switch(
                    ResponseLanguage.ENGLISH,
                    LanguageSwitchType.SESSION_PERSISTENT,
                    "User requested persistent English",
                )
                return (
                    ResponseLanguage.ENGLISH,
                    LanguageSwitchType.SESSION_PERSISTENT,
                    "Switched to persistent English by user request",
                )

        for pattern in self.ENGLISH_ONE_TURN_PATTERNS:
            if pattern.search(text):
                return (
                    ResponseLanguage.ENGLISH,
                    LanguageSwitchType.ONE_TURN,
                    "One-turn English requested by user",
                )

        # Check Persian switch commands
        for pattern in self.PERSIAN_PERSISTENT_PATTERNS:
            if pattern.search(text):
                self.state.current_language = ResponseLanguage.PERSIAN
                self.state.is_session_overridden = True
                self._record_switch(
                    ResponseLanguage.PERSIAN,
                    LanguageSwitchType.SESSION_PERSISTENT,
                    "User requested persistent Persian",
                )
                return (
                    ResponseLanguage.PERSIAN,
                    LanguageSwitchType.SESSION_PERSISTENT,
                    "Switched to persistent Persian by user request",
                )

        for pattern in self.PERSIAN_ONE_TURN_PATTERNS:
            if pattern.search(text):
                return (
                    ResponseLanguage.PERSIAN,
                    LanguageSwitchType.ONE_TURN,
                    "One-turn Persian requested by user",
                )

        # Maintain current session state
        return (
            self.state.current_language,
            LanguageSwitchType.NONE,
            f"Maintaining current policy ({self.state.current_language.value})",
        )

    def _record_switch(
        self, lang: ResponseLanguage, switch_type: LanguageSwitchType, reason: str
    ) -> None:
        self.state.switch_history.append(
            {
                "turn": self.state.turn_counter,
                "target_language": lang.value,
                "switch_type": switch_type.value,
                "reason": reason,
            }
        )
        logger.info("Language policy updated: %s (%s) - %s", lang.value, switch_type.value, reason)

    def get_system_directive(self, target_language: ResponseLanguage | None = None) -> str:
        """Generate a system prompt instruction snippet enforcing the active language."""
        lang = target_language or self.state.current_language
        if lang == ResponseLanguage.PERSIAN:
            return (
                "IMPORTANT RESPONSE LANGUAGE DIRECTIVE: The user has requested to communicate in PERSIAN. "
                "Respond in natural, fluent, courteous Persian (فارسی روان و محترمانه). "
                "Keep technical terms, identifiers, paths, and commands in their standard English form where appropriate."
            )
        return (
            "IMPORTANT RESPONSE LANGUAGE DIRECTIVE: The user may communicate in Persian or English. "
            "However, you MUST formulate your response in polished, natural British English (e.g., 'Certainly, sir.', 'Right away, sir.'). "
            "Do NOT respond in Persian unless the user explicitly commands you to speak or reply in Persian."
        )

    def reset(self) -> None:
        """Reset language policy back to British English default."""
        self.state = LanguagePolicyState(current_language=self.default_language)
