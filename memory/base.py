"""Abstract memory and persistence interfaces for JARVIS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class MessageRole(StrEnum):
    """Role associated with a stored conversation message."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class MessageStatus(StrEnum):
    """Lifecycle and delivery status of a conversation message."""

    COMPLETED = "completed"
    STREAMING = "streaming"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass
class ConversationMessage:
    """Represents a discrete message within a conversation session."""

    role: MessageRole
    content: str
    session_id: str
    message_id: str | None = None
    status: MessageStatus = MessageStatus.COMPLETED
    model: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)
    interruption_reason: str | None = None
    provider_id: str | None = None


class BaseMemoryStore(ABC):
    """Storage contract for persistent conversations, preferences, and agent state."""

    @abstractmethod
    def initialize(self) -> None:
        """Initialize database tables and storage infrastructure."""
        raise NotImplementedError

    @abstractmethod
    def create_session(self, title: str = "New Conversation") -> str:
        """Create a new conversation session and return its unique identifier."""
        raise NotImplementedError

    @abstractmethod
    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """List recent conversation sessions."""
        raise NotImplementedError

    @abstractmethod
    def store_message(self, message: ConversationMessage) -> str:
        """Store a conversation message and return its unique identifier."""
        raise NotImplementedError

    @abstractmethod
    def update_message_content(
        self,
        message_id: str,
        content: str,
        status: MessageStatus = MessageStatus.COMPLETED,
        interruption_reason: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> None:
        """Update the content and completion status of an existing message."""
        raise NotImplementedError

    @abstractmethod
    def get_messages(self, session_id: str, limit: int = 50) -> list[ConversationMessage]:
        """Retrieve recent conversation messages for a session."""
        raise NotImplementedError

    @abstractmethod
    def clear_session_messages(self, session_id: str) -> None:
        """Clear all messages belonging to a specific conversation session."""
        raise NotImplementedError

    @abstractmethod
    def set_preference(self, key: str, value: str) -> None:
        """Set a persistent user configuration or preference value."""
        raise NotImplementedError

    @abstractmethod
    def get_preference(self, key: str, default: str | None = None) -> str | None:
        """Retrieve a persistent preference value."""
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        """Close connections and release database handles."""
        raise NotImplementedError
