"""Official Google Gmail REST API Provider for JARVIS Phase 9.

Uses the official Gmail REST API (v1/users/me/messages/send) with delegated
OAuth 2.0 access token stored securely via Windows DPAPI credential store.
Never requires or stores user passwords.
"""

from __future__ import annotations

import base64
import mimetypes
from email.message import EmailMessage as PyEmailMessage
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

logger = get_logger("communication.email.gmail")


class GmailEmailProvider(BaseEmailProvider):
    """Sends email via official Gmail REST API."""

    GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
    OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(self) -> None:
        self.credential_store = get_credential_store()

    @property
    def provider_id(self) -> str:
        return "gmail"

    def is_authenticated(self) -> bool:
        """Check if an access token or refresh token is available."""
        access_token = self.credential_store.get_credential("gmail", "access_token")
        refresh_token = self.credential_store.get_credential("gmail", "refresh_token")
        return bool(access_token or refresh_token)

    def get_account_info(self) -> dict[str, Any]:
        """Query Gmail profile for current email address and status."""
        if not self.is_authenticated():
            return {"authenticated": False, "provider": "gmail"}

        token = self._get_valid_token()
        if not token:
            return {
                "authenticated": False,
                "provider": "gmail",
                "error": "Token expired or missing",
            }

        try:
            resp = requests.get(
                self.GMAIL_PROFILE_URL,
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "authenticated": True,
                    "provider": "gmail",
                    "email_address": data.get("emailAddress", "Connected User"),
                    "messages_total": data.get("messagesTotal"),
                }
            return {
                "authenticated": False,
                "provider": "gmail",
                "status_code": resp.status_code,
                "error": resp.text,
            }
        except Exception as exc:
            return {"authenticated": False, "provider": "gmail", "error": str(exc)}

    def _get_valid_token(self) -> str | None:
        """Retrieve active access token, refreshing if necessary."""
        access_token = self.credential_store.get_credential("gmail", "access_token")
        if access_token:
            return access_token

        # Try refresh flow if refresh_token and client credentials exist
        refresh_token = self.credential_store.get_credential("gmail", "refresh_token")
        client_id = self.credential_store.get_credential("gmail", "client_id")
        client_secret = self.credential_store.get_credential("gmail", "client_secret")

        if refresh_token and client_id and client_secret:
            try:
                resp = requests.post(
                    self.OAUTH_TOKEN_URL,
                    data={
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "refresh_token": refresh_token,
                        "grant_type": "refresh_token",
                    },
                    timeout=10,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    new_token = data.get("access_token")
                    if new_token:
                        self.credential_store.store_credential("gmail", "access_token", new_token)
                        return new_token
            except Exception as exc:
                logger.error(f"Gmail token refresh failed: {exc}")

        return None

    def build_mime_message(self, message: EmailMessage) -> bytes:
        """Construct standard RFC 2822 MIME message."""
        mime = PyEmailMessage()
        mime["To"] = ", ".join(message.to)
        if message.cc:
            mime["Cc"] = ", ".join(message.cc)
        if message.bcc:
            mime["Bcc"] = ", ".join(message.bcc)
        mime["Subject"] = message.subject

        if message.body_html:
            mime.set_content(message.body_text)
            mime.add_alternative(message.body_html, subtype="html")
        else:
            mime.set_content(message.body_text)

        # Attach validated files
        for att in message.attachments:
            if not att.file_path.exists():
                continue
            ctype, _ = mimetypes.guess_type(str(att.file_path))
            if ctype is None:
                maintype, subtype = "application", "octet-stream"
            else:
                maintype, subtype = ctype.split("/", 1)

            file_bytes = att.file_path.read_bytes()
            mime.add_attachment(
                file_bytes,
                maintype=maintype,
                subtype=subtype,
                filename=att.file_name,
            )

        return mime.as_bytes()

    def send_email(self, message: EmailMessage) -> EmailSendResult:
        """Send message using Gmail REST API."""
        if not self.is_authenticated():
            return EmailSendResult(
                success=False,
                status=EmailSendStatus.FAILED,
                provider="gmail",
                error="Gmail account is not connected. Please authenticate in Communication Settings.",
            )

        token = self._get_valid_token()
        if not token:
            return EmailSendResult(
                success=False,
                status=EmailSendStatus.FAILED,
                provider="gmail",
                error="Gmail OAuth token is expired or invalid.",
            )

        try:
            raw_bytes = self.build_mime_message(message)
            raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("ascii")

            payload = {"raw": raw_b64}
            resp = requests.post(
                self.GMAIL_SEND_URL,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=20,
            )

            if resp.status_code in (200, 202):
                data = resp.json()
                msg_id = data.get("id")
                logger.info(f"Gmail successfully accepted outbound message: ID={msg_id}")
                return EmailSendResult(
                    success=True,
                    status=EmailSendStatus.ACCEPTED,
                    message_id=msg_id,
                    provider="gmail",
                    details=data,
                )

            err_text = resp.text
            logger.error(f"Gmail API error {resp.status_code}: {err_text}")
            return EmailSendResult(
                success=False,
                status=EmailSendStatus.FAILED,
                provider="gmail",
                error=f"Gmail API rejected request (HTTP {resp.status_code}): {err_text}",
            )

        except requests.exceptions.Timeout:
            logger.warning("Gmail API timed out during send request.")
            return EmailSendResult(
                success=False,
                status=EmailSendStatus.UNKNOWN,
                provider="gmail",
                error="Request timed out after submission. Outcome is uncertain; verify before retrying.",
            )
        except Exception as exc:
            logger.error(f"Failed to submit email via Gmail API: {exc}")
            return EmailSendResult(
                success=False,
                status=EmailSendStatus.FAILED,
                provider="gmail",
                error=str(exc),
            )

    def disconnect(self) -> bool:
        """Revoke and delete Gmail credentials."""
        self.credential_store.delete_credential("gmail")
        logger.info("Gmail account disconnected.")
        return True
