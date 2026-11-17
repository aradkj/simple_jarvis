"""End-to-end integration tests for Antigravity-to-WhatsApp Multi-Tool Orchestration."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from integrations.antigravity.adapter import get_antigravity_integration
from integrations.orchestrator import MultiToolOrchestrator
from integrations.whatsapp.adapter import get_whatsapp_integration


def test_orchestration_success_pipeline(tmp_path: Path):
    orch = MultiToolOrchestrator()
    agy = get_antigravity_integration()
    wa = get_whatsapp_integration()

    # Pair WhatsApp in linked device mode
    wa.linked_provider.session_file = tmp_path / "orch_session.enc"
    wa.linked_provider.confirm_pairing("+989121112233")
    wa.contact_mgr.add_authorized_contact(
        "+989121112233", "Owner", role="admin", can_execute_commands=True
    )
    wa.connect()

    # Mock CLI execute to succeed
    with patch.object(agy.cli, "execute_task", return_value=(0, ["All tests passed cleanly."])):
        job = orch.run_antigravity_with_whatsapp_alert(
            prompt="Refactor authentication middleware",
            workspace_path=tmp_path,
            recipient="+989121112233",
            auto_verify=False,
        )

        # Wait for background thread completion
        for _ in range(50):
            if job.status in ("completed", "failed"):
                break
            time.sleep(0.05)

        assert job.status == "completed"
        assert job.notification_status == "sent"
        assert job.task_id is not None


def test_orchestration_antigravity_failure_alert(tmp_path: Path):
    orch = MultiToolOrchestrator()
    agy = get_antigravity_integration()
    wa = get_whatsapp_integration()

    # WhatsApp is connected
    wa.linked_provider.session_file = tmp_path / "orch_session.enc"
    wa.linked_provider.confirm_pairing("+989121112233")
    wa.connect()

    # Mock CLI execute to fail with exit code 1
    with patch.object(
        agy.cli, "execute_task", return_value=(1, ["Fatal Error: compilation failed."])
    ):
        job = orch.run_antigravity_with_whatsapp_alert(
            prompt="Faulty prompt",
            workspace_path=tmp_path,
            recipient="+989121112233",
            auto_verify=False,
        )

        for _ in range(50):
            if job.status in ("completed", "failed"):
                break
            time.sleep(0.05)

        # Job correctly reports failure
        assert job.status == "failed"
        # Notification of failure was still dispatched to WhatsApp
        assert job.notification_status == "sent"


def test_orchestration_whatsapp_offline_queues_notification(tmp_path: Path):
    orch = MultiToolOrchestrator()
    agy = get_antigravity_integration()
    wa = get_whatsapp_integration()

    # Disconnect WhatsApp
    wa.disconnect()
    assert wa.is_ready_to_send() is False

    # Mock CLI execute to succeed
    with patch.object(agy.cli, "execute_task", return_value=(0, ["Task finished."])):
        job = orch.run_antigravity_with_whatsapp_alert(
            prompt="Task when WhatsApp offline",
            workspace_path=tmp_path,
            recipient="+989121112233",
            auto_verify=False,
        )

        for _ in range(50):
            if job.status in ("completed", "failed"):
                break
            time.sleep(0.05)

        # Antigravity task finished without disruption
        assert job.status == "completed"
        # Notification was enqueued in offline queue
        assert len(wa.notification_mgr._offline_queue) >= 1
