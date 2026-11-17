"""Multilingual Response Controller for JARVIS.

Handles bilingual output formatting (British English persona vs Persian persona),
voice/TTS sanitization (stripping markdown, code blocks, URLs, emojis),
and natural acknowledgment formulation.
"""

from __future__ import annotations

import re
from typing import Any

from core.persian.language_policy import ResponseLanguage
from infrastructure.logging import get_logger

logger = get_logger("persian.response_controller")


class MultilingualResponseController:
    """Formats and sanitizes responses for UI chat display and voice TTS output."""

    # Voice sanitization patterns
    CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```")
    INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")
    MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]+\)")
    URL_PATTERN = re.compile(r"https?://\S+")
    FILE_PATH_PATTERN = re.compile(r"[A-Za-z]:\\[\w\\.-]+")
    MARKDOWN_FORMATTING = re.compile(r"[*_~#>-]")
    MULTIPLE_SPACES = re.compile(r"\s+")
    EMOJI_PATTERN = re.compile(
        r"[\U0001F600-\U0001F64F"  # Emoticons
        r"\U0001F300-\U0001F5FF"  # Symbols & pictographs
        r"\U0001F680-\U0001F6FF"  # Transport & map
        r"\U0001F1E0-\U0001F1FF"  # Flags
        r"\U00002702-\U000027B0"
        r"\U000024C2-\U0001F251]+",
        flags=re.UNICODE,
    )

    def prepare_response(
        self,
        raw_llm_response: str,
        language: ResponseLanguage = ResponseLanguage.ENGLISH,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Process response for display and audio playback.

        Returns:
            display_text: Rich formatted text for the UI chat
            spoken_text: Sanitized conversational prose for TTS playback
        """
        display_text = raw_llm_response.strip()
        spoken_text = self.sanitize_for_speech(display_text, language)

        return display_text, spoken_text

    def sanitize_for_speech(
        self,
        text: str,
        language: ResponseLanguage = ResponseLanguage.ENGLISH,
    ) -> str:
        """Strip markdown, URLs, code blocks, and symbols for natural voice TTS."""
        if not text:
            return ""

        spoken = text

        # Replace code blocks with brief spoken indicator
        if self.CODE_BLOCK_PATTERN.search(spoken):
            if language == ResponseLanguage.PERSIAN:
                spoken = self.CODE_BLOCK_PATTERN.sub("قطعه کد در چت نمایش داده شد.", spoken)
            else:
                spoken = self.CODE_BLOCK_PATTERN.sub(
                    "The code snippet is displayed on your screen, sir.", spoken
                )

        # Replace URLs
        spoken = self.URL_PATTERN.sub("the link", spoken)

        # Clean markdown links [text](url) -> text
        spoken = self.MARKDOWN_LINK_PATTERN.sub(r"\1", spoken)

        # Inline code `variable` -> variable
        spoken = self.INLINE_CODE_PATTERN.sub(r"\1", spoken)

        # File paths C:\foo\bar -> foo bar
        def _clean_path(match: re.Match) -> str:
            path_str = match.group(0)
            parts = [p for p in path_str.replace("\\", "/").split("/") if p and ":" not in p]
            return " ".join(parts[-2:]) if len(parts) >= 2 else parts[-1] if parts else "the file"

        spoken = self.FILE_PATH_PATTERN.sub(_clean_path, spoken)

        # Strip emojis
        spoken = self.EMOJI_PATTERN.sub("", spoken)

        # Strip markdown symbols (*, _, #, >, -, ~)
        spoken = self.MARKDOWN_FORMATTING.sub(" ", spoken)

        # Normalize whitespace
        spoken = self.MULTIPLE_SPACES.sub(" ", spoken).strip()

        # If empty after stripping, provide fallback acknowledgment
        if not spoken:
            return (
                "Task completed, sir."
                if language == ResponseLanguage.ENGLISH
                else "انجام شد قربان."
            )

        return spoken

    def generate_acknowledgment(
        self,
        intent_name: str,
        language: ResponseLanguage = ResponseLanguage.ENGLISH,
        target_name: str | None = None,
    ) -> str:
        """Generate an immediate spoken acknowledgment for low-latency feedback."""
        if language == ResponseLanguage.PERSIAN:
            if target_name:
                return f"حتماً قربان، در حال بررسی {target_name} هستم."
            return "حتماً قربان، در دست بررسی و اجرا است."

        # British English persona
        if target_name:
            return f"Certainly, sir. Inspecting {target_name} now."
        return "Right away, sir."

    def generate_clarification_prompt(
        self,
        ambiguous_phrase: str,
        language: ResponseLanguage = ResponseLanguage.ENGLISH,
    ) -> str:
        """Generate a clarification inquiry when destructive ambiguity is detected."""
        if language == ResponseLanguage.PERSIAN:
            return (
                f"قربان، درخواست شما شامل عبارت مبهم «{ambiguous_phrase}» است. "
                "لطفاً دقیقاً مشخص کنید کدام فایل‌ها یا آیتم‌ها مد نظر شماست تا از هرگونه حذف ناخواسته جلوگیری شود."
            )

        return (
            f"Sir, your request contains an ambiguous instruction: '{ambiguous_phrase}'. "
            "To prevent unintended file modifications or loss, please specify the exact files or targets to act upon."
        )

    def generate_hypothetical_response(
        self,
        explanation: str,
        language: ResponseLanguage = ResponseLanguage.ENGLISH,
    ) -> str:
        """Format an explanation for a hypothetical discussion without executing tools."""
        prefix_en = "Hypothetically speaking, sir: "
        prefix_fa = "از نظر تحلیلی و تئوری قربان: "

        if language == ResponseLanguage.PERSIAN:
            return f"{prefix_fa}{explanation}"
        return f"{prefix_en}{explanation}"

    def format_error(
        self,
        error_message: str,
        language: ResponseLanguage = ResponseLanguage.ENGLISH,
    ) -> str:
        """Format an error message gracefully according to language policy."""
        if language == ResponseLanguage.PERSIAN:
            return f"پوزش می‌طلبم قربان، خطایی در پردازش رخ داد: {error_message}"
        return f"My apologies, sir. An error was encountered: {error_message}"
