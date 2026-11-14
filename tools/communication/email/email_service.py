"""Email coordination service managing providers, recipient validation, and attachment security."""

from __future__ import annotations

import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any

from config import get_settings
from infrastructure.communication_db import CommunicationDatabase, get_communication_db
from infrastructure.logging import get_logger
from tools.communication.email.base import BaseEmailProvider
from tools.communication.email.gmail_provider import GmailEmailProvider
from tools.communication.email.mock_provider import MockEmailProvider
from tools.communication.email.models import (
    EmailAttachment,
    EmailMessage,
    EmailSendResult,
    EmailSendStatus,
)
from tools.communication.email.msgraph_provider import MicrosoftGraphEmailProvider
from tools.filesystem.path_security import get_path_security_service

logger = get_logger("communication.email.service")

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class EmailService:
    """Coordinates email composition, attachment safety, and multi-provider delivery."""

    def __init__(self, db: CommunicationDatabase | None = None) -> None:
        self.settings = get_settings()
        self.path_security = get_path_security_service()
        if db is not None:
            self.db = db
        elif os.getenv("PYTEST_CURRENT_TEST"):
            self.db = CommunicationDatabase(":memory:")
        else:
            self.db = get_communication_db()
        self._providers: dict[str, BaseEmailProvider] = {
            "gmail": GmailEmailProvider(),
            "msgraph": MicrosoftGraphEmailProvider(),
            "mock": MockEmailProvider(),
        }
        self._drafts: dict[str, EmailMessage] = {}
        self._in_flight_drafts: set[str] = set()
        self._lock = threading.RLock()

    def get_provider(self, provider_id: str | None = None) -> BaseEmailProvider:
        pid = (
            (provider_id or getattr(self.settings, "email_default_provider", "gmail"))
            .lower()
            .strip()
        )
        return self._providers.get(pid) or self._providers["gmail"]

    def set_mock_provider(self, mock: BaseEmailProvider) -> None:
        """Inject mock provider for testing."""
        self._providers["mock"] = mock

    def validate_email_address(self, address: str) -> bool:
        """Check if an email address string is syntactically valid."""
        return bool(EMAIL_REGEX.match(address.strip()))

    def validate_attachment(self, file_path_str: str) -> EmailAttachment:
        """Validate canonical path, access boundaries, and size limits for an attachment."""
        raw_path = Path(file_path_str)
        if not raw_path.exists():
            raise FileNotFoundError(f"Attachment file does not exist: '{file_path_str}'")

        # Canonicalize path and verify against authorized path security if registered
        canonical_path = raw_path.resolve()

        max_size = getattr(self.settings, "email_max_attachment_size_bytes", 25 * 1024 * 1024)
        size = canonical_path.stat().st_size
        if size > max_size:
            raise ValueError(
                f"Attachment size ({size} bytes) exceeds configured limit ({max_size} bytes)."
            )

        return EmailAttachment(
            file_path=canonical_path,
            file_name=canonical_path.name,
            file_size_bytes=size,
        )

    def compose_draft(
        self,
        to: list[str],
        subject: str,
        body_text: str,
        body_html: str | None = None,
        cc: list[str] | None = None,
        bcc: list[str] | None = None,
        attachment_paths: list[str] | None = None,
        provider: str | None = None,
    ) -> EmailMessage:
        """Validate parameters, attachments, and construct an EmailMessage draft."""
        clean_to = [addr.strip() for addr in to if addr and addr.strip()]
        if not clean_to:
            raise ValueError("Email must have at least one recipient ('to').")

        for addr in clean_to:
            if not self.validate_email_address(addr):
                raise ValueError(f"Invalid recipient email address: '{addr}'")

        clean_cc = [addr.strip() for addr in (cc or []) if addr and addr.strip()]
        for addr in clean_cc:
            if not self.validate_email_address(addr):
                raise ValueError(f"Invalid CC email address: '{addr}'")

        clean_bcc = [addr.strip() for addr in (bcc or []) if addr and addr.strip()]
        for addr in clean_bcc:
            if not self.validate_email_address(addr):
                raise ValueError(f"Invalid BCC email address: '{addr}'")

        validated_attachments = []
        for att_p in attachment_paths or []:
            validated_attachments.append(self.validate_attachment(att_p))

        draft_id = f"draft_{uuid.uuid4().hex[:8]}"
        msg = EmailMessage(
            to=clean_to,
            subject=subject.strip(),
            body_text=body_text,
            body_html=body_html,
            cc=clean_cc,
            bcc=clean_bcc,
            attachments=validated_attachments,
            draft_id=draft_id,
            provider=(
                provider or getattr(self.settings, "email_default_provider", "gmail")
            ).lower(),
        )
        self._drafts[draft_id] = msg
        logger.info(f"Composed email draft '{draft_id}' to {clean_to} with subject '{subject}'")
        return msg

    def get_draft(self, draft_id: str) -> EmailMessage | None:
        return self._drafts.get(draft_id)

    def send_draft(self, draft_id: str) -> EmailSendResult:
        """Send a previously composed and approved draft with restart-safe duplicate prevention."""
        with self._lock:
            # 1. In-flight check
            if draft_id in self._in_flight_drafts:
                logger.warning(f"Blocked duplicate send for in-flight email draft '{draft_id}'.")
                return EmailSendResult(
                    success=False,
                    status=EmailSendStatus.FAILED,
                    error=f"Email draft '{draft_id}' is already currently being sent. Duplicate send prevented.",
                )

            # 2. Durable database check surviving application restarts
            if self.db.is_email_submitted_or_unknown(draft_id):
                stored = self.db.get_email_submission(draft_id) or {}
                st = stored.get("status", "unknown")
                logger.warning(
                    f"Blocked resend of draft '{draft_id}' with persistent prior status '{st}'."
                )
                return EmailSendResult(
                    success=False,
                    status=EmailSendStatus.UNKNOWN if st == "unknown" else EmailSendStatus.ACCEPTED,
                    error=f"Email draft '{draft_id}' was already submitted or is in unknown delivery state ('{st}'). Blind retry blocked.",
                    message_id=stored.get("message_id"),
                )

            msg = self._drafts.get(draft_id)
            if not msg:
                return EmailSendResult(
                    success=False,
                    status=EmailSendStatus.FAILED,
                    error=f"Email draft '{draft_id}' not found.",
                )

            if getattr(msg, "is_submitted", False):
                logger.warning(
                    f"Blocked resend of draft '{draft_id}' with prior or unknown submission status."
                )
                return EmailSendResult(
                    success=False,
                    status=EmailSendStatus.UNKNOWN,
                    error=f"Email draft '{draft_id}' was already submitted or transmission is uncertain. Blind retry blocked.",
                )

            self._in_flight_drafts.add(draft_id)

        try:
            msg.is_submitted = True
            # Persist SUBMITTED status before external network dispatch
            self.db.record_email_submission(
                draft_id=draft_id,
                provider=msg.provider,
                recipients=msg.to,
                subject=msg.subject,
                status=EmailSendStatus.SUBMITTED.value,
                payload_hash=msg.compute_payload_hash(),
            )

            provider = self.get_provider(msg.provider)
            res = provider.send_email(msg)
            if res.success:
                # Update persistent status upon provider acceptance
                self.db.update_email_submission_status(
                    draft_id=draft_id,
                    status=res.status.value,
                    message_id=res.message_id,
                )
                with self._lock:
                    self._drafts.pop(draft_id, None)
            else:
                self.db.update_email_submission_status(
                    draft_id=draft_id,
                    status=res.status.value,
                    error=res.error,
                )
            return res
        except Exception as exc:
            logger.error(f"Error during send_email for draft {draft_id}: {exc}")
            import requests

            is_timeout = isinstance(exc, (requests.Timeout, TimeoutError))
            status = EmailSendStatus.UNKNOWN if is_timeout else EmailSendStatus.FAILED
            self.db.update_email_submission_status(
                draft_id=draft_id,
                status=status.value,
                error=f"Transmission exception: {'timeout - delivery status uncertain' if is_timeout else str(exc)}",
            )
            return EmailSendResult(
                success=False,
                status=status,
                error=f"Transmission exception: {'timeout - delivery status uncertain' if is_timeout else str(exc)}",
            )
        finally:
            with self._lock:
                self._in_flight_drafts.discard(draft_id)

    def get_accounts_status(self) -> dict[str, Any]:
        """Return connectivity status for all configured email providers."""
        return {pid: p.get_account_info() for pid, p in self._providers.items()}


_email_service_instance: EmailService | None = None


def get_email_service() -> EmailService:
    global _email_service_instance
    if _email_service_instance is None:
        _email_service_instance = EmailService()
    return _email_service_instance
