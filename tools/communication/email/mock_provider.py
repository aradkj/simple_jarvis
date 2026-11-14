"""Mock Email Provider for deterministic automated testing."""

from __future__ import annotations

import uuid
from typing import Any

from tools.communication.email.base import BaseEmailProvider
from tools.communication.email.models import (
    EmailMessage,
    EmailSendResult,
    EmailSendStatus,
)


class MockEmailProvider(BaseEmailProvider):
    """Deterministic Mock Email Provider."""

    def __init__(self, should_succeed: bool = True, authenticated: bool = True) -> None:
        self.should_succeed = should_succeed
        self._authenticated = authenticated
        self.sent_messages: list[EmailMessage] = []

    @property
    def provider_id(self) -> str:
        return "mock_email"

    def is_authenticated(self) -> bool:
        return self._authenticated

    def get_account_info(self) -> dict[str, Any]:
        return {
            "authenticated": self._authenticated,
            "provider": "mock",
            "email_address": "test_jarvis@example.com",
        }

    def send_email(self, message: EmailMessage) -> EmailSendResult:
        if not self._authenticated:
            return EmailSendResult(
                success=False,
                status=EmailSendStatus.FAILED,
                provider="mock",
                error="Mock email account not connected.",
            )

        if not self.should_succeed:
            return EmailSendResult(
                success=False,
                status=EmailSendStatus.FAILED,
                provider="mock",
                error="Simulated provider API failure.",
            )

        self.sent_messages.append(message)
        msg_id = f"mock_msg_{uuid.uuid4().hex[:8]}"
        return EmailSendResult(
            success=True,
            status=EmailSendStatus.ACCEPTED,
            message_id=msg_id,
            provider="mock",
            details={"recipient_count": len(message.to)},
        )

    def disconnect(self) -> bool:
        self._authenticated = False
        return True
