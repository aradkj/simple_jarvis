"""Structured memory models and categorical records for JARVIS Phase 5."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class MemoryCategory(StrEnum):
    """Categorical classification of persistent memories."""

    USER_PROFILE = "user_profile"  # Long-term user facts (languages, tech preferences)
    PREFERENCE = "preference"  # Interaction & workflow preferences (formatting, styles)
    PROJECT = "project"  # Persistent context bound to a specific project
    EPISODIC = "episodic"  # Resolved events, architectural decisions, task outcomes


class MemoryStatus(StrEnum):
    """Lifecycle status of a memory record."""

    PENDING_APPROVAL = "pending_approval"  # Extracted candidate awaiting user confirmation
    ACTIVE = "active"  # Verified, approved and actively retrievable
    SUPERSEDED = "superseded"  # Replaced by a more recent conflicting preference
    ARCHIVED = "archived"  # Retained for reference but deprioritized
    DELETED = "deleted"  # Soft-deleted by user
    EXPIRED = "expired"  # Lapsed after retention duration


@dataclass
class MemoryRecord:
    """Discrete, structured persistent memory unit."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    category: MemoryCategory = MemoryCategory.PREFERENCE
    key: str = ""
    content: str = ""
    normalized_content: str = ""
    project_id: str | None = None
    source_conversation_id: str = ""
    source_message_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    importance: float = 0.5  # 0.0 (trivial) to 1.0 (crucial)
    confidence: float = 1.0  # 0.0 (uncertain) to 1.0 (authoritative)
    status: MemoryStatus = MemoryStatus.PENDING_APPROVAL
    user_approved: bool = False
    content_fingerprint: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.normalized_content:
            self.normalized_content = self.content.strip().lower()
        if not self.content_fingerprint:
            self.content_fingerprint = self.compute_fingerprint()

    def compute_fingerprint(self) -> str:
        """Compute SHA-256 fingerprint of normalized content and key."""
        raw = f"{self.category.value}:{self.key.strip().lower()}:{self.normalized_content}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Convert record to a serializable dictionary."""
        return {
            "id": self.id,
            "category": self.category.value,
            "key": self.key,
            "content": self.content,
            "normalized_content": self.normalized_content,
            "project_id": self.project_id,
            "source_conversation_id": self.source_conversation_id,
            "source_message_id": self.source_message_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "importance": self.importance,
            "confidence": self.confidence,
            "status": self.status.value,
            "user_approved": self.user_approved,
            "content_fingerprint": self.content_fingerprint,
            "metadata": self.metadata,
        }

    @classmethod
    def from_row(cls, row: Any) -> MemoryRecord:
        """Construct record from a database row mapping."""
        row_dict = dict(row)
        meta = row_dict.get("metadata")
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        elif not isinstance(meta, dict):
            meta = {}

        expires_val = row_dict.get("expires_at")
        expires_dt = datetime.fromisoformat(expires_val) if expires_val else None

        return cls(
            id=str(row_dict["id"]),
            category=MemoryCategory(row_dict["category"]),
            key=str(row_dict.get("key") or ""),
            content=str(row_dict.get("content") or ""),
            normalized_content=str(row_dict.get("normalized_content") or ""),
            project_id=row_dict.get("project_id"),
            source_conversation_id=str(row_dict.get("source_conversation_id") or ""),
            source_message_id=row_dict.get("source_message_id"),
            created_at=datetime.fromisoformat(row_dict["created_at"]),
            updated_at=datetime.fromisoformat(row_dict["updated_at"]),
            last_accessed_at=datetime.fromisoformat(row_dict["last_accessed_at"]),
            expires_at=expires_dt,
            importance=float(row_dict.get("importance", 0.5)),
            confidence=float(row_dict.get("confidence", 1.0)),
            status=MemoryStatus(row_dict.get("status", MemoryStatus.ACTIVE.value)),
            user_approved=bool(row_dict.get("user_approved", 0)),
            content_fingerprint=str(row_dict.get("content_fingerprint") or ""),
            metadata=meta,
        )
