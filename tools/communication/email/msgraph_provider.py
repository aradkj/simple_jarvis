"""Official Microsoft Graph API Email Provider for JARVIS Phase 9.

Uses the official Microsoft Graph endpoint (/v1.0/me/sendMail) with delegated
Mail.Send OAuth permission and secure Windows DPAPI token management.
"""

from __future__ import annotations

import base64
from typing import Any

import requests

from infrastructure.credential_store import get_credential_store
from infrastructure.logging import get_logger
from tools.communication.email.base import BaseEmailProvider
from tools.communication.email.models import (
    EmailMessage,
    EmailSendResult,
    EmailSendStatus,
)

logger = get_logger("communication.email.msgraph")


class MicrosoftGraphEmailProvider(BaseEmailProvider):
    """Sends email via official Microsoft Graph REST API."""

    GRAPH_SEND_URL = "https://graph.microsoft.com/v1.0/me/sendMail"
    GRAPH_ME_URL = "https://graph.microsoft.com/v1.0/me"

    def __init__(self) -> None:
        self.credential_store = get_credential_store()

    @property
    def provider_id(self) -> str:
        return "msgraph"

    def is_authenticated(self) -> bool:
        return bool(self.credential_store.get_credential("msgraph", "access_token"))

    def get_account_info(self) -> dict[str, Any]:
        """Query Microsoft Graph /me profile endpoint."""
        token = self.credential_store.get_credential("msgraph", "access_token")
        if not token:
            return {"authenticated": False, "provider": "msgraph"}

        try:
            resp = requests.get(
                self.GRAPH_ME_URL,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "authenticated": True,
                    "provider": "msgraph",
                    "display_name": data.get("displayName"),
                    "user_principal_name": data.get("userPrincipalName"),
                    "mail": data.get("mail"),
                }
            return {"authenticated": False, "provider": "msgraph", "status_code": resp.status_code}
        except Exception as exc:
            return {"authenticated": False, "provider": "msgraph", "error": str(exc)}

    def send_email(self, message: EmailMessage) -> EmailSendResult:
        """Send message using Microsoft Graph /sendMail."""
        token = self.credential_store.get_credential("msgraph", "access_token")
        if not token:
            return EmailSendResult(
                success=False,
                status=EmailSendStatus.FAILED,
                provider="msgraph",
                error="Microsoft Outlook/Office 365 account is not connected.",
            )

        try:
            to_recipients = [{"emailAddress": {"address": addr}} for addr in message.to]
            cc_recipients = [{"emailAddress": {"address": addr}} for addr in message.cc]
            bcc_recipients = [{"emailAddress": {"address": addr}} for addr in message.bcc]

            graph_attachments = []
            for att in message.attachments:
                if not att.file_path.exists():
                    continue
                file_bytes = att.file_path.read_bytes()
                b64_content = base64.b64encode(file_bytes).decode("ascii")
                graph_attachments.append(
                    {
                        "@odata.type": "#microsoft.graph.fileAttachment",
                        "name": att.file_name,
                        "contentType": att.mime_type,
                        "contentBytes": b64_content,
                    }
                )

            body_type = "HTML" if message.body_html else "Text"
            body_content = message.body_html or message.body_text

            payload: dict[str, Any] = {
                "message": {
                    "subject": message.subject,
                    "body": {"contentType": body_type, "content": body_content},
                    "toRecipients": to_recipients,
                    "saveToSentItems": True,
                }
            }
            if cc_recipients:
                payload["message"]["ccRecipients"] = cc_recipients
            if bcc_recipients:
                payload["message"]["bccRecipients"] = bcc_recipients
            if graph_attachments:
                payload["message"]["attachments"] = graph_attachments

            resp = requests.post(
                self.GRAPH_SEND_URL,
                json=payload,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=20,
            )

            # Microsoft Graph sendMail returns 202 Accepted on success
            if resp.status_code == 202:
                logger.info("Microsoft Graph successfully accepted sendMail request.")
                return EmailSendResult(
                    success=True,
                    status=EmailSendStatus.ACCEPTED,
                    message_id="msgraph_accepted",
                    provider="msgraph",
                )

            err_text = resp.text
            logger.error(f"Microsoft Graph API error {resp.status_code}: {err_text}")
            return EmailSendResult(
                success=False,
                status=EmailSendStatus.FAILED,
                provider="msgraph",
                error=f"Microsoft Graph rejected request (HTTP {resp.status_code}): {err_text}",
            )

        except requests.exceptions.Timeout:
            return EmailSendResult(
                success=False,
                status=EmailSendStatus.UNKNOWN,
                provider="msgraph",
                error="Microsoft Graph request timed out. Outcome is uncertain.",
            )
        except Exception as exc:
            return EmailSendResult(
                success=False,
                status=EmailSendStatus.FAILED,
                provider="msgraph",
                error=str(exc),
            )

    def disconnect(self) -> bool:
        self.credential_store.delete_credential("msgraph")
        logger.info("Microsoft Graph account disconnected.")
        return True
