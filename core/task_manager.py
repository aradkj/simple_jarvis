"""Task management and lifecycle tracking for JARVIS."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from core.events import AgentEvent, AgentEventType, EventBus
from core.execution_context import ExecutionContext
from infrastructure.logging import get_logger

logger = get_logger("task_manager")


class TaskStatus(StrEnum):
    """Lifecycle status of a task."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """Represents a discrete executable unit of work within the agent."""

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    context: ExecutionContext = field(default_factory=ExecutionContext)
    result: Any = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def mark_started(self) -> None:
        """Mark the task as started."""
        self.status = TaskStatus.RUNNING
        self.started_at = datetime.now(UTC)

    def mark_completed(self, result: Any = None) -> None:
        """Mark the task as successfully completed."""
        self.status = TaskStatus.COMPLETED
        self.result = result
        self.completed_at = datetime.now(UTC)

    def mark_failed(self, error: str) -> None:
        """Mark the task as failed with an error message."""
        self.status = TaskStatus.FAILED
        self.error = error
        self.completed_at = datetime.now(UTC)

    def cancel(self) -> None:
        """Cancel the task and its underlying execution context."""
        self.status = TaskStatus.CANCELLED
        self.context.cancel()
        self.completed_at = datetime.now(UTC)


class TaskManager:
    """Coordinates task registration, state transitions, and cancellation."""

    def __init__(self, event_bus: EventBus | None = None) -> None:
        self._tasks: dict[str, Task] = {}
        self.event_bus = event_bus

    def create_task(self, description: str, context: ExecutionContext | None = None) -> Task:
        """Create and register a new task."""
        ctx = context or ExecutionContext()
        task = Task(description=description, context=ctx)
        ctx.task_id = task.task_id
        self._tasks[task.task_id] = task

        logger.debug(f"Created task {task.task_id}: {description}")
        if self.event_bus:
            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.TASK_CREATED,
                    payload={"task_id": task.task_id, "description": description},
                )
            )
        return task

    def get_task(self, task_id: str) -> Task | None:
        """Retrieve a task by ID."""
        return self._tasks.get(task_id)

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        """List all tasks, optionally filtered by status."""
        if status is None:
            return list(self._tasks.values())
        return [t for t in self._tasks.values() if t.status == status]

    def cancel_task(self, task_id: str) -> bool:
        """Cancel a running or pending task."""
        task = self._tasks.get(task_id)
        if not task:
            logger.warning(f"Attempted to cancel unknown task: {task_id}")
            return False

        if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            logger.debug(f"Task {task_id} already concluded with status {task.status.value}")
            return False

        task.cancel()
        logger.info(f"Cancelled task {task_id}")
        if self.event_bus:
            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.TASK_CANCELLED,
                    payload={"task_id": task_id},
                )
            )
        return True

    def clear(self) -> None:
        """Clear all tasks."""
        self._tasks.clear()
