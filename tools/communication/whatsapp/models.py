"""Data models for WhatsApp Cloud API integration in JARVIS Phase 9."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class WhatsAppMessageStatus(StrEnum):
    """Lifecycle truthful status of a WhatsApp message."""

    DRAFTED = "drafted"
    DRAFT_CREATED = "drafted"  # Compatibility alias
    PENDING_APPROVAL = "pending_approval"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass
class WhatsAppMessage:
    """Outbound WhatsApp message payload."""

    recipient_phone: str  # Normalized E.164 format (e.g. +989123456789)
    message_text: str
    recipient_name: str | None = None
    template_name: str | None = None
    template_language: str = "en_US"
    template_components: list[dict[str, Any]] = field(default_factory=list)
    draft_id: str | None = None
    account_id: str = "default"

    def to_preview_dict(self) -> dict[str, Any]:
        """Safe human-readable preview for approval UI."""
        return {
            "account_id": self.account_id,
            "recipient_phone": self.recipient_phone,
            "recipient_name": self.recipient_name or "Direct Recipient",
            "message_text": self.message_text,
            "character_count": len(self.message_text),
            "template_name": self.template_name or "(Free-form text message)",
            "payload_hash": self.compute_payload_hash(),
        }

    def compute_payload_hash(self) -> str:
        """Compute cryptographic SHA256 digest of WhatsApp message contents to prevent tampering."""
        hasher = hashlib.sha256()
        hasher.update(b"op:send_whatsapp|")
        hasher.update(f"account:{self.account_id}|".encode())
        hasher.update(f"recipient:{self.recipient_phone}|".encode())
        hasher.update(f"text:{self.message_text}|".encode())
        if self.template_name:
            hasher.update(f"template:{self.template_name}:{self.template_language}|".encode())
        for comp in self.template_components:
            hasher.update(f"comp:{sorted(comp.items())}|".encode())
        return hasher.hexdigest()


@dataclass
class WhatsAppSendResult:
    """Result returned after submitting message to WhatsApp Cloud API."""

    success: bool
    status: WhatsAppMessageStatus
    message_id: str | None = None
    recipient_phone: str = ""
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)
