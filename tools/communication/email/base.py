"""Abstract base class for email providers in JARVIS Phase 9."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from tools.communication.email.models import EmailMessage, EmailSendResult


class BaseEmailProvider(ABC):
    """Abstract interface implemented by all email delivery providers."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique provider identifier (e.g. 'gmail', 'msgraph')."""
        raise NotImplementedError

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Return True if valid OAuth or API credentials exist."""
        raise NotImplementedError

    @abstractmethod
    def get_account_info(self) -> dict[str, Any]:
        """Return connected account identity and scopes without secrets."""
        raise NotImplementedError

    @abstractmethod
    def send_email(self, message: EmailMessage) -> EmailSendResult:
        """Submit the email message to the provider's official REST API."""
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> bool:
        """Revoke or remove stored credentials for this provider."""
        raise NotImplementedError
