"""Unit tests for Phase 9 Email Integration, OAuth token storage, and Gmail/MS Graph providers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.execution_context import ExecutionContext
from infrastructure.credential_store import CredentialStore
from tools.base import ToolExecutionStatus
from tools.communication.email.email_service import EmailService
from tools.communication.email.email_tools import (
    EmailComposeInput,
    EmailComposeTool,
    EmailSendInput,
    EmailSendTool,
    EmailStatusInput,
    EmailStatusTool,
)
from tools.communication.email.gmail_provider import GmailEmailProvider
from tools.communication.email.mock_provider import MockEmailProvider
from tools.communication.email.models import EmailMessage, EmailSendStatus
from tools.communication.email.msgraph_provider import MicrosoftGraphEmailProvider


class TestCredentialStore:
    """Tests for encrypted credential storage."""

    def test_store_and_retrieve_credentials(self, tmp_path: Path):
        store = CredentialStore(tmp_path / "creds.enc")
        store.store_credential("gmail", "access_token", "ya29.test_token_123")
        store.store_credential("gmail", "refresh_token", "1//test_refresh_456")

        assert store.get_credential("gmail", "access_token") == "ya29.test_token_123"
        assert store.get_credential("gmail", "refresh_token") == "1//test_refresh_456"
        assert store.list_services() == ["gmail"]

        # Deletion
        store.delete_credential("gmail", "access_token")
        assert store.get_credential("gmail", "access_token") is None
        assert store.get_credential("gmail", "refresh_token") == "1//test_refresh_456"


class TestEmailService:
    """Tests for recipient validation, attachment boundaries, and draft composition."""

    def test_email_validation(self):
        svc = EmailService()
        assert svc.validate_email_address("alice@example.com") is True
        assert svc.validate_email_address("ali.reza@sub.domain.org") is True
        assert svc.validate_email_address("invalid_email") is False
        assert svc.validate_email_address("@missinguser.com") is False

    def test_compose_draft_validates_recipients(self):
        svc = EmailService()
        with pytest.raises(ValueError) as exc:
            svc.compose_draft(to=["invalid_address"], subject="Test", body_text="Hello")
        assert "Invalid recipient" in str(exc.value)

    def test_attachment_validation_checks_existence(self):
        svc = EmailService()
        with pytest.raises(FileNotFoundError):
            svc.validate_attachment("C:/AI/jarvis/non_existent_file_xyz.pdf")

    def test_compose_draft_success(self, tmp_path: Path):
        svc = EmailService()
        att_file = tmp_path / "report.txt"
        att_file.write_text("Sales report content")

        msg = svc.compose_draft(
            to=["ali@example.com"],
            subject="Monthly Report",
            body_text="Please find attached the sales report.",
            attachment_paths=[str(att_file)],
        )
        assert msg.draft_id is not None
        assert msg.to == ["ali@example.com"]
        assert len(msg.attachments) == 1
        assert msg.attachments[0].file_name == "report.txt"

        # Check retrieval
        retrieved = svc.get_draft(msg.draft_id)
        assert retrieved == msg


class TestGmailEmailProvider:
    """Tests for official Gmail REST API provider."""

    def test_build_mime_message(self, tmp_path: Path):
        prov = GmailEmailProvider()
        test_file = tmp_path / "sample.pdf"
        test_file.write_bytes(b"%PDF-1.4 test bytes")

        from tools.communication.email.models import EmailAttachment

        msg = EmailMessage(
            to=["bob@example.com"],
            subject="Invoice #123",
            body_text="Plain invoice text",
            body_html="<p>HTML invoice text</p>",
            attachments=[
                EmailAttachment(
                    file_path=test_file,
                    file_name="sample.pdf",
                    file_size_bytes=test_file.stat().st_size,
                    mime_type="application/pdf",
                )
            ],
        )

        mime_bytes = prov.build_mime_message(msg)
        assert b"To: bob@example.com" in mime_bytes
        assert b"Subject: Invoice #123" in mime_bytes
        assert b"sample.pdf" in mime_bytes

    def test_send_email_unauthenticated_fails(self):
        prov = GmailEmailProvider()
        with patch.object(prov, "is_authenticated", return_value=False):
            res = prov.send_email(
                EmailMessage(to=["test@example.com"], subject="Hello", body_text="World")
            )
            assert res.success is False
            assert "not connected" in res.error

    def test_send_email_api_success(self):
        prov = GmailEmailProvider()
        with (
            patch.object(prov, "is_authenticated", return_value=True),
            patch.object(prov, "_get_valid_token", return_value="mock_valid_token"),
            patch("requests.post") as mock_post,
        ):
            mock_post.return_value = MagicMock(
                status_code=200,
                json=lambda: {"id": "gmail_msg_12345", "threadId": "t1"},
            )

            res = prov.send_email(
                EmailMessage(to=["test@example.com"], subject="Hello", body_text="World")
            )
            assert res.success is True
            assert res.status == EmailSendStatus.ACCEPTED
            assert res.message_id == "gmail_msg_12345"


class TestMicrosoftGraphEmailProvider:
    """Tests for official Microsoft Graph API provider."""

    def test_send_email_accepted_202(self):
        prov = MicrosoftGraphEmailProvider()
        with (
            patch.object(prov, "is_authenticated", return_value=True),
            patch.object(prov.credential_store, "get_credential", return_value="mock_graph_token"),
            patch("requests.post") as mock_post,
        ):
            # Microsoft Graph sendMail returns HTTP 202 on success
            mock_post.return_value = MagicMock(status_code=202)

            res = prov.send_email(
                EmailMessage(to=["colleague@company.com"], subject="Sync", body_text="Hi team")
            )
            assert res.success is True
            assert res.status == EmailSendStatus.ACCEPTED
            assert res.provider == "msgraph"


class TestEmailTools:
    """Tests for EmailComposeTool, EmailSendTool, and EmailStatusTool."""

    def test_email_compose_tool(self):
        tool = EmailComposeTool()
        ctx = ExecutionContext()
        res = tool.execute(
            EmailComposeInput(
                to=["manager@example.com"],
                subject="Status Update",
                body_text="All systems nominal.",
            ),
            ctx,
        )
        assert res.status == ToolExecutionStatus.SUCCESS
        assert "draft_id" in res.data
        assert res.data["status"] == "draft_created"

    def test_email_send_tool_requires_approval(self):
        defn = EmailSendTool.get_definition()
        assert defn.requires_approval is True
        assert defn.risk_level.value in ("high", "critical")

    def test_email_send_tool_with_mock_provider(self):
        svc = EmailService()
        mock_prov = MockEmailProvider(should_succeed=True)
        svc.set_mock_provider(mock_prov)

        draft = svc.compose_draft(
            to=["client@example.com"],
            subject="Project Milestone",
            body_text="Phase 9 completed.",
            provider="mock",
        )

        with patch("tools.communication.email.email_tools.get_email_service", return_value=svc):
            tool = EmailSendTool()
            ctx = ExecutionContext()
            res = tool.execute(EmailSendInput(draft_id=draft.draft_id), ctx)
            assert res.status == ToolExecutionStatus.SUCCESS
            assert res.data["status"] == "accepted"
            assert len(mock_prov.sent_messages) == 1

    def test_email_status_tool(self):
        tool = EmailStatusTool()
        ctx = ExecutionContext()
        res = tool.execute(EmailStatusInput(), ctx)
        assert res.status == ToolExecutionStatus.SUCCESS
        assert "gmail" in res.data
        assert "msgraph" in res.data

    def test_email_duplicate_send_prevention(self):
        svc = EmailService()
        mock_prov = MockEmailProvider(should_succeed=True)
        svc.set_mock_provider(mock_prov)

        draft = svc.compose_draft(
            to=["client@example.com"],
            subject="Test",
            body_text="Test Body",
            provider="mock",
        )
        svc._in_flight_drafts.add(draft.draft_id)

        res = svc.send_draft(draft.draft_id)
        assert res.success is False
        assert "Duplicate send prevented" in res.error

        svc._in_flight_drafts.clear()
        res2 = svc.send_draft(draft.draft_id)
        assert res2.success is True

    def test_voice_approval_rejected_for_email_send(self):
        import uuid

        from core.approval import ApprovalManager
        from core.tool_proposal import RiskLevel, ToolProposal

        approval_mgr = ApprovalManager()
        prop = ToolProposal(
            proposal_id=f"prop_{uuid.uuid4().hex[:8]}",
            session_id="session_voice_test",
            tool_name="email_send",
            risk_level=RiskLevel.HIGH,
            arguments={"draft_id": "draft_123"},
        )
        approval_mgr._pending_proposals[prop.proposal_id] = prop

        # Voice approval submission must be rejected
        ok = approval_mgr.submit_decision(
            proposal_id=prop.proposal_id,
            approved=True,
            session_id="session_voice_test",
            source="voice",
        )
        assert ok is False


class TestEmailSubmissionAndSafety:
    """Tests for post-submission network timeout UNKNOWN status and blind retry blocking."""

    def test_email_timeout_yields_unknown_and_blocks_resend(self):
        import requests

        from tools.communication.email.email_service import EmailService
        from tools.communication.email.models import EmailSendStatus

        svc = EmailService()
        draft = svc.compose_draft(["user@example.com"], "Subject", "Body", provider="mock")

        # Mock a network timeout during HTTP dispatch
        mock_provider = MagicMock()
        mock_provider.send_email = MagicMock(
            side_effect=requests.exceptions.Timeout("Read timeout")
        )
        svc.set_mock_provider(mock_provider)

        # First send attempt -> times out -> status must be UNKNOWN
        res1 = svc.send_draft(draft.draft_id)
        assert res1.success is False
        assert res1.status in (EmailSendStatus.UNKNOWN, EmailSendStatus.SUBMISSION_UNKNOWN)
        assert "timeout" in res1.error.lower()

        # Immediate re-send attempt of the same draft must be blocked to prevent duplicates
        res2 = svc.send_draft(draft.draft_id)
        assert res2.success is False
        assert res2.status == EmailSendStatus.UNKNOWN
        assert "Blind retry blocked" in res2.error
        # Provider must NOT have been called a second time
        assert mock_provider.send_email.call_count == 1
