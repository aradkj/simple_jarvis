"""Official Meta WhatsApp Business Cloud API Webhook Handler for JARVIS Phase 9.

Implements cryptographically verified delivery and read receipt processing:
- HMAC-SHA256 signature verification ('X-Hub-Signature-256').
- Webhook endpoint handshake verification ('hub.mode', 'hub.verify_token', 'hub.challenge').
- Independent tracking of 'sent', 'delivered', 'read', and 'failed' status transitions.
- Idempotent deduplication of repeated webhook payloads.
- Rejection of forged, untrusted, or out-of-order events.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from config import get_settings
from infrastructure.communication_db import CommunicationDatabase, get_communication_db
from infrastructure.logging import get_logger
from tools.communication.whatsapp.models import WhatsAppMessageStatus

logger = get_logger("communication.whatsapp.webhook")

# Valid lifecycle progression order for Meta WhatsApp messages
VALID_LIFECYCLE_ORDER: dict[WhatsAppMessageStatus, int] = {
    WhatsAppMessageStatus.DRAFTED: 0,
    WhatsAppMessageStatus.PENDING_APPROVAL: 1,
    WhatsAppMessageStatus.SUBMITTED: 2,
    WhatsAppMessageStatus.ACCEPTED: 3,
    WhatsAppMessageStatus.SENT: 4,
    WhatsAppMessageStatus.DELIVERED: 5,
    WhatsAppMessageStatus.READ: 6,
    WhatsAppMessageStatus.FAILED: 99,
}


@dataclass
class WebhookStatusUpdate:
    """Individual status change parsed from a verified webhook notification."""

    message_id: str
    recipient_id: str
    status: WhatsAppMessageStatus
    timestamp: datetime
    raw_status_string: str
    error_code: int | None = None
    error_title: str | None = None


@dataclass
class MessageDeliveryRecord:
    """Persistent lifecycle state for an outbound WhatsApp message."""

    message_id: str
    recipient_phone: str
    current_status: WhatsAppMessageStatus
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    sent_at: datetime | None = None
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    error_details: dict[str, Any] = field(default_factory=dict)


class WhatsAppWebhookHandler:
    """Handles verification, security validation, and status updates from Meta Webhooks."""

    def __init__(
        self,
        app_secret: str | None = None,
        verify_token: str | None = None,
        db: CommunicationDatabase | None = None,
    ) -> None:
        self.settings = get_settings()
        self.app_secret = (app_secret or "").strip()
        self.verify_token = (verify_token or "jarvis_wa_webhook_token").strip()
        if db is not None:
            self.db = db
        elif os.getenv("PYTEST_CURRENT_TEST"):
            self.db = CommunicationDatabase(":memory:")
        else:
            self.db = get_communication_db()

        # Bounded cache of processed event IDs to prevent duplicate webhook processing
        self._processed_event_ids: dict[str, float] = {}
        # Track message status by message_id
        self._message_records: dict[str, MessageDeliveryRecord] = {}
        self._lock = threading.RLock()

    def verify_signature(self, payload_bytes: bytes, signature_header: str | None) -> bool:
        """Verify HMAC-SHA256 signature in X-Hub-Signature-256 against configured app_secret.

        Format: 'sha256=<hex_digest>'
        """
        if not self.app_secret:
            logger.warning("WhatsApp App Secret is not configured; rejecting webhook verification.")
            return False

        if not signature_header or not signature_header.startswith("sha256="):
            logger.warning("Missing or malformed X-Hub-Signature-256 header.")
            return False

        expected_sig = signature_header[7:].strip()
        computed_sig = hmac.new(
            self.app_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

        # Constant-time comparison to prevent timing attacks
        is_valid = hmac.compare_digest(computed_sig.lower(), expected_sig.lower())
        if not is_valid:
            logger.error("X-Hub-Signature-256 verification failed; rejecting forged webhook event.")
        return is_valid

    def handle_verification(
        self, mode: str | None, token: str | None, challenge: str | None
    ) -> str | None:
        """Handle Meta Webhook challenge handshake."""
        if mode == "subscribe" and token == self.verify_token and challenge:
            logger.info("WhatsApp webhook handshake challenge successfully verified.")
            return challenge
        logger.warning(
            f"Webhook verification failed: mode={mode}, token_matches={token == self.verify_token}"
        )
        return None

    def register_outbound_message(self, message_id: str, recipient_phone: str) -> None:
        """Register newly accepted outbound message before external webhook notifications arrive."""
        with self._lock:
            self._message_records[message_id] = MessageDeliveryRecord(
                message_id=message_id,
                recipient_phone=recipient_phone,
                current_status=WhatsAppMessageStatus.ACCEPTED,
            )

    def process_webhook_payload(
        self,
        payload: dict[str, Any],
        raw_bytes: bytes | None = None,
        signature_header: str | None = None,
    ) -> list[WebhookStatusUpdate]:
        """Validate, deduplicate, and process incoming Meta Webhook payload."""
        # 1. Signature check if signature and raw bytes are provided
        if (
            raw_bytes is not None
            and signature_header is not None
            and not self.verify_signature(raw_bytes, signature_header)
        ):
            raise PermissionError("Invalid X-Hub-Signature-256 signature.")

        # 2. Extract entries and changes
        updates: list[WebhookStatusUpdate] = []
        entries = payload.get("entry", [])
        if not isinstance(entries, list):
            return updates

        now_mono = time.monotonic()
        with self._lock:
            # Clean up old processed events (> 24 hours)
            cutoff = now_mono - 86400.0
            self._processed_event_ids = {
                k: t for k, t in self._processed_event_ids.items() if t > cutoff
            }

            configured_phone_id = getattr(self.settings, "whatsapp_phone_number_id", "")
            for entry in entries:
                changes = entry.get("changes", [])
                for change in changes:
                    val = change.get("value", {})

                    # Business Account Ownership Check
                    if configured_phone_id:
                        meta = val.get("metadata", {})
                        phone_id = meta.get("phone_number_id")
                        if phone_id and phone_id != configured_phone_id:
                            logger.error(
                                f"Webhook business account ownership violation: phone_number_id '{phone_id}' "
                                f"does not match configured '{configured_phone_id}'."
                            )
                            raise PermissionError(
                                "Webhook payload belongs to an unauthorized business account ID."
                            )

                    statuses = val.get("statuses", [])
                    for st in statuses:
                        msg_id = st.get("id")
                        status_str = st.get("status")
                        recipient_id = st.get("recipient_id", "")
                        timestamp_str = st.get("timestamp")

                        if not msg_id or not status_str:
                            continue

                        # Deduplicate repeated webhook events across memory and durable SQLite
                        event_dedup_key = f"{msg_id}:{status_str}:{timestamp_str}"
                        if (
                            event_dedup_key in self._processed_event_ids
                            or self.db.is_webhook_event_processed(event_dedup_key)
                        ):
                            logger.debug(f"Ignoring duplicate webhook event: {event_dedup_key}")
                            continue
                        self._processed_event_ids[event_dedup_key] = now_mono
                        try:
                            self.db.record_webhook_event(
                                event_dedup_key,
                                payload_hash=hashlib.sha256(event_dedup_key.encode()).hexdigest(),
                            )
                        except Exception as exc:
                            logger.debug(f"Failed to record webhook event in SQLite: {exc}")

                        parsed_status = self._parse_status_string(status_str)
                        ts = (
                            datetime.fromtimestamp(int(timestamp_str), UTC)
                            if timestamp_str
                            else datetime.now(UTC)
                        )

                        err_code = None
                        err_title = None
                        errors = st.get("errors", [])
                        if errors and isinstance(errors, list):
                            err_code = errors[0].get("code")
                            err_title = errors[0].get("title") or errors[0].get("message")

                        update = WebhookStatusUpdate(
                            message_id=msg_id,
                            recipient_id=recipient_id,
                            status=parsed_status,
                            timestamp=ts,
                            raw_status_string=status_str,
                            error_code=err_code,
                            error_title=err_title,
                        )
                        self._apply_status_transition(update)
                        updates.append(update)

                    # Inbound messages from users (resets/opens 24-hour customer service window)
                    incoming_messages = val.get("messages", [])
                    for inc in incoming_messages:
                        sender_phone = inc.get("from")
                        if sender_phone:
                            ts_str = inc.get("timestamp")
                            body_text = ""
                            if inc.get("type") == "text":
                                body_text = inc.get("text", {}).get("body", "")
                            try:
                                inc_ts = (
                                    datetime.fromtimestamp(int(ts_str), UTC)
                                    if ts_str
                                    else datetime.now(UTC)
                                )
                            except Exception:
                                inc_ts = datetime.now(UTC)
                            try:
                                from tools.communication.whatsapp.whatsapp_service import (
                                    get_whatsapp_service,
                                )

                                get_whatsapp_service().record_inbound_interaction(
                                    sender_phone, inc_ts, message_text=body_text
                                )
                            except Exception as exc:
                                logger.warning(
                                    f"Failed to record customer interaction for {sender_phone}: {exc}"
                                )

        return updates

    def _parse_status_string(self, raw: str) -> WhatsAppMessageStatus:
        s = raw.lower().strip()
        if s == "sent":
            return WhatsAppMessageStatus.SENT
        if s == "delivered":
            return WhatsAppMessageStatus.DELIVERED
        if s == "read":
            return WhatsAppMessageStatus.READ
        if s == "failed":
            return WhatsAppMessageStatus.FAILED
        return WhatsAppMessageStatus.UNKNOWN

    def _apply_status_transition(self, update: WebhookStatusUpdate) -> None:
        """Apply strictly valid lifecycle transitions, rejecting out-of-order regressions."""
        rec = self._message_records.get(update.message_id)
        if not rec:
            rec = MessageDeliveryRecord(
                message_id=update.message_id,
                recipient_phone=update.recipient_id,
                current_status=WhatsAppMessageStatus.ACCEPTED,
            )
            self._message_records[update.message_id] = rec

        current_rank = VALID_LIFECYCLE_ORDER.get(rec.current_status, 0)
        new_rank = VALID_LIFECYCLE_ORDER.get(update.status, 0)

        # Failure overrides normal progression
        if update.status == WhatsAppMessageStatus.FAILED:
            rec.current_status = WhatsAppMessageStatus.FAILED
            rec.updated_at = update.timestamp
            rec.error_details = {
                "error_code": update.error_code,
                "error_title": update.error_title,
            }
            logger.warning(
                f"WhatsApp message {update.message_id} FAILED: code {update.error_code} - {update.error_title}"
            )
            self._persist_record_to_db(rec)
            return

        # Reject regressions (e.g. from read back to sent)
        if new_rank > current_rank:
            rec.current_status = update.status
            rec.updated_at = update.timestamp
            if update.status == WhatsAppMessageStatus.SENT:
                rec.sent_at = update.timestamp
            elif update.status == WhatsAppMessageStatus.DELIVERED:
                rec.delivered_at = update.timestamp
            elif update.status == WhatsAppMessageStatus.READ:
                rec.read_at = update.timestamp
            logger.info(
                f"WhatsApp message {update.message_id} status transitioned: {rec.current_status.value}"
            )
            self._persist_record_to_db(rec)

    def _persist_record_to_db(self, rec: MessageDeliveryRecord) -> None:
        try:
            self.db.save_delivery_record(
                message_id=rec.message_id,
                recipient_phone=rec.recipient_phone,
                current_status=rec.current_status.value,
                created_at=rec.created_at.isoformat(),
                updated_at=rec.updated_at.isoformat(),
                sent_at=rec.sent_at.isoformat() if rec.sent_at else None,
                delivered_at=rec.delivered_at.isoformat() if rec.delivered_at else None,
                read_at=rec.read_at.isoformat() if rec.read_at else None,
                error_details=rec.error_details,
            )
        except Exception as exc:
            logger.debug(f"Failed to persist delivery record in SQLite: {exc}")

    def get_message_record(self, message_id: str) -> MessageDeliveryRecord | None:
        """Query delivery record for a specific message ID, hydrating from SQLite if needed."""
        with self._lock:
            rec = self._message_records.get(message_id)
            if rec:
                return rec

            db_row = self.db.get_delivery_record(message_id)
            if db_row:
                try:
                    status_enum = self._parse_status_string(db_row["current_status"])
                    rec = MessageDeliveryRecord(
                        message_id=db_row["message_id"],
                        recipient_phone=db_row["recipient_phone"],
                        current_status=status_enum,
                        created_at=datetime.fromisoformat(db_row["created_at"]),
                        updated_at=datetime.fromisoformat(db_row["updated_at"]),
                        sent_at=datetime.fromisoformat(db_row["sent_at"])
                        if db_row.get("sent_at")
                        else None,
                        delivered_at=datetime.fromisoformat(db_row["delivered_at"])
                        if db_row.get("delivered_at")
                        else None,
                        read_at=datetime.fromisoformat(db_row["read_at"])
                        if db_row.get("read_at")
                        else None,
                        error_details=db_row.get("error_details") or {},
                    )
                    self._message_records[message_id] = rec
                    return rec
                except Exception as exc:
                    logger.debug(f"Failed to hydrate delivery record: {exc}")
            return None

    def get_status(self) -> dict[str, Any]:
        """Return diagnostic webhook handler state."""
        with self._lock:
            return {
                "app_secret_configured": bool(self.app_secret),
                "verify_token_configured": bool(self.verify_token),
                "tracked_messages_count": len(self._message_records),
                "cached_event_count": len(self._processed_event_ids),
            }
