"""Unit tests for JARVIS Phase 9 Final Super Remediation & Advanced Voice Identity.

Verifies:
1. Persian voice input understanding -> British English spoken response formulation.
2. BritishNeuralTTSService multi-engine routing, voice preview, and barge-in.
3. Cryptographic approval payload binding and tampering rejection (Email & WhatsApp).
4. Durable CommunicationDatabase SQLite persistence for recipient consent and webhook events.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from core.execution_context import ExecutionContext
from core.personality import JarvisPersonalityEngine
from infrastructure.communication_db import CommunicationDatabase
from tools.communication.email.email_service import get_email_service
from tools.communication.email.email_tools import (
    EmailComposeInput,
    EmailComposeTool,
    EmailSendInput,
    EmailSendTool,
)
from tools.communication.whatsapp.whatsapp_service import get_whatsapp_service
from tools.communication.whatsapp.whatsapp_tools import (
    WhatsAppComposeInput,
    WhatsAppComposeTool,
    WhatsAppSendInput,
    WhatsAppSendTool,
)
from tools.voice.models import TTSRequest
from tools.voice.tts_service import BritishNeuralTTSService, MockTTSService


class TestPersianUnderstandingAndBritishVoiceIdentity:
    """Tests for Persian understanding and authentic JARVIS British tone."""

    def test_persian_system_check_to_british_voice(self):
        prompt = "جارویس، وضعیت سیستم رو بررسی کن"
        response = "پردازنده 15 درصد و حافظه رم 45 درصد مصرف شده است."
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text=response, user_prompt=prompt
        )
        assert "Certainly, sir." in spoken
        assert "System status check is complete" in spoken
        assert "within normal parameters" in spoken

    def test_persian_email_draft_to_british_voice(self):
        prompt = "برای علی ایمیل بفرست"
        response = "پیش‌نویس ایمیل با موفقیت آماده شد و در انتظار تأیید شماست."
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text=response, user_prompt=prompt
        )
        assert "prepared the email draft" in spoken
        assert "Awaiting your approval" in spoken

    def test_persian_whatsapp_draft_to_british_voice(self):
        prompt = "در واتساپ به علی پیام بده"
        response = "پیش‌نویس پیام واتساپ ساخته شد."
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text=response, user_prompt=prompt
        )
        assert "drafted the WhatsApp message" in spoken

    def test_persian_cancelled_to_british_voice(self):
        prompt = "ارسال رو لغو کن"
        response = "عملیات ارسال لغو شد."
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text=response, user_prompt=prompt
        )
        assert "cancelled" in spoken

    def test_english_response_refinement(self):
        response = "CPU usage is 12% and memory is nominal."
        spoken = JarvisPersonalityEngine.format_spoken_response_en(
            text=response, user_prompt="Check CPU"
        )
        assert "Certainly, sir." in spoken
        assert "CPU usage is 12%" in spoken


class TestBritishNeuralTTSService:
    """Tests for BritishNeuralTTSService multi-backend routing, preview, and barge-in."""

    def test_voice_preview_phrase(self):
        mock_fallback = MockTTSService()
        tts = BritishNeuralTTSService(engine_name="mock", fallback_engine=mock_fallback)
        success = tts.preview_voice()
        assert success is True
        assert tts.is_speaking() is True

    def test_barge_in_stop(self):
        mock_fallback = MockTTSService()
        tts = BritishNeuralTTSService(engine_name="mock", fallback_engine=mock_fallback)
        tts.speak(TTSRequest(text="Long text being spoken"))
        assert tts.is_speaking() is True

        tts.stop()
        assert tts.is_speaking() is False
        assert mock_fallback.stopped_count >= 1

    def test_azure_fallback_on_missing_key(self):
        mock_fallback = MockTTSService()
        tts = BritishNeuralTTSService(engine_name="azure_neural", fallback_engine=mock_fallback)
        with patch.object(tts.settings, "azure_speech_key", None):
            res = tts._synthesize_azure("Hello sir", "en-GB-RyanNeural", 1.0, 1.0)
            assert res is True
            assert len(mock_fallback.spoken_requests) == 1
            assert mock_fallback.spoken_requests[0].text == "Hello sir"

    def test_openai_fallback_on_missing_key(self):
        mock_fallback = MockTTSService()
        tts = BritishNeuralTTSService(engine_name="openai_speech", fallback_engine=mock_fallback)
        with patch.object(tts.settings, "openai_api_key", None):
            res = tts._synthesize_openai("Greetings sir", "fable", 1.0, 1.0)
            assert res is True
            assert len(mock_fallback.spoken_requests) == 1
            assert mock_fallback.spoken_requests[0].text == "Greetings sir"

    def test_available_voices_listing(self):
        tts = BritishNeuralTTSService(engine_name="mock")
        voices = tts.get_available_voices()
        assert any("en-GB-OliverNeural" in v for v in voices)
        assert any("en-GB-Ryan:DragonHDLatestNeural" in v for v in voices)
        assert any("en-GB-RyanNeural" in v for v in voices)
        assert any("fable" in v for v in voices)
        assert any("Windows Native" in v for v in voices)


class TestApprovalPayloadBindingAndTamperResistance:
    """Verifies cryptographic binding of approvals to draft contents."""

    def test_email_payload_tamper_rejection(self):
        compose_tool = EmailComposeTool()
        send_tool = EmailSendTool()
        ctx = ExecutionContext()

        # 1. Compose draft
        res = compose_tool.execute(
            EmailComposeInput(
                to=["security@example.com"],
                subject="Initial Safe Subject",
                body_text="Initial Safe Body",
                provider="gmail",
            ),
            ctx,
        )
        assert res.is_success is True
        draft_id = res.data["draft_id"]
        valid_hash = res.data["preview"]["payload_hash"]

        # 2. Attempt tampering: modify draft in-memory before send
        service = get_email_service()
        draft = service.get_draft(draft_id)
        assert draft is not None
        draft.body_text = "TAMPERED MALICIOUS CONTENT"

        # 3. Execute with approved hash -> must be REJECTED
        send_res = send_tool.execute(
            EmailSendInput(
                draft_id=draft_id,
                payload_hash=valid_hash,
            ),
            ctx,
        )
        assert send_res.is_success is False
        assert "tampering detected" in send_res.error.lower()

    def test_whatsapp_payload_tamper_rejection(self):
        compose_tool = WhatsAppComposeTool()
        send_tool = WhatsAppSendTool()
        ctx = ExecutionContext()

        # 1. Compose draft
        res = compose_tool.execute(
            WhatsAppComposeInput(
                recipient="+989121112233",
                message_text="Initial Safe WhatsApp Message",
            ),
            ctx,
        )
        assert res.is_success is True
        draft_id = res.data["draft_id"]
        valid_hash = res.data["preview"]["payload_hash"]

        # 2. Attempt tampering
        wa_service = get_whatsapp_service()
        draft = wa_service.get_draft(draft_id)
        assert draft is not None
        draft.message_text = "TAMPERED MALICIOUS WHATSAPP MESSAGE"

        # 3. Execute with approved hash -> must be REJECTED
        send_res = send_tool.execute(
            WhatsAppSendInput(
                draft_id=draft_id,
                payload_hash=valid_hash,
            ),
            ctx,
        )
        assert send_res.is_success is False
        assert "tampering detected" in send_res.error.lower()


class TestCommunicationDatabasePersistence:
    """Tests SQLite persistence for recipient consent and webhook deduplication across restarts."""

    def test_recipient_opt_in_and_opt_out_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "test_comm.sqlite3"
            db = CommunicationDatabase(db_file)

            # Record opt-in
            phone = "+989123456789"
            db.record_consent(phone, status="OPTED_IN", source="test_suite")
            assert db.is_consent_granted(phone) is True

            # Re-open database from disk (simulating restart)
            db2 = CommunicationDatabase(db_file)
            assert db2.is_consent_granted(phone) is True

            # Revoke consent
            db2.revoke_consent(phone, reason="user_stop")
            assert db2.is_consent_granted(phone) is False
            status = db2.get_consent_status(phone)
            assert status["consent_status"] == "OPTED_OUT"
            assert status["revoked_at"] is not None

    def test_webhook_deduplication_across_restarts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_file = Path(tmpdir) / "test_comm.sqlite3"
            db = CommunicationDatabase(db_file)

            event_id = "wa_evt_unique_12345"
            p_hash = "abcde12345hash"

            # First insertion succeeds
            assert db.record_webhook_event(event_id, p_hash) is True
            # Duplicate fails
            assert db.record_webhook_event(event_id, p_hash) is False

            # Re-open from disk (process restart)
            db2 = CommunicationDatabase(db_file)
            assert db2.is_webhook_event_processed(event_id) is True
            assert db2.record_webhook_event(event_id, p_hash) is False

    def test_whatsapp_service_blocks_opted_out_recipient(self):
        wa_service = get_whatsapp_service()
        phone = "+989998887766"

        # Explicitly opt-out recipient in db
        wa_service.db.revoke_consent(phone, reason="test_opt_out")

        # Compose and try to send
        draft = wa_service.compose_draft(recipient=phone, message_text="Hello")
        res = wa_service.send_draft(draft.draft_id)

        assert res.success is False
        assert "opted out" in res.error.lower()
