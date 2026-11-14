"""Deterministic Mock WhatsApp Provider for automated test suites."""

from __future__ import annotations

import uuid
from typing import Any

from tools.communication.whatsapp.models import (
    WhatsAppMessage,
    WhatsAppMessageStatus,
    WhatsAppSendResult,
)


class MockWhatsAppProvider:
    """Mock WhatsApp provider for automated tests without Meta API calls."""

    def __init__(self, should_succeed: bool = True, configured: bool = True) -> None:
        self.should_succeed = should_succeed
        self._configured = configured
        self.sent_messages: list[WhatsAppMessage] = []

    def is_configured(self) -> bool:
        return self._configured

    def get_status(self) -> dict[str, Any]:
        return {
            "provider": "mock_whatsapp",
            "configured": self._configured,
            "phone_number_id": "mock_phone_12345",
        }

    def send_message(self, message: WhatsAppMessage) -> WhatsAppSendResult:
        if not self._configured:
            return WhatsAppSendResult(
                success=False,
                status=WhatsAppMessageStatus.FAILED,
                recipient_phone=message.recipient_phone,
                error="WhatsApp Cloud API not configured.",
            )

        if not self.should_succeed:
            return WhatsAppSendResult(
                success=False,
                status=WhatsAppMessageStatus.FAILED,
                recipient_phone=message.recipient_phone,
                error="Simulated WhatsApp Cloud API error (e.g. rate limit or 24hr window).",
            )

        self.sent_messages.append(message)
        msg_id = f"wamid.{uuid.uuid4().hex}"
        return WhatsAppSendResult(
            success=True,
            status=WhatsAppMessageStatus.ACCEPTED,
            message_id=msg_id,
            recipient_phone=message.recipient_phone,
            details={"messaging_product": "whatsapp"},
        )
