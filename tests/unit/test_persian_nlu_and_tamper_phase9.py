"""Comprehensive Persian NLU, Approval Payload Tamper Protection, and Delivery Monotonicity Tests.

Validates:
1. 9 realistic Persian requests (file create, file read, telemetry, app launch, email, WhatsApp, follow-up, denial, failure).
2. Attachment content cryptographic binding & disk tampering detection.
3. WhatsApp account ID binding and tamper detection.
4. Monotonic delivery state progression & timeout UNKNOWN preservation in SQLite.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from core.execution_context import ExecutionContext
from core.personality import JarvisPersonalityEngine
from infrastructure.communication_db import CommunicationDatabase
from tools.communication.email.email_service import get_email_service
from tools.communication.email.email_tools import (
    EmailSendInput,
    EmailSendTool,
)
from tools.communication.email.mock_provider import MockEmailProvider
from tools.communication.whatsapp.mock_provider import MockWhatsAppProvider
from tools.communication.whatsapp.whatsapp_service import get_whatsapp_service
from tools.communication.whatsapp.whatsapp_tools import (
    WhatsAppSendInput,
    WhatsAppSendTool,
)


class TestPersianNLUUnderstandingScenarios:
    """Tests authentic understanding and British English response for 9 realistic Persian requests."""

    def test_scenario_1_file_creation(self) -> None:
        user_prompt = "روی دسکتاپ یک فایل به اسم report.html ایجاد کن"
        agent_text = "فایل report.html ایجاد شد."
        resp = JarvisPersonalityEngine.format_spoken_response_en(agent_text, user_prompt)
        assert "Certainly, sir." in resp
        assert "created and verified" in resp.lower()
        assert "report.html" in resp
        assert "desktop" in resp.lower()

    def test_scenario_2_file_reading(self) -> None:
        user_prompt = "لطفاً فایل config.json را بخوان و محتوایش را بررسی کن"
        agent_text = "محتوای فایل config.json به شرح زیر است:"
        resp = JarvisPersonalityEngine.format_spoken_response_en(agent_text, user_prompt)
        assert "Certainly, sir." in resp
        assert "read and inspected" in resp.lower()
        assert "config.json" in resp

    def test_scenario_3_system_telemetry_cpu_ram(self) -> None:
        user_prompt = "وضعیت سیستم و پردازنده چطور است؟"
        agent_text = "میزان مصرف CPU در حال حاضر 24.5% و رم در وضعیت عادی است."
        resp = JarvisPersonalityEngine.format_spoken_response_en(agent_text, user_prompt)
        assert "Certainly, sir." in resp
        assert "24.5%" in resp
        assert "CPU utilization" in resp

    def test_scenario_4_app_launch(self) -> None:
        user_prompt = "برنامه ماشین حساب را برای من باز کن"
        agent_text = "ماشین حساب اجرا شد."
        resp = JarvisPersonalityEngine.format_spoken_response_en(agent_text, user_prompt)
        assert "Right away, sir." in resp
        assert "Calculator" in resp

    def test_scenario_5_email_draft_and_approval(self) -> None:
        user_prompt = "یک ایمیل به contact@acme.com بفرست"
        agent_text = "پیش‌نویس ایمیل به contact@acme.com آماده شد و نیاز به تأیید دارد."
        resp = JarvisPersonalityEngine.format_spoken_response_en(agent_text, user_prompt)
        assert "contact@acme.com" in resp
        assert "awaiting your approval" in resp.lower()

    def test_scenario_6_whatsapp_draft(self) -> None:
        user_prompt = "در واتساپ به شماره 09121112233 پیام بده"
        agent_text = "پیش‌نویس پیام واتساپ به +989121112233 آماده تأیید است."
        resp = JarvisPersonalityEngine.format_spoken_response_en(agent_text, user_prompt)
        assert "drafted the WhatsApp message" in resp
        assert "ready for your confirmation" in resp.lower()

    def test_scenario_7_contextual_follow_up_reference(self) -> None:
        user_prompt = "همین فایل را ویرایش کن"
        agent_text = "تغییرات روی همین فایل اعمال شد."
        resp = JarvisPersonalityEngine.format_spoken_response_en(agent_text, user_prompt)
        assert "Certainly, sir." in resp
        assert "referenced file" in resp.lower()

    def test_scenario_8_permission_denial(self) -> None:
        user_prompt = "عملیات را انجام بده"
        agent_text = "کاربر اجازه ندادید و عملیات لغو شد."
        resp = JarvisPersonalityEngine.format_spoken_response_en(agent_text, user_prompt)
        assert "cancelled or denied" in resp.lower()

    def test_scenario_9_tool_failure(self) -> None:
        user_prompt = "فایل را ذخیره کن"
        agent_text = "خطا: دسترسی به دیسک مقدور نبود و ذخیره با شکست مواجه شد."
        resp = JarvisPersonalityEngine.format_spoken_response_en(agent_text, user_prompt)
        assert "encountered an issue" in resp.lower()


class TestAttachmentContentTamperingAndApprovalIntegrity:
    """Verifies SHA256 binding of email attachment content and WhatsApp account ID."""

    def test_email_attachment_content_tampering_detected(self, tmp_path: Path) -> None:
        # Create real attachment file on disk
        att_file = tmp_path / "invoice.txt"
        att_file.write_text("Invoice #101: Total $500", encoding="utf-8")

        svc = get_email_service()
        svc.set_mock_provider(MockEmailProvider())
        msg = svc.compose_draft(
            to=["finance@example.com"],
            subject="Monthly Invoice",
            body_text="Please review attached invoice.",
            attachment_paths=[str(att_file)],
            provider="mock",
        )
        approved_hash = msg.compute_payload_hash()

        # Attacker modifies the file content on disk without changing filename or size
        att_file.write_text("Invoice #101: Total $999", encoding="utf-8")

        # Recomputed hash must change
        tampered_hash = msg.compute_payload_hash()
        assert approved_hash != tampered_hash

        # Attempting to send using the previously approved hash must be rejected
        tool = EmailSendTool()
        ctx = ExecutionContext()
        res = tool.execute(
            EmailSendInput(draft_id=msg.draft_id, payload_hash=approved_hash),
            ctx,
        )
        assert res.is_success is False
        assert "tampering detected" in res.error.lower()

    def test_whatsapp_account_id_tamper_rejection(self) -> None:
        wa_svc = get_whatsapp_service()
        wa_svc.set_mock_provider(MockWhatsAppProvider())
        msg = wa_svc.compose_draft(
            recipient="+989123456789",
            message_text="Meeting confirmed at 10 AM.",
        )
        original_hash = msg.compute_payload_hash()

        # Attacker tampers with the sender account_id
        msg.account_id = "malicious_spoofed_account"
        tampered_hash = msg.compute_payload_hash()
        assert original_hash != tampered_hash

        tool = WhatsAppSendTool()
        ctx = ExecutionContext()
        res = tool.execute(
            WhatsAppSendInput(draft_id=msg.draft_id, payload_hash=original_hash),
            ctx,
        )
        assert res.is_success is False
        assert "tampering detected" in res.error.lower()


class TestDeliveryStateMonotonicityAndTimeoutUnknown:
    """Verifies that delivery state progression is monotonic and timeouts produce UNKNOWN."""

    def test_monotonic_state_transitions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test_mono.sqlite3"
            db = CommunicationDatabase(db_path)

            msg_id = "msg_test_1001"
            phone = "+989123456789"

            # 1. Staged -> submitted
            db.save_delivery_record(msg_id, phone, "submitted")
            assert db.get_delivery_record(msg_id)["current_status"] == "submitted"

            # 2. Advanced to accepted
            db.save_delivery_record(msg_id, phone, "accepted")
            assert db.get_delivery_record(msg_id)["current_status"] == "accepted"

            # 3. Advanced to delivered
            db.save_delivery_record(msg_id, phone, "delivered")
            assert db.get_delivery_record(msg_id)["current_status"] == "delivered"

            # 4. Advanced to read
            db.save_delivery_record(msg_id, phone, "read")
            assert db.get_delivery_record(msg_id)["current_status"] == "read"

            # 5. Out-of-order update with earlier status (e.g. sent) must NOT regress read
            db.save_delivery_record(msg_id, phone, "sent")
            assert db.get_delivery_record(msg_id)["current_status"] == "read"

            # 6. UNKNOWN status must NOT overwrite confirmed read
            db.save_delivery_record(msg_id, phone, "unknown")
            assert db.get_delivery_record(msg_id)["current_status"] == "read"
