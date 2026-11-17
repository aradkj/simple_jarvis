"""Unit tests for WhatsApp Integration (Providers, Contact Manager, Notifications, Inbound Router)."""

from __future__ import annotations

from pathlib import Path

from integrations.antigravity.lifecycle import AntigravityTaskRecord, TaskLifecycleState
from integrations.antigravity.verifier import TaskVerificationResult
from integrations.whatsapp.adapter import WhatsAppIntegration
from integrations.whatsapp.contact_manager import WhatsAppContactManager
from integrations.whatsapp.inbound_handler import InboundCommandHandler
from integrations.whatsapp.linked_device_provider import LinkedDeviceWhatsAppProvider
from integrations.whatsapp.notification_manager import WhatsAppNotificationManager
from integrations.whatsapp.provider_base import (
    WhatsAppConnectionStatus,
)


def test_contact_normalization_and_resolution():
    mgr = WhatsAppContactManager()
    mgr.settings.whatsapp_self_phone_number = "+989123456789"

    # Normalization
    assert mgr.normalize_phone("09123456789") == "+989123456789"
    assert mgr.normalize_phone("00989123456789") == "+989123456789"
    assert mgr.normalize_phone("+1 (555) 123-4567") == "+15551234567"

    # Self resolution
    assert mgr.resolve_recipient("خودم") == "+989123456789"
    assert mgr.resolve_recipient("me") == "+989123456789"


def test_authorized_sender_security():
    mgr = WhatsAppContactManager()
    # Add authorized contact without command execution permission
    mgr.add_authorized_contact("+989120000001", "Friend", role="user", can_execute_commands=False)

    # Add authorized admin with command execution permission
    mgr.add_authorized_contact(
        "+989120000002", "Admin User", role="admin", can_execute_commands=True
    )

    # Unknown sender
    assert mgr.is_authorized("+989999999999") is False
    assert mgr.is_authorized("+989999999999", require_command_permission=True) is False

    # Friend (messaging authorized, commands unauthorized)
    assert mgr.is_authorized("+989120000001") is True
    assert mgr.is_authorized("+989120000001", require_command_permission=True) is False

    # Admin (both authorized)
    assert mgr.is_authorized("+989120000002") is True
    assert mgr.is_authorized("+989120000002", require_command_permission=True) is True


def test_linked_device_qr_and_session(tmp_path: Path):
    session_file = tmp_path / "test_session.enc"
    prov = LinkedDeviceWhatsAppProvider(session_file=session_file)

    assert prov.is_connected() is False
    assert prov.get_status()["status"] == WhatsAppConnectionStatus.DISCONNECTED.value

    # Generate QR Code
    qr_code = prov.generate_pairing_qr()
    assert qr_code.startswith("2@")
    assert prov.get_current_qr() == qr_code
    assert prov._status == WhatsAppConnectionStatus.PAIRING_QR

    # Confirm Pairing
    assert prov.confirm_pairing("+989129998877") is True
    assert prov.is_connected() is True
    assert prov.get_status()["paired_phone"] == "+989129998877"

    # Session file was encrypted and written
    assert session_file.exists()

    # Re-instantiate provider from same session file
    prov2 = LinkedDeviceWhatsAppProvider(session_file=session_file)
    assert prov2.is_connected() is True
    assert prov2.get_status()["paired_phone"] == "+989129998877"

    # Disconnect
    prov2.disconnect()
    assert prov2.is_connected() is False
    assert not session_file.exists()


def test_notification_manager_dedup_and_offline_queue(tmp_path: Path):
    queue_file = tmp_path / "offline_queue.json"
    notif_mgr = WhatsAppNotificationManager(queue_file=queue_file)

    # Deduplication test
    assert notif_mgr.is_duplicate("+989121112233", "Hello World") is False
    # Immediately repeated identical message: duplicate
    assert notif_mgr.is_duplicate("+989121112233", "Hello World") is True
    # Different message: not duplicate
    assert notif_mgr.is_duplicate("+989121112233", "Different Message") is False

    # Offline queue test
    notif_mgr.enqueue("+989121112233", "Pending message", priority=1)
    assert len(notif_mgr._offline_queue) == 1
    assert queue_file.exists()

    # Format Antigravity task notifications
    task = AntigravityTaskRecord(
        task_id="agy-task-1234",
        prompt="Refactor database schema",
        workspace_path="C:\\test\\ws",
        state=TaskLifecycleState.COMPLETED,
        verification=TaskVerificationResult(
            verified=True,
            git_changed_files=["models.py", "db.py"],
            tests_executed=True,
            tests_passed=True,
        ),
    )
    formatted = notif_mgr.format_task_notification(task)
    assert "Task Completed Successfully" in formatted
    assert "models.py" in formatted
    assert "All passed" in formatted

    # Failure format
    task_fail = AntigravityTaskRecord(
        task_id="agy-task-5678",
        prompt="Broken prompt",
        workspace_path="C:\\test\\ws",
        state=TaskLifecycleState.FAILED,
        error_message="SyntaxError in tests",
    )
    formatted_fail = notif_mgr.format_task_notification(task_fail)
    assert "Task Failed" in formatted_fail
    assert "SyntaxError in tests" in formatted_fail


def test_inbound_command_handler():
    handler = InboundCommandHandler()
    # Ensure test contacts
    handler.contacts.add_authorized_contact(
        "+989120000099", "Tester", role="admin", can_execute_commands=True
    )

    # 1. Unauthorized attempt
    res_unauth = handler.process_incoming("+989333333333", "status")
    assert res_unauth["authorized"] is False
    assert res_unauth["action"] == "reject"

    # 2. Authorized status command
    res_status = handler.process_incoming("+989120000099", "وضعیت")
    assert res_status["authorized"] is True
    assert res_status["action"] == "reply"
    assert "وضعیت زنده جارویس" in res_status["reply"]

    # 3. Authorized Antigravity trigger command
    res_agy = handler.process_incoming("+989120000099", "کد: تست‌های احراز هویت را بررسی کن")
    assert res_agy["authorized"] is True
    assert res_agy["action"] == "execute_antigravity"
    assert "تست‌های احراز هویت" in res_agy["prompt"]

    # 4. Help command
    res_help = handler.process_incoming("+989120000099", "help")
    assert res_help["authorized"] is True
    assert "دستورات قابل استفاده" in res_help["reply"]


def test_whatsapp_adapter_end_to_end(tmp_path: Path):
    adapter = WhatsAppIntegration()
    # Point linked provider session to tmp
    adapter.linked_provider.session_file = tmp_path / "wa_session.enc"
    adapter.linked_provider.confirm_pairing("+989121112233")
    adapter.contact_mgr.add_authorized_contact(
        "+989121112233", "Owner", role="admin", can_execute_commands=True
    )

    assert adapter.connect() is True
    assert adapter.is_ready_to_send() is True

    # Send message
    res = adapter.execute("send_message", {"recipient": "+989121112233", "text": "Test greeting"})
    assert res.success is True
    assert res.data["recipient"] == "+989121112233"

    # Send task notification
    task = AntigravityTaskRecord(
        task_id="agy-task-9999",
        prompt="E2E test task",
        workspace_path=str(tmp_path),
        state=TaskLifecycleState.COMPLETED,
    )
    res_notif = adapter.execute(
        "send_task_notification", {"task": task, "recipient": "+989121112233"}
    )
    assert res_notif.success is True
    assert res_notif.data["status"] == "sent"
