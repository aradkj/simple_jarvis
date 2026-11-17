"""Provider-independent WhatsApp abstraction for JARVIS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class WhatsAppProviderType(StrEnum):
    CLOUD_API = "cloud_api"
    LINKED_DEVICE = "linked_device"
    MOCK = "mock"


class WhatsAppConnectionStatus(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    PAIRING_QR = "pairing_qr"
    CONNECTED = "connected"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass
class WhatsAppSendResult:
    success: bool
    message_id: str = ""
    error: str | None = None
    recipient: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    details: dict[str, Any] = field(default_factory=dict)


class WhatsAppProvider(ABC):
    """Abstract base class for all WhatsApp messaging providers."""

    provider_type: WhatsAppProviderType

    @abstractmethod
    def connect(self) -> bool:
        """Connect or initiate session."""
        ...

    @abstractmethod
    def disconnect(self) -> bool:
        """Disconnect session."""
        ...

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        """Return provider status and connection state."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if ready to send and receive."""
        ...

    @abstractmethod
    def send_text_message(self, recipient: str, text: str) -> WhatsAppSendResult:
        """Send a standard text message."""
        ...
