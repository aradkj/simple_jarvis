"""Communication subsystem for JARVIS Phase 9 (Email & WhatsApp)."""

from tools.communication.email import (
    EmailComposeTool,
    EmailSendTool,
    EmailService,
    EmailStatusTool,
    get_email_service,
)
from tools.communication.whatsapp import (
    WhatsAppComposeTool,
    WhatsAppSendTool,
    WhatsAppService,
    WhatsAppStatusTool,
    get_whatsapp_service,
)

__all__ = [
    "EmailComposeTool",
    "EmailSendTool",
    "EmailService",
    "EmailStatusTool",
    "WhatsAppComposeTool",
    "WhatsAppSendTool",
    "WhatsAppService",
    "WhatsAppStatusTool",
    "get_email_service",
    "get_whatsapp_service",
]
