"""Integration event definitions for the JARVIS Universal Integration Hub."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class IntegrationEventType(StrEnum):
    """Event types published across the integration lifecycle."""

    # Hub & Connection Events
    INTEGRATION_REGISTERED = "integration.registered"
    INTEGRATION_STATE_CHANGED = "integration.state_changed"
    INTEGRATION_CONNECTED = "integration.connected"
    INTEGRATION_DISCONNECTED = "integration.disconnected"
    INTEGRATION_HEALTH_CHANGED = "integration.health_changed"
    INTEGRATION_AUTH_CHANGED = "integration.auth_changed"

    # Task Lifecycle Events (Unified across CLI and IDE)
    TASK_CREATED = "integration.task.created"
    TASK_ACCEPTED = "integration.task.accepted"
    TASK_STARTED = "integration.task.started"
    TASK_PROGRESS = "integration.task.progress"
    TASK_COMPLETED = "integration.task.completed"
    TASK_FAILED = "integration.task.failed"
    TASK_CANCELLED = "integration.task.cancelled"
    TASK_TIMEOUT = "integration.task.timeout"
    TASK_INTERRUPTED = "integration.task.interrupted"

    # Notification & Messaging Events
    NOTIFICATION_QUEUED = "integration.notification.queued"
    NOTIFICATION_SENT = "integration.notification.sent"
    NOTIFICATION_FAILED = "integration.notification.failed"
    MESSAGE_RECEIVED = "integration.message.received"

    # Security & Audit Events
    AUDIT_OPERATION_EXECUTED = "integration.audit.executed"
    PERMISSION_EVALUATED = "integration.permission.evaluated"


@dataclass
class IntegrationEvent:
    """Structured event emitted by an integration or the Integration Hub."""

    event_type: IntegrationEventType
    integration_id: str
    task_id: str | None = None
    operation: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "integration_id": self.integration_id,
            "task_id": self.task_id,
            "operation": self.operation,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
        }
