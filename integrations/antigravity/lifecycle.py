"""Antigravity Task Lifecycle State Machine & Tracker."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from infrastructure.logging import get_logger
from integrations.antigravity.verifier import TaskVerificationResult
from integrations.events import IntegrationEvent, IntegrationEventType

logger = get_logger("antigravity_lifecycle")


class TaskLifecycleState(StrEnum):
    CREATED = "created"
    ACCEPTED = "accepted"
    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class AntigravityTaskRecord:
    task_id: str
    prompt: str
    workspace_path: str
    state: TaskLifecycleState = TaskLifecycleState.CREATED
    model: str = "inherit"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    exit_code: int | None = None
    output_log: list[str] = field(default_factory=list)
    error_message: str | None = None
    verification: TaskVerificationResult | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def duration_seconds(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.completed_at or datetime.now(UTC)
        return max(0.0, (end - self.started_at).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "workspace_path": self.workspace_path,
            "state": self.state.value,
            "model": self.model,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_seconds": self.duration_seconds(),
            "exit_code": self.exit_code,
            "output_log_tail": self.output_log[-10:] if self.output_log else [],
            "error_message": self.error_message,
            "verification": self.verification.to_dict() if self.verification else None,
            "metadata": self.metadata,
        }


class AntigravityLifecycleTracker:
    """Thread-safe lifecycle coordinator emitting structured events to IntegrationHub."""

    _instance: AntigravityLifecycleTracker | None = None
    _lock = threading.RLock()

    def __init__(self) -> None:
        self._tasks: dict[str, AntigravityTaskRecord] = {}
        self._max_records = 200

    @classmethod
    def get_instance(cls) -> AntigravityLifecycleTracker:
        with cls._lock:
            if cls._instance is None:
                cls._instance = AntigravityLifecycleTracker()
            return cls._instance

    def create_task(
        self,
        prompt: str,
        workspace_path: str | Path,
        model: str = "inherit",
        metadata: dict[str, Any] | None = None,
    ) -> AntigravityTaskRecord:
        task_id = f"agy-task-{uuid.uuid4().hex[:8]}"
        record = AntigravityTaskRecord(
            task_id=task_id,
            prompt=prompt,
            workspace_path=str(Path(workspace_path).resolve()),
            model=model,
            metadata=metadata or {},
        )
        with self._lock:
            self._tasks[task_id] = record
            if len(self._tasks) > self._max_records:
                oldest = sorted(self._tasks.keys(), key=lambda tid: self._tasks[tid].created_at)[0]
                del self._tasks[oldest]

        self._emit(IntegrationEventType.TASK_CREATED, record)
        return record

    def transition(
        self,
        task_id: str,
        new_state: TaskLifecycleState,
        payload_extra: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if not record:
                return

            record.state = new_state
            now = datetime.now(UTC)

            if new_state == TaskLifecycleState.STARTED and not record.started_at:
                record.started_at = now
            elif new_state in (
                TaskLifecycleState.COMPLETED,
                TaskLifecycleState.FAILED,
                TaskLifecycleState.CANCELLED,
                TaskLifecycleState.TIMEOUT,
            ):
                record.completed_at = now

        event_map = {
            TaskLifecycleState.CREATED: IntegrationEventType.TASK_CREATED,
            TaskLifecycleState.ACCEPTED: IntegrationEventType.TASK_ACCEPTED,
            TaskLifecycleState.STARTED: IntegrationEventType.TASK_STARTED,
            TaskLifecycleState.PROGRESS: IntegrationEventType.TASK_PROGRESS,
            TaskLifecycleState.COMPLETED: IntegrationEventType.TASK_COMPLETED,
            TaskLifecycleState.FAILED: IntegrationEventType.TASK_FAILED,
            TaskLifecycleState.CANCELLED: IntegrationEventType.TASK_CANCELLED,
            TaskLifecycleState.TIMEOUT: IntegrationEventType.TASK_TIMEOUT,
        }

        event_type = event_map.get(new_state, IntegrationEventType.TASK_PROGRESS)
        self._emit(event_type, record, extra=payload_extra)

    def append_output(self, task_id: str, line: str) -> None:
        with self._lock:
            record = self._tasks.get(task_id)
            if record:
                record.output_log.append(line)
                if len(record.output_log) > 2000:
                    record.output_log = record.output_log[-1000:]

    def get_task(self, task_id: str) -> AntigravityTaskRecord | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, limit: int = 50) -> list[AntigravityTaskRecord]:
        with self._lock:
            sorted_tasks = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
            return sorted_tasks[:limit]

    def _emit(
        self,
        event_type: IntegrationEventType,
        record: AntigravityTaskRecord,
        extra: dict[str, Any] | None = None,
    ) -> None:
        try:
            from integrations.hub import get_integration_hub

            hub = get_integration_hub()
            payload = {
                "task_id": record.task_id,
                "state": record.state.value,
                "workspace": record.workspace_path,
                "prompt": record.prompt[:200],
                "model": record.model,
            }
            if extra:
                payload.update(extra)

            hub.publish(
                IntegrationEvent(
                    event_type=event_type,
                    integration_id="antigravity",
                    task_id=record.task_id,
                    operation="delegate_task",
                    payload=payload,
                )
            )
        except Exception as exc:
            logger.debug(f"Failed to emit integration event {event_type}: {exc}")
