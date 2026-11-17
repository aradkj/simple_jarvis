"""Meta WhatsApp Cloud API Provider Adapter for JARVIS Universal Integration Hub."""

from __future__ import annotations

from typing import Any

from infrastructure.logging import get_logger
from integrations.whatsapp.provider_base import (
    WhatsAppConnectionStatus,
    WhatsAppProvider,
    WhatsAppProviderType,
    WhatsAppSendResult,
)
from tools.communication.whatsapp.cloud_api_provider import WhatsAppCloudAPIProvider
from tools.communication.whatsapp.models import WhatsAppMessage

logger = get_logger("whatsapp_cloud_provider")


class CloudAPIWhatsAppProvider(WhatsAppProvider):
    """WhatsApp Provider utilizing Meta Graph Cloud API."""

    provider_type = WhatsAppProviderType.CLOUD_API

    def __init__(self) -> None:
        self.underlying = WhatsAppCloudAPIProvider()
        self._connected = False

    def connect(self) -> bool:
        if self.underlying.is_configured():
            self._connected = True
            logger.info("Connected to WhatsApp Cloud API.")
            return True
        logger.warning(
            "WhatsApp Cloud API is not fully configured (missing phone_number_id or access_token)."
        )
        self._connected = False
        return False

    def disconnect(self) -> bool:
        self._connected = False
        return True

    def get_status(self) -> dict[str, Any]:
        info = self.underlying.get_status()
        conn_state = (
            WhatsAppConnectionStatus.CONNECTED
            if self._connected
            else WhatsAppConnectionStatus.DISCONNECTED
        )
        return {
            "type": self.provider_type.value,
            "status": conn_state.value,
            "configured": info.get("configured", False),
            "phone_number_id": info.get("phone_number_id"),
            "api_version": info.get("api_version"),
        }

    def is_connected(self) -> bool:
        return self._connected and self.underlying.is_configured()

    def send_text_message(self, recipient: str, text: str) -> WhatsAppSendResult:
        msg = WhatsAppMessage(
            recipient=recipient,
            text_body=text,
            is_template=False,
        )
        try:
            res = self.underlying.send_message(msg)
            return WhatsAppSendResult(
                success=res.success,
                message_id=res.message_id or "",
                error=res.error_message,
                recipient=recipient,
                details={"status_code": res.status_code, "raw_response": res.raw_response},
            )
        except Exception as exc:
            logger.error(f"Failed to send text message via Cloud API: {exc}")
            return WhatsAppSendResult(
                success=False,
                error=str(exc),
                recipient=recipient,
            )
