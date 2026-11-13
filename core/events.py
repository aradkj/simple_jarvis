"""Event types and event dispatching for the JARVIS agent architecture."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class AgentEventType(StrEnum):
    """Enumeration of event types emitted across the agent lifecycle."""

    AGENT_INITIALIZED = "agent.initialized"
    AGENT_STATUS_CHANGED = "agent.status_changed"
    ANALYSIS_STARTED = "agent.analysis_started"
    PLAN_CREATED = "plan.created"
    PLAN_UPDATED = "plan.updated"
    STEP_STARTED = "step.started"
    STEP_COMPLETED = "step.completed"
    STEP_FAILED = "step.failed"
    TOOL_PROPOSED = "tool.proposed"
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_GRANTED = "approval.granted"
    APPROVAL_REJECTED = "approval.rejected"
    REPLANNING_STARTED = "agent.replanning_started"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    AGENT_CANCELLED = "agent.cancelled"
    TASK_CREATED = "task.created"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    TOOL_EXECUTION_REQUESTED = "tool.execution_requested"
    TOOL_EXECUTION_COMPLETED = "tool.execution_completed"
    PERMISSION_REQUESTED = "permission.requested"
    PERMISSION_GRANTED = "permission.granted"
    PERMISSION_DENIED = "permission.denied"
    MESSAGE_RECEIVED = "message.received"
    MESSAGE_SENT = "message.sent"
    ERROR_OCCURRED = "error.occurred"


@dataclass
class AgentEvent:
    """Represents an event published within the JARVIS core system."""

    event_type: AgentEventType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        """Convert the event to a dictionary representation."""
        return {
            "event_type": self.event_type.value,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
        }


EventCallback = Callable[[AgentEvent], None]


class EventBus:
    """Synchronous event publisher and subscriber hub."""

    def __init__(self) -> None:
        self._subscribers: dict[AgentEventType, list[EventCallback]] = {}
        self._global_subscribers: list[EventCallback] = []

    def subscribe(self, event_type: AgentEventType, callback: EventCallback) -> None:
        """Subscribe a callback to a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        if callback not in self._subscribers[event_type]:
            self._subscribers[event_type].append(callback)

    def subscribe_all(self, callback: EventCallback) -> None:
        """Subscribe a callback to all published events."""
        if callback not in self._global_subscribers:
            self._global_subscribers.append(callback)

    def unsubscribe(self, event_type: AgentEventType, callback: EventCallback) -> None:
        """Unsubscribe a callback from a specific event type."""
        if event_type in self._subscribers and callback in self._subscribers[event_type]:
            self._subscribers[event_type].remove(callback)

    def unsubscribe_all(self, callback: EventCallback) -> None:
        """Unsubscribe a callback from all events."""
        if callback in self._global_subscribers:
            self._global_subscribers.remove(callback)
        for sub_list in self._subscribers.values():
            if callback in sub_list:
                sub_list.remove(callback)

    def publish(self, event: AgentEvent) -> None:
        """Publish an event to all relevant subscribers."""
        # Call specific subscribers
        if event.event_type in self._subscribers:
            for callback in list(self._subscribers[event.event_type]):
                callback(event)

        # Call global subscribers
        for callback in list(self._global_subscribers):
            callback(event)

    def clear(self) -> None:
        """Remove all subscriptions."""
        self._subscribers.clear()
        self._global_subscribers.clear()
