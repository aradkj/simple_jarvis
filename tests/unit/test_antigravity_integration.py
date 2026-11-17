"""Unit tests for Google Antigravity Integration (CLI, IDE, Lifecycle, Workspace Lock, Verifier)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from integrations.antigravity.adapter import AntigravityIntegration
from integrations.antigravity.cli import AntigravityCLI
from integrations.antigravity.ide import AntigravityIDEManager
from integrations.antigravity.lifecycle import (
    AntigravityLifecycleTracker,
    TaskLifecycleState,
)
from integrations.antigravity.verifier import AntigravityVerifier, TaskVerificationResult
from integrations.antigravity.workspace_lock import WorkspaceLockManager
from integrations.base import HealthState


def test_cli_discovery(tmp_path: Path):
    cli = AntigravityCLI()
    if not cli.is_available():
        mock_agy = tmp_path / "agy.exe"
        mock_agy.write_text("@echo off\n", encoding="utf-8")
        cli.executable_path = mock_agy
        with patch.object(cli, "detect_version", return_value="1.5.10"):
            exe = cli.locate_executable()
            assert exe.is_file()
            assert cli.is_available() is True
            assert cli.detect_version() == "1.5.10"
        return

    # The environment has agy.exe at C:\Users\aradb\AppData\Local\agy\bin\agy.exe
    exe = cli.locate_executable()
    assert exe.is_file()
    assert cli.is_available() is True
    version = cli.detect_version()
    assert version != "unknown"


def test_workspace_locking(tmp_path: Path):
    lock_mgr = WorkspaceLockManager()
    ws = tmp_path / "test_workspace"
    ws.mkdir()

    task1 = "task-1"
    task2 = "task-2"

    assert lock_mgr.is_locked(ws) is False
    assert lock_mgr.acquire(ws, task1) is True
    assert lock_mgr.is_locked(ws) is True
    assert lock_mgr.get_locking_task(ws) == task1

    # Second acquisition by another task should fail
    assert lock_mgr.acquire(ws, task2, timeout=0.1) is False

    # Release by task1
    lock_mgr.release(ws, task1)
    assert lock_mgr.is_locked(ws) is False

    # Context manager test
    with lock_mgr.lock_workspace(ws, task1):
        assert lock_mgr.is_locked(ws) is True
    assert lock_mgr.is_locked(ws) is False


def test_lifecycle_tracker(tmp_path: Path):
    tracker = AntigravityLifecycleTracker()
    task = tracker.create_task(prompt="Fix tests", workspace_path=tmp_path, model="inherit")
    assert task.task_id.startswith("agy-task-")
    assert task.state == TaskLifecycleState.CREATED

    tracker.transition(task.task_id, TaskLifecycleState.ACCEPTED)
    assert task.state == TaskLifecycleState.ACCEPTED

    tracker.transition(task.task_id, TaskLifecycleState.STARTED)
    assert task.state == TaskLifecycleState.STARTED
    assert task.started_at is not None

    tracker.append_output(task.task_id, "Running linter...")
    assert len(task.output_log) == 1

    tracker.transition(task.task_id, TaskLifecycleState.COMPLETED)
    assert task.state == TaskLifecycleState.COMPLETED
    assert task.completed_at is not None
    assert task.duration_seconds() >= 0.0


def test_ide_hooks_lifecycle(tmp_path: Path):
    manager = AntigravityIDEManager()
    ws = tmp_path / "ide_workspace"
    ws.mkdir()
    agents_dir = ws / ".agents"
    agents_dir.mkdir()
    agents_dir / "hooks.json"

    # Initially hooks don't exist
    status1 = manager.get_hooks_status(ws)
    assert status1["exists"] is False
    assert status1["jarvis_hooks_installed"] is False

    # Install hooks
    assert manager.install_hooks(ws) is True
    status2 = manager.get_hooks_status(ws)
    assert status2["exists"] is True
    assert status2["jarvis_hooks_installed"] is True

    # Backup file should be created on next update
    assert manager.install_hooks(ws) is True
    bak_file = agents_dir / "hooks.json.bak"
    assert bak_file.exists()

    # Uninstall hooks
    assert manager.uninstall_hooks(ws) is True
    status3 = manager.get_hooks_status(ws)
    assert status3["jarvis_hooks_installed"] is False


def test_verifier(tmp_path: Path):
    verifier = AntigravityVerifier(tmp_path)
    # Temporary non-git directory
    res = verifier.verify(run_tests=False, run_linter=False)
    assert isinstance(res, TaskVerificationResult)
    assert res.verified is True
    assert "No file changes detected" in res.message


def test_adapter_operations(tmp_path: Path):
    adapter = AntigravityIntegration()
    if not adapter.cli.is_available():
        mock_agy = tmp_path / "agy.exe"
        mock_agy.write_text("@echo off\n", encoding="utf-8")
        adapter.cli.executable_path = mock_agy
        with patch.object(adapter.cli, "detect_version", return_value="1.5.10"):
            assert adapter.connect() is True
            assert adapter.health_state == HealthState.HEALTHY
            status = adapter.get_status()
            assert status["connected"] is True
            assert status["cli_available"] is True
            caps = adapter.get_capabilities()
            assert "delegate_task" in caps.operations
            assert "verify_workspace" in caps.operations
            assert "install_ide_hooks" in caps.operations
            with patch.object(adapter.cli, "execute_task", return_value=(0, ["Done."])):
                res = adapter.execute(
                    "delegate_task",
                    {"prompt": "Echo test", "workspace_path": str(tmp_path), "auto_verify": False},
                )
                assert res.success is True
                assert res.data["exit_code"] == 0
                task_id = res.data["task_id"]
                st_res = adapter.execute("get_task_status", {"task_id": task_id})
                assert st_res.success is True
                assert st_res.data["state"] == TaskLifecycleState.COMPLETED.value
            return

    assert adapter.connect() is True
    assert adapter.health_state == HealthState.HEALTHY

    # Status
    status = adapter.get_status()
    assert status["connected"] is True
    assert status["cli_available"] is True

    # Capabilities
    caps = adapter.get_capabilities()
    assert "delegate_task" in caps.operations
    assert "verify_workspace" in caps.operations
    assert "install_ide_hooks" in caps.operations

    # Mock CLI execute to test end-to-end delegation without real LLM call
    with patch.object(adapter.cli, "execute_task", return_value=(0, ["Done."])):
        res = adapter.execute(
            "delegate_task",
            {"prompt": "Echo test", "workspace_path": str(tmp_path), "auto_verify": False},
        )
        assert res.success is True
        assert res.data["exit_code"] == 0
        task_id = res.data["task_id"]

        # Check task status
        st_res = adapter.execute("get_task_status", {"task_id": task_id})
        assert st_res.success is True
        assert st_res.data["state"] == TaskLifecycleState.COMPLETED.value
