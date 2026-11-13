"""Execution context for tracking execution state, metadata, and cancellation."""

import contextlib
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class CancellationToken:
    """Thread-safe cancellation token for interrupting long-running operations."""

    def __init__(self) -> None:
        self._is_cancelled = threading.Event()
        self._callbacks: list[Any] = []
        self._lock = threading.Lock()

    def register_callback(self, callback: Any) -> None:
        """Register a callback to be called immediately upon cancellation (or right away if already cancelled)."""
        run_now = False
        with self._lock:
            if self._is_cancelled.is_set():
                run_now = True
            else:
                self._callbacks.append(callback)
        if run_now:
            with contextlib.suppress(Exception):
                callback()

    def cancel(self) -> None:
        """Signal cancellation and invoke all registered callbacks."""
        self._is_cancelled.set()
        with self._lock:
            callbacks = list(self._callbacks)
            self._callbacks.clear()
        for cb in callbacks:
            with contextlib.suppress(Exception):
                cb()

    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._is_cancelled.is_set()

    def reset(self) -> None:
        """Reset the cancellation state."""
        with self._lock:
            self._is_cancelled.clear()
            self._callbacks.clear()


@dataclass
class ExecutionContext:
    """Execution context associated with an agent task, tool invocation, or session."""

    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_id: str | None = None
    user_id: str = "local_user"
    project_id: str | None = None
    memory_context: str = ""
    cancellation_token: CancellationToken = field(default_factory=CancellationToken)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_cancelled(self) -> bool:
        """Return True if execution has been cancelled."""
        return self.cancellation_token.is_cancelled()

    def cancel(self) -> None:
        """Request cancellation of the current execution."""
        self.cancellation_token.cancel()

    def create_child_context(self, task_id: str | None = None) -> "ExecutionContext":
        """Create a child execution context inheriting the session and cancellation token."""
        return ExecutionContext(
            session_id=self.session_id,
            task_id=task_id or self.task_id,
            user_id=self.user_id,
            project_id=self.project_id,
            memory_context=self.memory_context,
            cancellation_token=self.cancellation_token,
            metadata=dict(self.metadata),
        )
