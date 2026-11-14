"""Email integration module for JARVIS Phase 9."""

from tools.communication.email.base import BaseEmailProvider
from tools.communication.email.email_service import EmailService, get_email_service
from tools.communication.email.email_tools import (
    EmailComposeInput,
    EmailComposeTool,
    EmailSendInput,
    EmailSendTool,
    EmailStatusInput,
    EmailStatusTool,
)
from tools.communication.email.gmail_provider import GmailEmailProvider
from tools.communication.email.mock_provider import MockEmailProvider
from tools.communication.email.models import (
    EmailAttachment,
    EmailMessage,
    EmailSendResult,
    EmailSendStatus,
)
from tools.communication.email.msgraph_provider import MicrosoftGraphEmailProvider

__all__ = [
    "BaseEmailProvider",
    "EmailAttachment",
    "EmailComposeInput",
    "EmailComposeTool",
    "EmailMessage",
    "EmailSendInput",
    "EmailSendResult",
    "EmailSendStatus",
    "EmailSendTool",
    "EmailService",
    "EmailStatusInput",
    "EmailStatusTool",
    "GmailEmailProvider",
    "MicrosoftGraphEmailProvider",
    "MockEmailProvider",
    "get_email_service",
]
