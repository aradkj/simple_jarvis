"""Data models for Email Integration in JARVIS Phase 9."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any


class EmailSendStatus(StrEnum):
    """Detailed truthful status of an outbound email operation."""

    DRAFTED = "drafted"
    DRAFT_CREATED = "drafted"  # Compatibility alias
    PENDING_APPROVAL = "pending_approval"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    DELIVERY_CONFIRMED = "delivery_confirmed"
    DELIVERED = "delivery_confirmed"  # Compatibility alias
    FAILED = "failed"
    UNKNOWN = "unknown"
    SUBMISSION_UNKNOWN = "unknown"  # Explicit alias for post-submission network timeouts


@dataclass
class EmailAttachment:
    """Validated attachment file metadata."""

    file_path: Path
    file_name: str
    file_size_bytes: int
    mime_type: str = "application/octet-stream"


@dataclass
class EmailMessage:
    """Structured email message payload."""

    to: list[str]
    subject: str
    body_text: str
    body_html: str | None = None
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    attachments: list[EmailAttachment] = field(default_factory=list)
    draft_id: str | None = None
    provider: str = "gmail"
    is_submitted: bool = False

    def to_preview_dict(self) -> dict[str, Any]:
        """Generate safe, readable preview dictionary for user confirmation."""
        return {
            "provider": self.provider,
            "to": self.to,
            "cc": self.cc,
            "bcc": self.bcc,
            "subject": self.subject,
            "body_snippet": self.body_text[:500] + ("..." if len(self.body_text) > 500 else ""),
            "attachments": [
                {"name": a.file_name, "size_bytes": a.file_size_bytes, "path": str(a.file_path)}
                for a in self.attachments
            ],
            "attachments_count": len(self.attachments),
            "payload_hash": self.compute_payload_hash(),
        }

    def compute_payload_hash(self) -> str:
        """Compute cryptographic SHA256 digest of exact message draft contents,
        binding account ID, operation, recipients, subject, body, and actual attachment bytes.
        """
        hasher = hashlib.sha256()
        hasher.update(b"op:send_email|")
        hasher.update(f"account:{self.provider}|".encode())
        hasher.update(f"to:{','.join(sorted(self.to))}|".encode())
        hasher.update(f"cc:{','.join(sorted(self.cc))}|".encode())
        hasher.update(f"bcc:{','.join(sorted(self.bcc))}|".encode())
        hasher.update(f"subject:{self.subject}|".encode())
        hasher.update(f"body_text:{self.body_text}|".encode())
        if self.body_html:
            hasher.update(f"body_html:{self.body_html}|".encode())
        for att in sorted(self.attachments, key=lambda a: a.file_name):
            hasher.update(f"att_name:{att.file_name}|".encode())
            hasher.update(f"att_size:{att.file_size_bytes}|".encode())
            try:
                p = Path(att.file_path)
                if p.is_file():
                    with open(p, "rb") as fp:
                        while chunk := fp.read(65536):
                            hasher.update(chunk)
                else:
                    hasher.update(str(att.file_path).encode("utf-8"))
            except Exception:
                hasher.update(str(att.file_path).encode("utf-8"))
        return hasher.hexdigest()


@dataclass
class EmailSendResult:
    """Result returned after submitting an email to provider API."""

    success: bool
    status: EmailSendStatus
    message_id: str | None = None
    provider: str = "gmail"
    error: str | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)
