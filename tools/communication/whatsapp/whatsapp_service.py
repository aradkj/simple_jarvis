"""WhatsApp service managing phone normalization, contact resolution, and message delivery."""

from __future__ import annotations

import contextlib
import os
import re
import threading
import uuid
from datetime import UTC, datetime
from typing import Any

from config import get_settings
from infrastructure.communication_db import CommunicationDatabase, get_communication_db
from infrastructure.logging import get_logger
from tools.communication.whatsapp.cloud_api_provider import WhatsAppCloudAPIProvider
from tools.communication.whatsapp.mock_provider import MockWhatsAppProvider
from tools.communication.whatsapp.models import (
    WhatsAppMessage,
    WhatsAppMessageStatus,
    WhatsAppSendResult,
)

logger = get_logger("communication.whatsapp.service")


class WhatsAppService:
    """Coordinates phone normalization, template selection, and Cloud API transmission."""

    def __init__(self, db: CommunicationDatabase | None = None) -> None:
        self.settings = get_settings()
        self.real_provider = WhatsAppCloudAPIProvider()
        self.mock_provider: MockWhatsAppProvider | None = None
        if db is not None:
            self.db = db
        elif os.getenv("PYTEST_CURRENT_TEST"):
            self.db = CommunicationDatabase(":memory:")
        else:
            self.db = get_communication_db()
        self._drafts: dict[str, WhatsAppMessage] = {}
        self._in_flight_drafts: set[str] = set()
        self._customer_windows: dict[str, datetime] = {}
        self._lock = threading.RLock()

    def record_inbound_interaction(
        self, phone: str, timestamp: datetime | None = None, message_text: str = ""
    ) -> None:
        """Record incoming customer interaction to open/refresh the 24-hour service window and track consent."""
        with self._lock:
            try:
                norm = self.normalize_phone_number(phone)
                self._customer_windows[norm] = timestamp or datetime.now(UTC)
                logger.info(f"Refreshed WhatsApp 24h customer service window for {norm}")

                # Process opt-in / opt-out keywords from incoming interaction
                txt_clean = message_text.strip().lower()
                if txt_clean in ("stop", "لغو", "unsubscribe", "خروج"):
                    self.db.revoke_consent(norm, reason="incoming_opt_out")
                elif txt_clean in ("start", "شروع", "subscribe", "عضویت"):
                    # Explicit opt-in only: ordinary greetings (سلام, hi, hello) do NOT grant marketing consent
                    self.db.record_consent(
                        norm,
                        status="OPTED_IN",
                        source="incoming_explicit_opt_in",
                        account_id=getattr(self.settings, "whatsapp_phone_number_id", "default")
                        or "default",
                        scope="whatsapp_messaging",
                    )
            except Exception as exc:
                logger.warning(f"Failed to record inbound interaction for '{phone}': {exc}")

    def is_within_customer_service_window(self, phone: str) -> bool:
        """Verify whether recipient is within the active 24-hour customer service window."""
        try:
            norm = self.normalize_phone_number(phone)
        except Exception:
            return False

        with self._lock:
            self_phone = getattr(self.settings, "whatsapp_self_phone_number", "")
            if self_phone:
                try:
                    if norm == self.normalize_phone_number(self_phone):
                        return True
                except Exception:
                    pass

            last_ts = self._customer_windows.get(norm)
            if not last_ts:
                return False
            delta = (datetime.now(UTC) - last_ts).total_seconds()
            return 0 <= delta <= 86400.0

    @property
    def provider(self) -> Any:
        return self.mock_provider if self.mock_provider is not None else self.real_provider

    def set_mock_provider(self, mock: MockWhatsAppProvider | None) -> None:
        self.mock_provider = mock

    def normalize_phone_number(self, phone: str) -> str:
        """Normalize phone string into canonical E.164 format (+[country_code][number])."""
        raw = phone.strip()
        # Remove spaces, parentheses, hyphens, dots
        cleaned = re.sub(r"[\s\(\)\-\.]+", "", raw)

        # Handle Persian / Arabic digits
        persian_digits = "۰۱۲۳۴۵۶۷۸۹"
        for i, pd in enumerate(persian_digits):
            cleaned = cleaned.replace(pd, str(i))

        # Check Iranian mobile national prefix (09... -> +989...)
        if cleaned.startswith("09") and len(cleaned) == 11:
            return f"+98{cleaned[1:]}"

        if cleaned.startswith("98") and len(cleaned) == 12 and not cleaned.startswith("+"):
            return f"+{cleaned}"

        if not cleaned.startswith("+"):
            # If 10 digits starting with non-zero, assume US/North America +1
            if len(cleaned) == 10:
                return f"+1{cleaned}"
            # Otherwise prepend +
            return f"+{cleaned}"

        return cleaned

    def validate_phone_number(self, phone: str) -> bool:
        """Verify normalized phone number conforms to E.164 requirements."""
        # E.164: + followed by 7 to 15 digits
        return bool(re.match(r"^\+[1-9]\d{6,14}$", phone))

    def resolve_recipient_phone(self, recipient_hint: str) -> str:
        """Resolve recipient hints such as 'خودم' or 'myself' to verified configuration."""
        hint_clean = recipient_hint.strip().lower()
        if hint_clean in ("خودم", "من", "myself", "me", "self"):
            configured_self = getattr(self.settings, "whatsapp_self_phone_number", "").strip()
            if not configured_self:
                raise ValueError(
                    "Self-recipient requested ('خودم'), but whatsapp_self_phone_number is not configured in settings."
                )
            normalized = self.normalize_phone_number(configured_self)
            if not self.validate_phone_number(normalized):
                raise ValueError(
                    f"Configured self-phone number '{configured_self}' is not a valid E.164 phone number."
                )
            return normalized

        normalized = self.normalize_phone_number(recipient_hint)
        if not self.validate_phone_number(normalized):
            raise ValueError(
                f"Invalid recipient phone number: '{recipient_hint}'. Please provide a valid international phone number."
            )
        return normalized

    def compose_draft(
        self,
        recipient: str,
        message_text: str,
        recipient_name: str | None = None,
        template_name: str | None = None,
        template_language: str = "en_US",
        template_components: list[dict[str, Any]] | None = None,
    ) -> WhatsAppMessage:
        """Validate recipient, construct WhatsAppMessage draft, and store for approval."""
        if not message_text.strip():
            raise ValueError("WhatsApp message text cannot be empty.")

        phone = self.resolve_recipient_phone(recipient)
        draft_id = f"wa_draft_{uuid.uuid4().hex[:8]}"

        msg = WhatsAppMessage(
            recipient_phone=phone,
            message_text=message_text.strip(),
            recipient_name=recipient_name,
            template_name=template_name,
            template_language=template_language,
            template_components=template_components or [],
            draft_id=draft_id,
        )
        self._drafts[draft_id] = msg
        logger.info(f"Composed WhatsApp draft '{draft_id}' to {phone}")
        return msg

    def get_draft(self, draft_id: str) -> WhatsAppMessage | None:
        return self._drafts.get(draft_id)

    def send_draft(self, draft_id: str) -> WhatsAppSendResult:
        """Send a previously composed and approved draft with duplicate prevention."""
        with self._lock:
            if draft_id in self._in_flight_drafts:
                logger.warning(f"Blocked duplicate send for in-flight WhatsApp draft '{draft_id}'.")
                return WhatsAppSendResult(
                    success=False,
                    status=WhatsAppMessageStatus.FAILED,
                    error=f"WhatsApp draft '{draft_id}' is already currently being sent. Duplicate send prevented.",
                )

            msg = self._drafts.get(draft_id)
            if not msg:
                return WhatsAppSendResult(
                    success=False,
                    status=WhatsAppMessageStatus.FAILED,
                    error=f"WhatsApp draft '{draft_id}' not found.",
                )

            # Recipient Consent Check: Ensure recipient has not explicitly opted out
            self_phone = getattr(self.settings, "whatsapp_self_phone_number", "")
            is_self = False
            if self_phone:
                with contextlib.suppress(Exception):
                    is_self = msg.recipient_phone == self.normalize_phone_number(self_phone)

            consent = self.db.get_consent_status(msg.recipient_phone)
            if consent and consent.get("consent_status") == "OPTED_OUT" and not is_self:
                return WhatsAppSendResult(
                    success=False,
                    status=WhatsAppMessageStatus.FAILED,
                    recipient_phone=msg.recipient_phone,
                    error=f"Message blocked: Recipient '{msg.recipient_phone}' has opted out of WhatsApp messages.",
                )

            if (
                getattr(self.settings, "whatsapp_enforce_24h_window", False)
                and not msg.template_name
                and not self.is_within_customer_service_window(msg.recipient_phone)
            ):
                return WhatsAppSendResult(
                    success=False,
                    status=WhatsAppMessageStatus.FAILED,
                    recipient_phone=msg.recipient_phone,
                    error=(
                        "Meta WhatsApp policy restriction: Free-form messages outside the 24-hour "
                        "customer service window require an approved template. Specify template_name "
                        "or wait for an incoming message."
                    ),
                )

            self._in_flight_drafts.add(draft_id)

        try:
            res = self.provider.send_message(msg)
            if res.success:
                with self._lock:
                    self._drafts.pop(draft_id, None)
                try:
                    self.db.save_delivery_record(
                        message_id=res.message_id or draft_id,
                        recipient_phone=msg.recipient_phone,
                        current_status=res.status.value,
                        sent_at=datetime.now(UTC).isoformat(),
                    )
                except Exception as exc:
                    logger.debug(f"Failed to persist delivery record in SQLite: {exc}")
            return res
        finally:
            with self._lock:
                self._in_flight_drafts.discard(draft_id)

    def get_status(self) -> dict[str, Any]:
        return self.provider.get_status()


_whatsapp_service_instance: WhatsAppService | None = None


def get_whatsapp_service() -> WhatsAppService:
    global _whatsapp_service_instance
    if _whatsapp_service_instance is None:
        _whatsapp_service_instance = WhatsAppService()
    return _whatsapp_service_instance
