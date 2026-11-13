"""Privacy enforcement, sensitive data filtering, and access control for JARVIS memory."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from infrastructure.logging import get_logger

logger = get_logger("memory.privacy")


class SensitiveDataError(Exception):
    """Raised when text contains prohibited sensitive personal information or secrets."""


class SensitiveDataFilter:
    """Detects and filters credentials, private keys, financial tokens, and sensitive data."""

    # Patterns for API keys, passwords, private keys, tokens
    _PATTERNS: ClassVar[list[tuple[str, re.Pattern[str]]]] = [
        (
            "api_key",
            re.compile(
                r"(?:api[_-]?key|access[_-]?token|bearer(?:[ _-]?token)?)\s*[:= ]\s*['\"]?([A-Za-z0-9_\-\.]{16,})['\"]?",
                re.IGNORECASE,
            ),
        ),
        (
            "generic_secret",
            re.compile(
                r"(?:secret|password|passwd|pwd)\s*[:=]\s*['\"]?([^\s'\"]{6,})['\"]?",
                re.IGNORECASE,
            ),
        ),
        (
            "private_key",
            re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.IGNORECASE),
        ),
        ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
        ("gemini_key", re.compile(r"\bAIza[0-9A-Za-z-_]{35}\b")),
        ("credit_card", re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")),
        ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
        (
            "jwt",
            re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        ),
    ]

    # Sensitive keywords that must not be stored as automatic long-term memories
    _SENSITIVE_KEYWORDS: ClassVar[set[str]] = {
        "password",
        "passwd",
        "secret_key",
        "master_key",
        "private_key",
        "cvv",
        "credit_card",
        "medical_record",
        "social_security",
    }

    @classmethod
    def contains_sensitive_data(cls, text: str) -> bool:
        """Return True if text matches any credential, key, or sensitive pattern."""
        if not text:
            return False

        for name, pattern in cls._PATTERNS:
            if pattern.search(text):
                logger.warning(f"SensitiveDataFilter matched prohibited pattern: {name}")
                return True

        # Check for direct credential assignments
        lower = text.lower()
        for kw in cls._SENSITIVE_KEYWORDS:
            if kw in lower and any(sym in lower for sym in [":", "=", "is ", "was "]):
                logger.warning(f"SensitiveDataFilter detected sensitive keyword phrase: {kw}")
                return True

        return False

    @classmethod
    def validate_or_raise(cls, text: str) -> None:
        """Validate text contains no sensitive secrets or raise SensitiveDataError."""
        if cls.contains_sensitive_data(text):
            raise SensitiveDataError(
                "Text contains credentials, private keys, or sensitive personal data prohibited from memory storage."
            )


class MemoryPrivacyManager:
    """Enforces application privacy boundaries and master memory switches."""

    def __init__(
        self,
        memory_enabled: bool = True,
        allow_cloud_transmission: bool = False,
    ) -> None:
        self.memory_enabled = memory_enabled
        self.allow_cloud_transmission = allow_cloud_transmission
        self.filter = SensitiveDataFilter()

    def is_retrieval_allowed(self) -> bool:
        """True if local long-term memory retrieval is active and authorized."""
        return self.memory_enabled

    def is_storage_allowed(self) -> bool:
        """True if new long-term memories may be stored locally."""
        return self.memory_enabled

    def is_cloud_transmission_allowed(self) -> bool:
        """True if transmitting retrieved memories to external AI providers is authorized."""
        return self.memory_enabled and self.allow_cloud_transmission

    def validate_candidate_content(self, content: str) -> None:
        """Verify content is safe for persistent storage."""
        if not self.is_storage_allowed():
            raise SensitiveDataError("Long-term memory subsystem is disabled by user policy.")
        self.filter.validate_or_raise(content)

    def filter_memories_for_cloud_transmission(self, memories: list[Any]) -> list[Any]:
        """Strictly filter memory records for external provider transmission.

        Ensures records are active, user-approved, and contain zero credentials or secrets.
        """
        if not self.is_cloud_transmission_allowed():
            return []

        safe_records = []
        for m in memories:
            # Check user approval
            if not getattr(m, "user_approved", False):
                continue
            # Check active status
            status_val = getattr(m, "status", None)
            status_str = status_val.value if hasattr(status_val, "value") else str(status_val)
            if status_str != "active":
                continue
            # Check content against sensitive data filter
            content = getattr(m, "content", "")
            if self.filter.contains_sensitive_data(content):
                logger.warning(
                    f"Privacy boundary blocked memory {getattr(m, 'id', 'unknown')} from cloud transmission (sensitive pattern detected)."
                )
                continue
            safe_records.append(m)

        return safe_records
