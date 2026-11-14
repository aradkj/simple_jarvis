"""Comprehensive Phase 9 Final Evidence Closure & Defect Remediation Tests.

Verifies:
1. Azure British Voice Identifiers per Microsoft official catalog.
2. Persian NLU missing information detection & follow-up safety.
3. Approval Record Integrity (TrustedApprovalStore, disk byte tampering, account/recipient substitution, replay prevention).
4. WhatsApp consent non-marketing greetings & webhook business account ownership.
5. Email submission persistence across restart and timeout UNKNOWN deduplication.
6. Desktop authorization scoping under Strict Default-Deny.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from pydantic import SecretStr

from config import Settings
from core.approval import TrustedApprovalStore
from core.personality import JarvisPersonalityEngine
from infrastructure.communication_db import CommunicationDatabase
from memory.base import ConversationMessage
from tools.communication.email.email_service import EmailService
from tools.communication.email.mock_provider import MockEmailProvider
from tools.communication.whatsapp.whatsapp_service import WhatsAppService
from tools.communication.whatsapp.whatsapp_webhook import WhatsAppWebhookHandler
from tools.filesystem.path_security import PathSecurityService
from tools.voice.tts_service import BritishNeuralTTSService

# ==============================================================================
# 1. Azure British Voice Identifiers
# ==============================================================================


def test_azure_british_voice_catalog_identifiers() -> None:
    """Verify configured British English voice identifiers conform to official Microsoft catalog."""
    settings = Settings(voice_british_voice="en-GB-OliverNeural")
    assert settings.voice_british_voice == "en-GB-OliverNeural"

    with patch("tools.voice.tts_service.get_settings", return_value=settings):
        service = BritishNeuralTTSService(preferred_voice="en-GB-OliverNeural")
        voices = service.get_available_voices()
        assert any("en-GB-OliverNeural" in v for v in voices)
        assert any("en-GB-Ryan:DragonHDLatestNeural" in v for v in voices)
        assert any("en-GB-RyanNeural" in v for v in voices)


# ==============================================================================
# 2. Persian NLU — Missing Information and Follow-up Safety
# ==============================================================================


def test_persian_nlu_vague_edit_requires_clarification() -> None:
    """If user says 'ویرایشش کن' or 'edit it' without instructions, require clarification."""
    resolved, inferred = JarvisPersonalityEngine.resolve_references("ویرایشش کن", [])
    assert inferred.get("needs_clarification") is True
    assert inferred.get("clarification_reason") == "missing_modification_details"
    assert "چه تغییری" in inferred.get("clarification_prompt", "")

    spoken = JarvisPersonalityEngine.format_spoken_response_en(
        inferred["clarification_prompt"], "ویرایشش کن"
    )
    assert "What modification would you like me to make to the file?" in spoken


def test_persian_nlu_email_without_details_requires_clarification() -> None:
    """If user asks to send an email without subject or body, require clarification."""
    resolved, inferred = JarvisPersonalityEngine.resolve_references(
        "یک ایمیل به contact@acme.com بفرست", []
    )
    assert inferred.get("needs_clarification") is True
    assert inferred.get("clarification_reason") == "missing_email_details"
    assert "موضوع و متن ایمیل" in inferred.get("clarification_prompt", "")

    spoken = JarvisPersonalityEngine.format_spoken_response_en(
        inferred["clarification_prompt"], "یک ایمیل به contact@acme.com بفرست"
    )
    assert "provide the subject and body of the email" in spoken


def test_persian_nlu_whatsapp_without_content_requires_clarification() -> None:
    """If user asks to send a WhatsApp message without message content, require clarification."""
    resolved, inferred = JarvisPersonalityEngine.resolve_references(
        "در واتساپ به شماره 09121112233 پیام بده", []
    )
    assert inferred.get("needs_clarification") is True
    assert inferred.get("clarification_reason") == "missing_whatsapp_content"
    assert "متن پیام" in inferred.get("clarification_prompt", "")

    spoken = JarvisPersonalityEngine.format_spoken_response_en(
        inferred["clarification_prompt"], "در واتساپ به شماره 09121112233 پیام بده"
    )
    assert "What message content would you like me to send" in spoken


def test_persian_nlu_ambiguous_recipient_requires_clarification() -> None:
    """If multiple recipients are present in context, require clarification."""
    history = [
        ConversationMessage(role="user", content="با علی و سارا صحبت کردم", session_id="s1"),
        ConversationMessage(
            role="assistant", content="درود. جلسه علی و سارا ثبت شد.", session_id="s1"
        ),
    ]
    resolved, inferred = JarvisPersonalityEngine.resolve_references("بهش پیام بده", history)
    assert inferred.get("ambiguous_recipient") is True
    assert inferred.get("needs_clarification") is True
    assert "چندین مخاطب" in inferred.get("clarification_prompt", "")


# ==============================================================================
# 3. Approval Record Integrity (TrustedApprovalStore)
# ==============================================================================


def test_trusted_approval_store_detects_tampering_and_prevents_replay(tmp_path: Path) -> None:
    """Verify TrustedApprovalStore enforces account binding, recipient binding, attachment bytes, and replay defense."""
    store = TrustedApprovalStore.get_instance()
    store.clear()

    att_file = tmp_path / "invoice.pdf"
    att_file.write_bytes(b"%PDF-1.4 initial clean bytes")

    svc = EmailService()
    draft = svc.compose_draft(
        to=["client@acme.com"],
        subject="Monthly Invoice",
        body_text="Please find invoice attached.",
        attachment_paths=[str(att_file)],
        provider="gmail",
    )

    initial_hash = draft.compute_payload_hash()
    proposal_id = "prop_test_invoice_001"

    # Register approval
    store.register_approval(
        proposal_id=proposal_id,
        tool_name="email_send",
        account_id="gmail",
        recipient="client@acme.com",
        payload_hash=initial_hash,
    )

    # 1. Account substitution attempt
    ok, err = store.verify_and_consume(
        tool_name="email_send",
        account_id="attacker_account",
        recipient="client@acme.com",
        actual_payload_hash=initial_hash,
        proposal_id=proposal_id,
    )
    assert ok is False
    assert "Account substitution detected" in err

    # 2. Recipient substitution attempt
    ok, err = store.verify_and_consume(
        tool_name="email_send",
        account_id="gmail",
        recipient="attacker@evil.com",
        actual_payload_hash=initial_hash,
        proposal_id=proposal_id,
    )
    assert ok is False
    assert "Recipient substitution detected" in err

    # 3. Attachment disk bytes tampering attempt
    att_file.write_bytes(b"%PDF-1.4 malicious injected payload")
    tampered_hash = draft.compute_payload_hash()
    assert tampered_hash != initial_hash

    ok, err = store.verify_and_consume(
        tool_name="email_send",
        account_id="gmail",
        recipient="client@acme.com",
        actual_payload_hash=tampered_hash,
        proposal_id=proposal_id,
    )
    assert ok is False
    assert "Payload tampering detected" in err

    # 4. Restore disk bytes and verify legitimate consumption
    att_file.write_bytes(b"%PDF-1.4 initial clean bytes")
    restored_hash = draft.compute_payload_hash()
    assert restored_hash == initial_hash

    ok, err = store.verify_and_consume(
        tool_name="email_send",
        account_id="gmail",
        recipient="client@acme.com",
        actual_payload_hash=restored_hash,
        proposal_id=proposal_id,
    )
    assert ok is True

    # 5. Replay attempt
    ok, err = store.verify_and_consume(
        tool_name="email_send",
        account_id="gmail",
        recipient="client@acme.com",
        actual_payload_hash=restored_hash,
        proposal_id=proposal_id,
    )
    assert ok is False
    assert "replay blocked" in err.lower()


# ==============================================================================
# 4. WhatsApp Consent and Webhook Security
# ==============================================================================


def test_whatsapp_consent_greetings_do_not_grant_opt_in() -> None:
    """Verify greetings like 'سلام' or 'hi' do NOT grant opt-in consent; only explicit keywords do."""
    with tempfile.TemporaryDirectory() as td:
        db = CommunicationDatabase(Path(td) / "comm.db")
        settings = Settings(whatsapp_phone_number_id="123456789")

        with patch(
            "tools.communication.whatsapp.whatsapp_service.get_settings", return_value=settings
        ):
            svc = WhatsAppService(db=db)

            # Incoming ordinary greeting
            svc.record_inbound_interaction("+989120000001", message_text="سلام جارویس")
            consent = db.get_consent_status("+989120000001")
            assert consent is None  # No consent granted for greeting

            svc.record_inbound_interaction("+989120000001", message_text="hello there")
            assert db.get_consent_status("+989120000001") is None

            # Explicit opt-in keyword
            svc.record_inbound_interaction("+989120000001", message_text="شروع")
            consent_optin = db.get_consent_status("+989120000001")
            assert consent_optin is not None
            assert consent_optin["consent_status"] == "OPTED_IN"

            # Explicit opt-out keyword
            svc.record_inbound_interaction("+989120000001", message_text="لغو")
            consent_optout = db.get_consent_status("+989120000001")
            assert consent_optout is not None
            assert consent_optout["consent_status"] == "OPTED_OUT"


def test_whatsapp_webhook_business_account_ownership_validation() -> None:
    """Verify webhook rejects status payload belonging to mismatched business account."""
    with tempfile.TemporaryDirectory() as td:
        db = CommunicationDatabase(Path(td) / "comm.db")
        settings = Settings(
            whatsapp_phone_number_id="legitimate_account_id_999",
            whatsapp_app_secret=SecretStr("test_secret"),
        )

        with patch(
            "tools.communication.whatsapp.whatsapp_webhook.get_settings", return_value=settings
        ):
            handler = WhatsAppWebhookHandler(
                app_secret="test_secret",
                verify_token="test_token",
                db=db,
            )

            # Payload with mismatched phone_number_id
            mismatched_payload = {
                "object": "whatsapp_business_account",
                "entry": [
                    {
                        "id": "biz_1",
                        "changes": [
                            {
                                "value": {
                                    "messaging_product": "whatsapp",
                                    "metadata": {
                                        "phone_number_id": "unauthorized_foreign_account_666"
                                    },
                                    "statuses": [{"id": "wamid.test", "status": "sent"}],
                                }
                            }
                        ],
                    }
                ],
            }

            with pytest.raises(PermissionError, match="unauthorized business account ID"):
                handler.process_webhook_payload(mismatched_payload)


# ==============================================================================
# 5. Email Submission Persistence Across Restart
# ==============================================================================


def test_email_submission_persistence_and_unknown_blocking_across_restarts() -> None:
    """Verify email SUBMITTED and UNKNOWN states survive service restart and block blind retries."""
    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "test_comm.db"
        db = CommunicationDatabase(db_path)

        # Mock provider that simulates a network timeout during submission
        svc = EmailService(db=db)
        mock_prov = MagicMock()
        mock_prov.send_email = MagicMock(side_effect=requests.exceptions.Timeout("Read timeout"))
        svc.set_mock_provider(mock_prov)

        draft = svc.compose_draft(
            to=["partner@enterprise.org"],
            subject="Strategic Agreement",
            body_text="Confidential terms.",
            provider="mock",
        )

        # First send attempt times out
        res = svc.send_draft(draft.draft_id)
        assert res.success is False
        assert res.status.value == "unknown"

        # Verify DB recorded UNKNOWN state
        sub = db.get_email_submission(draft.draft_id)
        assert sub is not None
        assert sub["status"] == "unknown"

        # Simulate full JARVIS restart: Re-create EmailService with existing DB
        svc_restarted = EmailService(db=CommunicationDatabase(db_path))
        svc_restarted.set_mock_provider(MockEmailProvider(should_succeed=True))

        # Re-attaching draft to restarted service
        svc_restarted._drafts[draft.draft_id] = draft

        # Resend attempt must be strictly BLOCKED
        res2 = svc_restarted.send_draft(draft.draft_id)
        assert res2.success is False
        assert "Blind retry blocked" in res2.error


# ==============================================================================
# 6. Desktop Authorization Scope Under Strict Default-Deny
# ==============================================================================


def test_desktop_authorization_scope_strict_default_deny(tmp_path: Path) -> None:
    """Verify validate_and_resolve_path blocks arbitrary desktop reads, deletes, copies, and moves
    unless Desktop is in authorized directories or explicitly scoped.
    """
    desktop_dir = tmp_path / "WindowsDesktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    existing_file = desktop_dir / "private_notes.txt"
    existing_file.write_text("Confidential desktop notes")

    sec_store = tmp_path / "auth_dirs.json"
    sec = PathSecurityService(storage_path=sec_store)
    sec.clear_all()
    assert len(sec.list_authorized_directories()) == 0

    with patch("infrastructure.paths.get_desktop_dir", return_value=desktop_dir):
        # 1. Arbitrary read on Desktop -> Denied
        with pytest.raises(PermissionError, match="Desktop directory is not authorized for 'read'"):
            sec.validate_and_resolve_path(str(existing_file), operation="read")

        # 2. Arbitrary delete on Desktop -> Denied
        with pytest.raises(
            PermissionError, match="Desktop directory is not authorized for 'delete'"
        ):
            sec.validate_and_resolve_path(str(existing_file), operation="delete")

        # 3. Arbitrary copy/move on Desktop -> Denied
        with pytest.raises(PermissionError, match="Desktop directory is not authorized for 'copy'"):
            sec.validate_and_resolve_path(str(existing_file), operation="copy")

        # 4. Overwriting existing file without explicit authorization -> Denied
        with pytest.raises(
            PermissionError, match="Overwriting existing file 'private_notes.txt' on Desktop"
        ):
            sec.validate_and_resolve_path(str(existing_file), operation="write")

        # 5. Creating a brand new file on Desktop via explicit request -> Permitted for write
        new_target = desktop_dir / "new_report.html"
        resolved = sec.validate_and_resolve_path(str(new_target), operation="write")
        assert resolved == new_target.resolve()
        # Ensure Desktop is still NOT permanently authorized
        assert len(sec.list_authorized_directories()) == 0

        # 6. Explicitly scoped temporary operation -> Permitted
        sec.authorize_temporary_operation(str(existing_file), operation="read")
        resolved_read = sec.validate_and_resolve_path(str(existing_file), operation="read")
        assert resolved_read == existing_file.resolve()
