"""Data models for Antigravity Coding Agent Subsystem."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class CodingTaskStatus(StrEnum):
    """Lifecycle states of a delegated coding task."""

    PENDING = "pending"
    RUNNING = "running"
    STREAMING = "streaming"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StreamEvent:
    """An NDJSON event emitted by the agy stream."""

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    text_delta: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class VerificationResult:
    """Outcome of independent verification after code modifications."""

    verified: bool
    git_changed_files: list[str] = field(default_factory=list)
    git_diff_summary: str = ""
    tests_executed: bool = False
    tests_passed: bool = False
    test_output: str = ""
    linter_clean: bool = True
    linter_output: str = ""
    message: str = ""


@dataclass
class CodingTask:
    """Represents a software engineering task delegated to Antigravity."""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str = ""
    workspace: str = ""
    model: str = ""
    status: CodingTaskStatus = CodingTaskStatus.PENDING
    conversation_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_seconds: float = 0.0
    response_text: str = ""
    events: list[StreamEvent] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)
    verification: VerificationResult | None = None
    remediation_attempts: int = 0
    error_message: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "workspace": self.workspace,
            "model": self.model,
            "status": self.status.value,
            "conversation_id": self.conversation_id,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": round(self.duration_seconds, 2),
            "response_text": self.response_text,
            "event_count": len(self.events),
            "remediation_attempts": self.remediation_attempts,
            "error_message": self.error_message,
            "usage": self.usage,
            "verified": self.verification.verified if self.verification else False,
        }
