"""Unit tests for Phase 9 WhatsApp Cloud API integration, phone normalization, and messaging tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from core.execution_context import ExecutionContext
from tools.base import ToolExecutionStatus
from tools.communication.whatsapp.cloud_api_provider import WhatsAppCloudAPIProvider
from tools.communication.whatsapp.mock_provider import MockWhatsAppProvider
from tools.communication.whatsapp.models import (
    WhatsAppMessage,
    WhatsAppMessageStatus,
)
from tools.communication.whatsapp.whatsapp_service import WhatsAppService
from tools.communication.whatsapp.whatsapp_tools import (
    WhatsAppComposeInput,
    WhatsAppComposeTool,
    WhatsAppSendInput,
    WhatsAppSendTool,
    WhatsAppStatusInput,
    WhatsAppStatusTool,
)


class TestWhatsAppPhoneNormalization:
    """Tests for international E.164 phone number formatting and validation."""

    def test_iranian_mobile_normalization(self):
        svc = WhatsAppService()
        assert svc.normalize_phone_number("09121234567") == "+989121234567"
        assert svc.normalize_phone_number("0935-123-4567") == "+989351234567"
        assert svc.normalize_phone_number("+98 912 123 4567") == "+989121234567"

    def test_persian_digits_normalization(self):
        svc = WhatsAppService()
        assert svc.normalize_phone_number("۰۹۱۲۱۲۳۴۵۶۷") == "+989121234567"

    def test_us_phone_normalization(self):
        svc = WhatsAppService()
        assert svc.normalize_phone_number("(415) 555-2671") == "+14155552671"
        assert svc.normalize_phone_number("+1-415-555-2671") == "+14155552671"

    def test_e164_validation(self):
        svc = WhatsAppService()
        assert svc.validate_phone_number("+989121234567") is True
        assert svc.validate_phone_number("+14155552671") is True
        assert svc.validate_phone_number("09121234567") is False  # Missing leading +
        assert svc.validate_phone_number("+0123") is False  # Too short
        assert svc.validate_phone_number("+123456789012345678") is False  # Too long

    def test_self_recipient_resolution(self):
        svc = WhatsAppService()
        with patch.object(svc.settings, "whatsapp_self_phone_number", "+989121234567"):
            assert svc.resolve_recipient_phone("خودم") == "+989121234567"
            assert svc.resolve_recipient_phone("myself") == "+989121234567"

    def test_self_recipient_unconfigured_raises_error(self):
        svc = WhatsAppService()
        with patch.object(svc.settings, "whatsapp_self_phone_number", ""):
            with pytest.raises(ValueError) as exc:
                svc.resolve_recipient_phone("خودم")
            assert "whatsapp_self_phone_number is not configured" in str(exc.value)


class TestWhatsAppCloudAPIProvider:
    """Tests for official Meta WhatsApp Cloud API provider."""

    def test_unconfigured_provider_fails_safely(self):
        prov = WhatsAppCloudAPIProvider()
        with patch.object(prov, "is_configured", return_value=False):
            res = prov.send_message(
                WhatsAppMessage(recipient_phone="+989121234567", message_text="Hello")
            )
            assert res.success is False
            assert "not configured" in res.error

    def test_send_free_form_text_api_success(self):
        prov = WhatsAppCloudAPIProvider()
        with (
            patch.object(prov, "is_configured", return_value=True),
            patch.object(prov, "get_phone_number_id", return_value="10482910492810"),
            patch.object(prov, "get_access_token", return_value="mock_meta_token"),
            patch("requests.post") as mock_post,
        ):
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {
                    "messaging_product": "whatsapp",
                    "contacts": [{"input": "989121234567", "wa_id": "989121234567"}],
                    "messages": [{"id": "wamid.HBgLM...="}],
                },
            )

            res = prov.send_message(
                WhatsAppMessage(recipient_phone="+989121234567", message_text="سیستم آماده است.")
            )
            assert res.success is True
            assert res.status == WhatsAppMessageStatus.ACCEPTED
            assert "wamid." in res.message_id


class TestWhatsAppTools:
    """Tests for WhatsAppComposeTool, WhatsAppSendTool, and WhatsAppStatusTool."""

    def test_whatsapp_compose_tool(self):
        tool = WhatsAppComposeTool()
        ctx = ExecutionContext()
        res = tool.execute(
            WhatsAppComposeInput(
                recipient="+989121234567",
                message_text="جلسه فردا ساعت ۱۰ برگزار می‌شود.",
            ),
            ctx,
        )
        assert res.status == ToolExecutionStatus.SUCCESS
        assert "draft_id" in res.data
        assert res.data["status"] == "draft_created"
        assert res.data["preview"]["recipient_phone"] == "+989121234567"

    def test_whatsapp_send_tool_requires_approval(self):
        defn = WhatsAppSendTool.get_definition()
        assert defn.requires_approval is True
        assert defn.risk_level.value in ("high", "critical")

    def test_whatsapp_send_tool_with_mock_provider(self):
        svc = WhatsAppService()
        mock_prov = MockWhatsAppProvider(should_succeed=True)
        svc.set_mock_provider(mock_prov)

        draft = svc.compose_draft(
            recipient="+989121234567",
            message_text="گزارش با موفقیت آماده شد.",
        )

        with patch(
            "tools.communication.whatsapp.whatsapp_tools.get_whatsapp_service", return_value=svc
        ):
            tool = WhatsAppSendTool()
            ctx = ExecutionContext()
            res = tool.execute(WhatsAppSendInput(draft_id=draft.draft_id), ctx)
            assert res.status == ToolExecutionStatus.SUCCESS
            assert res.data["status"] == "accepted"
            assert len(mock_prov.sent_messages) == 1
            assert mock_prov.sent_messages[0].recipient_phone == "+989121234567"

    def test_whatsapp_status_tool(self):
        tool = WhatsAppStatusTool()
        ctx = ExecutionContext()
        res = tool.execute(WhatsAppStatusInput(), ctx)
        assert res.status == ToolExecutionStatus.SUCCESS
        assert "provider" in res.data


class TestWhatsAppWebhook:
    """Tests for Meta WhatsApp Cloud API Webhook signature verification and status transitions."""

    def test_webhook_handshake_verification_success(self):
        from tools.communication.whatsapp.whatsapp_webhook import WhatsAppWebhookHandler

        handler = WhatsAppWebhookHandler(verify_token="test_token_123")
        res = handler.handle_verification(
            mode="subscribe", token="test_token_123", challenge="test_challenge_abc"
        )
        assert res == "test_challenge_abc"

    def test_webhook_handshake_verification_invalid_token(self):
        from tools.communication.whatsapp.whatsapp_webhook import WhatsAppWebhookHandler

        handler = WhatsAppWebhookHandler(verify_token="test_token_123")
        res = handler.handle_verification(
            mode="subscribe", token="wrong_token", challenge="test_challenge_abc"
        )
        assert res is None

    def test_webhook_signature_verification_valid_and_forged(self):
        import hashlib
        import hmac

        from tools.communication.whatsapp.whatsapp_webhook import WhatsAppWebhookHandler

        secret = "meta_app_secret_xyz"
        handler = WhatsAppWebhookHandler(app_secret=secret)

        raw_payload = b'{"entry": []}'
        valid_digest = hmac.new(secret.encode("utf-8"), raw_payload, hashlib.sha256).hexdigest()
        valid_header = f"sha256={valid_digest}"

        assert handler.verify_signature(raw_payload, valid_header) is True
        # Forged signature
        assert handler.verify_signature(raw_payload, "sha256=forged_hex_signature") is False
        assert handler.verify_signature(raw_payload, None) is False

    def test_webhook_event_status_transitions_and_deduplication(self):
        from tools.communication.whatsapp.whatsapp_webhook import WhatsAppWebhookHandler

        handler = WhatsAppWebhookHandler(app_secret="test_secret")
        msg_id = "wamid.HBgLTEST123=="
        handler.register_outbound_message(msg_id, "+989121234567")

        rec = handler.get_message_record(msg_id)
        assert rec is not None
        assert rec.current_status == WhatsAppMessageStatus.ACCEPTED

        # 1. Received 'sent' event
        sent_payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": msg_id,
                                        "status": "sent",
                                        "timestamp": "1731580000",
                                        "recipient_id": "989121234567",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        updates = handler.process_webhook_payload(sent_payload)
        assert len(updates) == 1
        assert updates[0].status == WhatsAppMessageStatus.SENT
        assert rec.current_status == WhatsAppMessageStatus.SENT

        # Deduplication: Re-submitting the exact same event returns 0 new updates
        dup_updates = handler.process_webhook_payload(sent_payload)
        assert len(dup_updates) == 0

        # 2. Received 'delivered' event
        delivered_payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": msg_id,
                                        "status": "delivered",
                                        "timestamp": "1731580010",
                                        "recipient_id": "989121234567",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        updates_del = handler.process_webhook_payload(delivered_payload)
        assert len(updates_del) == 1
        assert rec.current_status == WhatsAppMessageStatus.DELIVERED

        # 3. Received 'read' event
        read_payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "statuses": [
                                    {
                                        "id": msg_id,
                                        "status": "read",
                                        "timestamp": "1731580020",
                                        "recipient_id": "989121234567",
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }
        updates_read = handler.process_webhook_payload(read_payload)
        assert len(updates_read) == 1
        assert rec.current_status == WhatsAppMessageStatus.READ


class TestWhatsAppDuplicatePrevention:
    """Tests for preventing duplicate sends of WhatsApp drafts."""

    def test_whatsapp_duplicate_send_prevention(self):
        svc = WhatsAppService()
        mock_prov = MockWhatsAppProvider(should_succeed=True)
        svc.set_mock_provider(mock_prov)

        draft = svc.compose_draft("+989121234567", "پیام تستی")
        # Mark as in-flight
        svc._in_flight_drafts.add(draft.draft_id)

        res = svc.send_draft(draft.draft_id)
        assert res.success is False
        assert "Duplicate send prevented" in res.error

        # Release in-flight
        svc._in_flight_drafts.clear()
        res2 = svc.send_draft(draft.draft_id)
        assert res2.success is True


class TestWhatsAppCustomerServiceWindowAndHMAC:
    """Tests for Meta 24-hour customer service window and HMAC webhook signature verification."""

    def test_24h_window_policy_enforcement(self):
        from datetime import UTC, datetime, timedelta

        svc = WhatsAppService()
        mock_prov = MockWhatsAppProvider(should_succeed=True)
        svc.set_mock_provider(mock_prov)
        svc.settings.whatsapp_enforce_24h_window = True

        phone = "+989121234567"

        # 1. No prior inbound message -> free-form message blocked
        draft1 = svc.compose_draft(phone, "Hello outside window")
        res1 = svc.send_draft(draft1.draft_id)
        assert res1.success is False
        assert "24-hour customer service window" in res1.error

        # 2. Template message allowed outside window
        draft_template = svc.compose_draft(
            phone,
            "Template message text",
            template_name="hello_world",
            template_language="en_US",
        )
        res_temp = svc.send_draft(draft_template.draft_id)
        assert res_temp.success is True

        # 3. Inbound message received -> window opens -> free-form allowed
        svc.record_inbound_interaction(phone, datetime.now(UTC))
        assert svc.is_within_customer_service_window(phone) is True

        draft2 = svc.compose_draft(phone, "Hello inside active window")
        res2 = svc.send_draft(draft2.draft_id)
        assert res2.success is True

        # 4. Inbound interaction older than 24 hours -> window expired
        old_time = datetime.now(UTC) - timedelta(hours=25)
        svc.record_inbound_interaction(phone, old_time)
        assert svc.is_within_customer_service_window(phone) is False

    def test_webhook_hmac_sha256_signature_verification(self):
        import hashlib
        import hmac

        from tools.communication.whatsapp.whatsapp_webhook import WhatsAppWebhookHandler

        secret = "test_meta_app_secret_xyz123"
        handler = WhatsAppWebhookHandler(app_secret=secret)

        raw_payload = b'{"entry": [{"id": "123", "changes": []}]}'

        # 1. Valid signature
        valid_digest = hmac.new(secret.encode("utf-8"), raw_payload, hashlib.sha256).hexdigest()
        assert handler.verify_signature(raw_payload, f"sha256={valid_digest}") is True

        # 2. Tampered payload
        tampered_payload = b'{"entry": [{"id": "123", "changes": [{"forged": true}]}]}'
        assert handler.verify_signature(tampered_payload, f"sha256={valid_digest}") is False

        # 3. Wrong secret
        wrong_handler = WhatsAppWebhookHandler(app_secret="different_secret")
        assert wrong_handler.verify_signature(raw_payload, f"sha256={valid_digest}") is False

        # 4. Missing / malformed header
        assert handler.verify_signature(raw_payload, None) is False
        assert handler.verify_signature(raw_payload, "invalid_header_format") is False
