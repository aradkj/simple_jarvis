"""Durable SQLite storage for WhatsApp consent, webhook events, and delivery records.

Preserves communication state, recipient consent choices (opt-in/opt-out with timestamps),
and idempotent webhook deduplication across application and process restarts.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from infrastructure.logging import get_logger
from infrastructure.paths import get_data_dir

logger = get_logger("infrastructure.communication_db")


DELIVERY_STATE_RANK: dict[str, int] = {
    "drafted": 0,
    "pending_approval": 1,
    "submitted": 2,
    "accepted": 3,
    "sent": 4,
    "delivered": 5,
    "read": 6,
    "failed": 99,
    "unknown": -1,
}


class CommunicationDatabase:
    """Thread-safe persistent SQLite store for communication consent and delivery lifecycle."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            self.db_path = get_data_dir() / "communication.sqlite3"
        elif str(db_path) == ":memory:":
            self.db_path = ":memory:"
        else:
            self.db_path = Path(db_path)

        self._lock = threading.RLock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self.db_path == ":memory:":
            if not hasattr(self, "_memory_conn"):
                self._memory_conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._memory_conn.row_factory = sqlite3.Row
            return self._memory_conn
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        """Create tables and indexes if not already present."""
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    # 1. WhatsApp Recipient Consent Table
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS whatsapp_recipient_consent (
                            recipient_phone TEXT PRIMARY KEY,
                            consent_status TEXT NOT NULL,
                            consent_timestamp TEXT NOT NULL,
                            consent_source TEXT NOT NULL,
                            revoked_at TEXT,
                            account_id TEXT DEFAULT 'default',
                            scope TEXT DEFAULT 'whatsapp_messaging'
                        );
                        """
                    )
                    with contextlib.suppress(sqlite3.OperationalError):
                        conn.execute(
                            "ALTER TABLE whatsapp_recipient_consent ADD COLUMN account_id TEXT DEFAULT 'default';"
                        )
                    with contextlib.suppress(sqlite3.OperationalError):
                        conn.execute(
                            "ALTER TABLE whatsapp_recipient_consent ADD COLUMN scope TEXT DEFAULT 'whatsapp_messaging';"
                        )

                    # 2. WhatsApp Webhook Events Deduplication Table
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS whatsapp_webhook_events (
                            event_id TEXT PRIMARY KEY,
                            received_at TEXT NOT NULL,
                            payload_hash TEXT NOT NULL
                        );
                        """
                    )

                    # 3. WhatsApp Message Delivery Records
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS whatsapp_delivery_records (
                            message_id TEXT PRIMARY KEY,
                            recipient_phone TEXT NOT NULL,
                            current_status TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            sent_at TEXT,
                            delivered_at TEXT,
                            read_at TEXT,
                            error_details TEXT
                        );
                        """
                    )

                    # 4. Email Outbound Submission Persistence Records
                    conn.execute(
                        """
                        CREATE TABLE IF NOT EXISTS email_submission_records (
                            draft_id TEXT PRIMARY KEY,
                            provider TEXT NOT NULL,
                            recipients TEXT NOT NULL,
                            subject TEXT NOT NULL,
                            status TEXT NOT NULL,
                            payload_hash TEXT NOT NULL,
                            submitted_at TEXT NOT NULL,
                            updated_at TEXT NOT NULL,
                            message_id TEXT,
                            error TEXT
                        );
                        """
                    )
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    # --- WhatsApp Recipient Consent ---

    def record_consent(
        self,
        phone: str,
        status: str = "OPTED_IN",
        source: str = "user_direct",
        account_id: str = "default",
        scope: str = "whatsapp_messaging",
        timestamp: datetime | None = None,
    ) -> None:
        """Record explicit recipient consent (e.g. OPTED_IN or OPTED_OUT)."""
        now_iso = (timestamp or datetime.now(UTC)).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO whatsapp_recipient_consent
                        (recipient_phone, consent_status, consent_timestamp, consent_source, revoked_at, account_id, scope)
                        VALUES (?, ?, ?, ?, NULL, ?, ?)
                        ON CONFLICT(recipient_phone) DO UPDATE SET
                            consent_status = excluded.consent_status,
                            consent_timestamp = excluded.consent_timestamp,
                            consent_source = excluded.consent_source,
                            account_id = excluded.account_id,
                            scope = excluded.scope,
                            revoked_at = NULL;
                        """,
                        (phone, status.upper(), now_iso, source, account_id, scope),
                    )
                logger.info(
                    f"Recorded consent for {phone}: status={status}, source={source}, account={account_id}"
                )
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    def revoke_consent(
        self, phone: str, reason: str = "opt_out_command", timestamp: datetime | None = None
    ) -> None:
        """Revoke recipient consent."""
        now_iso = (timestamp or datetime.now(UTC)).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO whatsapp_recipient_consent
                        (recipient_phone, consent_status, consent_timestamp, consent_source, revoked_at)
                        VALUES (?, 'OPTED_OUT', ?, ?, ?)
                        ON CONFLICT(recipient_phone) DO UPDATE SET
                            consent_status = 'OPTED_OUT',
                            revoked_at = excluded.revoked_at,
                            consent_source = excluded.consent_source;
                        """,
                        (phone, now_iso, reason, now_iso),
                    )
                logger.info(f"Revoked consent for {phone}: reason={reason}")
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    def get_consent_status(self, phone: str) -> dict[str, Any] | None:
        """Retrieve stored consent record for recipient phone."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM whatsapp_recipient_consent WHERE recipient_phone = ?",
                    (phone,),
                )
                row = cursor.fetchone()
                if row:
                    return dict(row)
                return None
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    def is_consent_granted(self, phone: str) -> bool:
        """Check whether recipient currently holds valid active opt-in consent."""
        record = self.get_consent_status(phone)
        if not record:
            return False
        return str(record.get("consent_status", "")).upper() == "OPTED_IN"

    def list_consents(self) -> list[dict[str, Any]]:
        """List all recipient consent records."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM whatsapp_recipient_consent ORDER BY consent_timestamp DESC"
                )
                return [dict(row) for row in cursor.fetchall()]
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    # --- Webhook Event Deduplication ---

    def record_webhook_event(self, event_id: str, payload_hash: str) -> bool:
        """Persist webhook event ID. Returns False if event was already processed (duplicate)."""
        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    cursor = conn.execute(
                        "INSERT OR IGNORE INTO whatsapp_webhook_events (event_id, received_at, payload_hash) VALUES (?, ?, ?)",
                        (event_id, now_iso, payload_hash),
                    )
                    return cursor.rowcount > 0
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    def is_webhook_event_processed(self, event_id: str) -> bool:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT 1 FROM whatsapp_webhook_events WHERE event_id = ?",
                    (event_id,),
                )
                return cursor.fetchone() is not None
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    # --- WhatsApp Delivery Records ---

    def save_delivery_record(
        self,
        message_id: str,
        recipient_phone: str,
        current_status: str,
        created_at: str | None = None,
        updated_at: str | None = None,
        sent_at: str | None = None,
        delivered_at: str | None = None,
        read_at: str | None = None,
        error_details: dict[str, Any] | None = None,
    ) -> None:
        """Persist or update delivery record across restarts."""
        now_iso = datetime.now(UTC).isoformat()
        c_at = created_at or now_iso
        u_at = updated_at or now_iso
        err_json = json.dumps(error_details or {})

        with self._lock:
            conn = self._get_connection()
            try:
                # Monotonic status check: prevent regression or overwriting confirmed states with 'unknown'
                cursor = conn.execute(
                    "SELECT current_status FROM whatsapp_delivery_records WHERE message_id = ?",
                    (message_id,),
                )
                existing = cursor.fetchone()
                effective_status = current_status
                if existing:
                    existing_status = str(existing["current_status"]).lower()
                    new_status = current_status.lower()
                    # UNKNOWN does not overwrite any confirmed forward status
                    if (
                        new_status == "unknown"
                        and existing_status != "unknown"
                        or (
                            DELIVERY_STATE_RANK.get(new_status, 0)
                            < DELIVERY_STATE_RANK.get(existing_status, 0)
                            and existing_status != "unknown"
                        )
                    ):
                        effective_status = existing_status

                with conn:
                    conn.execute(
                        """
                        INSERT INTO whatsapp_delivery_records
                        (message_id, recipient_phone, current_status, created_at, updated_at, sent_at, delivered_at, read_at, error_details)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(message_id) DO UPDATE SET
                            current_status = excluded.current_status,
                            updated_at = excluded.updated_at,
                            sent_at = COALESCE(excluded.sent_at, whatsapp_delivery_records.sent_at),
                            delivered_at = COALESCE(excluded.delivered_at, whatsapp_delivery_records.delivered_at),
                            read_at = COALESCE(excluded.read_at, whatsapp_delivery_records.read_at),
                            error_details = excluded.error_details;
                        """,
                        (
                            message_id,
                            recipient_phone,
                            effective_status,
                            c_at,
                            u_at,
                            sent_at,
                            delivered_at,
                            read_at,
                            err_json,
                        ),
                    )
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    def get_delivery_record(self, message_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM whatsapp_delivery_records WHERE message_id = ?",
                    (message_id,),
                )
                row = cursor.fetchone()
                if row:
                    res = dict(row)
                    if res.get("error_details"):
                        with contextlib.suppress(Exception):
                            res["error_details"] = json.loads(res["error_details"])
                    return res
                return None
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    def list_delivery_records(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM whatsapp_delivery_records ORDER BY updated_at DESC LIMIT ?",
                    (limit,),
                )
                records = []
                for row in cursor.fetchall():
                    rec = dict(row)
                    if rec.get("error_details"):
                        with contextlib.suppress(Exception):
                            rec["error_details"] = json.loads(rec["error_details"])
                    records.append(rec)
                return records
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    # --- Email Outbound Submission Persistence ---

    def record_email_submission(
        self,
        draft_id: str,
        provider: str,
        recipients: list[str] | str,
        subject: str,
        status: str,
        payload_hash: str,
        message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Persist newly submitted email draft across application restarts."""
        now_iso = datetime.now(UTC).isoformat()
        recipients_str = (
            ",".join(sorted(recipients)) if isinstance(recipients, list) else str(recipients)
        )
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        INSERT INTO email_submission_records
                        (draft_id, provider, recipients, subject, status, payload_hash, submitted_at, updated_at, message_id, error)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(draft_id) DO UPDATE SET
                            status = excluded.status,
                            updated_at = excluded.updated_at,
                            message_id = COALESCE(excluded.message_id, email_submission_records.message_id),
                            error = excluded.error;
                        """,
                        (
                            draft_id,
                            provider.lower(),
                            recipients_str,
                            subject,
                            status.lower(),
                            payload_hash,
                            now_iso,
                            now_iso,
                            message_id,
                            error,
                        ),
                    )
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    def update_email_submission_status(
        self,
        draft_id: str,
        status: str,
        message_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Update existing email submission status."""
        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._get_connection()
            try:
                with conn:
                    conn.execute(
                        """
                        UPDATE email_submission_records
                        SET status = ?, updated_at = ?, message_id = COALESCE(?, message_id), error = ?
                        WHERE draft_id = ?;
                        """,
                        (status.lower(), now_iso, message_id, error, draft_id),
                    )
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    def get_email_submission(self, draft_id: str) -> dict[str, Any] | None:
        """Retrieve stored email submission record by draft_id."""
        with self._lock:
            conn = self._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT * FROM email_submission_records WHERE draft_id = ?",
                    (draft_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None
            finally:
                if self.db_path != ":memory:":
                    conn.close()

    def is_email_submitted_or_unknown(self, draft_id: str) -> bool:
        """Check whether draft has already been submitted or is in unknown/in-flight status."""
        rec = self.get_email_submission(draft_id)
        if not rec:
            return False
        st = rec.get("status", "").lower()
        return st in ("submitted", "accepted", "delivery_confirmed", "unknown")


_communication_db_instance: CommunicationDatabase | None = None


def get_communication_db() -> CommunicationDatabase:
    """Singleton provider for CommunicationDatabase."""
    global _communication_db_instance
    if _communication_db_instance is None:
        _communication_db_instance = CommunicationDatabase()
    return _communication_db_instance
