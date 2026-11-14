"""Official Meta WhatsApp Business Cloud API Provider for JARVIS Phase 9.

Interacts directly with the official Graph API endpoint:
https://graph.facebook.com/{version}/{phone_number_id}/messages
Never uses unofficial browser DOM scraping or reverse-engineered protocols.
"""

from __future__ import annotations

from typing import Any

import requests

from config import get_settings
from infrastructure.credential_store import get_credential_store
from infrastructure.logging import get_logger
from tools.communication.whatsapp.models import (
    WhatsAppMessage,
    WhatsAppMessageStatus,
    WhatsAppSendResult,
)

logger = get_logger("communication.whatsapp.cloud_api")


class WhatsAppCloudAPIProvider:
    """Sends WhatsApp messages via Meta WhatsApp Business Platform Cloud API."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.credential_store = get_credential_store()

    def is_configured(self) -> bool:
        """Check if phone number ID and access token exist."""
        phone_id = self.get_phone_number_id()
        token = self.get_access_token()
        return bool(phone_id and token)

    def get_phone_number_id(self) -> str:
        """Retrieve phone number ID from credential store or config."""
        return (
            self.credential_store.get_credential("whatsapp", "phone_number_id")
            or getattr(self.settings, "whatsapp_phone_number_id", "")
        ).strip()

    def get_access_token(self) -> str | None:
        """Retrieve Meta Graph API token from credential store."""
        return self.credential_store.get_credential("whatsapp", "access_token")

    def get_status(self) -> dict[str, Any]:
        """Return connectivity and configuration diagnostics."""
        phone_id = self.get_phone_number_id()
        is_conf = self.is_configured()
        return {
            "provider": "whatsapp_cloud_api",
            "configured": is_conf,
            "phone_number_id": phone_id if phone_id else "(Not configured)",
            "api_version": getattr(self.settings, "whatsapp_api_version", "v21.0"),
            "self_phone_configured": bool(getattr(self.settings, "whatsapp_self_phone_number", "")),
        }

    def send_message(self, message: WhatsAppMessage) -> WhatsAppSendResult:
        """Send message using official WhatsApp Cloud API."""
        if not self.is_configured():
            return WhatsAppSendResult(
                success=False,
                status=WhatsAppMessageStatus.FAILED,
                recipient_phone=message.recipient_phone,
                error=(
                    "WhatsApp Cloud API is not configured. Please supply phone_number_id "
                    "and access_token in Communication Settings."
                ),
            )

        phone_id = self.get_phone_number_id()
        token = self.get_access_token()
        version = getattr(self.settings, "whatsapp_api_version", "v21.0")
        url = f"https://graph.facebook.com/{version}/{phone_id}/messages"

        # Format recipient: Meta API expects digits only without leading '+'
        clean_recipient = message.recipient_phone.lstrip("+").strip()

        if message.template_name:
            # Template message payload (required for business-initiated conversations outside 24h window)
            payload: dict[str, Any] = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": clean_recipient,
                "type": "template",
                "template": {
                    "name": message.template_name,
                    "language": {"code": message.template_language},
                },
            }
            if message.template_components:
                payload["template"]["components"] = message.template_components
        else:
            # Free-form text message payload
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": clean_recipient,
                "type": "text",
                "text": {"preview_url": False, "body": message.message_text},
            }

        try:
            resp = requests.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )

            if resp.status_code in (200, 201):
                data = resp.json()
                messages = data.get("messages", [])
                msg_id = messages[0].get("id") if messages else "wa_msg_accepted"
                logger.info(
                    f"WhatsApp Cloud API accepted message to {message.recipient_phone}: ID={msg_id}"
                )
                return WhatsAppSendResult(
                    success=True,
                    status=WhatsAppMessageStatus.ACCEPTED,
                    message_id=msg_id,
                    recipient_phone=message.recipient_phone,
                    details=data,
                )

            err_data = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            err_msg = err_data.get("error", {}).get("message") or resp.text
            err_code = err_data.get("error", {}).get("code")

            logger.error(
                f"WhatsApp Cloud API error {resp.status_code} (code {err_code}): {err_msg}"
            )
            return WhatsAppSendResult(
                success=False,
                status=WhatsAppMessageStatus.FAILED,
                recipient_phone=message.recipient_phone,
                error=f"WhatsApp Cloud API error {resp.status_code}: {err_msg}",
                details=err_data,
            )

        except requests.exceptions.Timeout:
            logger.warning(f"WhatsApp Cloud API request timed out for {message.recipient_phone}")
            return WhatsAppSendResult(
                success=False,
                status=WhatsAppMessageStatus.SUBMITTED,
                recipient_phone=message.recipient_phone,
                error="Request timed out after submission. Outcome is uncertain; verify before retrying.",
            )
        except Exception as exc:
            logger.error(f"Failed to submit message to WhatsApp Cloud API: {exc}")
            return WhatsAppSendResult(
                success=False,
                status=WhatsAppMessageStatus.FAILED,
                recipient_phone=message.recipient_phone,
                error=str(exc),
            )
