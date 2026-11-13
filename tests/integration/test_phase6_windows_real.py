"""Integration tests for JARVIS Phase 6 with safe real Windows APIs and Agent pipeline."""

from __future__ import annotations

import contextlib
import os
from unittest.mock import MagicMock

import pytest

from config import Settings
from core.approval import ApprovalManager
from core.execution_context import ExecutionContext
from core.executor import AgentExecutor
from core.permissions import PermissionCategory
from core.planner import AgentPlanner, Plan, PlanStep, StepStatus, StepType
from core.state_machine import AgentStateMachine
from core.tool_registry import ToolRegistry
from tools.windows.models import WindowState
from tools.windows.windows_service import WindowsControlService


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific native tests")
def test_real_windows_service_app_catalog_discovery() -> None:
    """WindowsControlService discovers standard applications installed on Windows 11."""
    svc = WindowsControlService()
    catalog = svc.get_application_catalog()
    assert len(catalog) > 0

    app_ids = [a.app_id for a in catalog]
    assert "notepad" in app_ids
    notepad = next(a for a in catalog if a.app_id == "notepad")
    assert notepad.is_installed is True
    assert notepad.executable_path.lower().endswith(".exe")


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific native tests")
def test_real_windows_service_window_enumeration() -> None:
    """WindowsControlService enumerates real top-level desktop windows."""
    svc = WindowsControlService()
    windows = svc.list_windows()
    # Desktop will have at least one window (e.g. explorer, terminal, IDE)
    assert isinstance(windows, list)
    assert len(windows) > 0

    first_win = windows[0]
    assert first_win.hwnd > 0
    assert isinstance(first_win.title, str)
    assert isinstance(first_win.pid, int)
    assert first_win.state in (
        WindowState.NORMAL,
        WindowState.MINIMIZED,
        WindowState.MAXIMIZED,
        WindowState.HIDDEN,
    )


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific native tests")
def test_real_windows_service_audio_status_query() -> None:
    """WindowsControlService reads actual master volume and mute state via Core Audio COM."""
    svc = WindowsControlService()
    try:
        status = svc.get_audio_status()
    except Exception as exc:
        pytest.skip(f"Windows Core Audio default playback endpoint not available: {exc}")
    assert status.supported is True
    assert 0.0 <= status.volume_percent <= 100.0
    assert isinstance(status.is_muted, bool)


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific native tests")
def test_real_windows_service_power_status_query() -> None:
    """WindowsControlService reads system power status from kernel32."""
    svc = WindowsControlService()
    power = svc.get_power_status()
    assert power.ac_line_status in ("online", "offline", "unknown")
    assert 0 <= power.battery_percent <= 100
    assert power.battery_status in ("charging", "discharging", "no_battery", "critical", "unknown")


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific native tests")
def test_real_windows_service_display_brightness_graceful() -> None:
    """WindowsControlService queries display brightness without raising unhandled exceptions."""
    svc = WindowsControlService()
    brightness = svc.get_brightness()
    assert isinstance(brightness.supported, bool)
    if brightness.supported:
        assert brightness.brightness_percent is not None
        assert 0 <= brightness.brightness_percent <= 100
    else:
        assert brightness.error_reason is not None


def test_agent_executor_high_risk_approval_lifecycle_mock() -> None:
    """High-risk Windows tool proposal awaits approval and respects user rejection."""
    mock_pm = MagicMock()
    mock_pm.is_ready.return_value = True

    tool_registry = ToolRegistry()
    mock_launch_tool = MagicMock()
    mock_launch_tool.name = "windows_app_launch"
    mock_launch_tool.category = PermissionCategory.WINDOWS_APP_LAUNCH
    mock_launch_tool.get_definition.return_value = MagicMock(
        risk_level=MagicMock(value="high"),
        requires_approval=True,
    )
    tool_registry.register(mock_launch_tool)

    app_mgr = ApprovalManager()
    state_machine = AgentStateMachine()
    settings = Settings(windows_control_enabled=True)

    executor = AgentExecutor(
        tool_registry=tool_registry,
        provider_manager=mock_pm,
        planner=AgentPlanner(provider_manager=mock_pm, settings=settings),
        state_machine=state_machine,
        approval_manager=app_mgr,
        settings=settings,
    )

    plan = Plan(goal="Launch Notepad", session_id="test-session")
    step = PlanStep(
        description="Launch Notepad application",
        step_type=StepType.TOOL_CALL,
        tool_name="windows_app_launch",
        parameters={"app_id": "notepad"},
    )
    plan.add_step(step)

    # Execute without waiting for approval -> returns waiting_for_approval
    ctx = ExecutionContext(session_id="test-session")
    outcome = executor.execute_plan(plan, context=ctx, wait_for_approval=False)
    assert outcome.status == "waiting_for_approval"
    assert step.status == StepStatus.WAITING_APPROVAL
    assert outcome.pending_approval is not None
    assert outcome.pending_approval.tool_name == "windows_app_launch"


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific native tests")
def test_real_windows_audio_reversible_mutation() -> None:
    """Safely inspect real Windows master audio, perform tiny reversible mutation, and restore original state in finally."""
    import time

    svc = WindowsControlService()
    try:
        status = svc.get_audio_status()
        if not status.supported:
            pytest.skip("Windows Core Audio endpoint is not supported on this device/session.")
    except Exception as exc:
        pytest.skip(f"Windows Core Audio default playback endpoint not available: {exc}")

    original_volume = status.volume_percent
    original_muted = status.is_muted

    try:
        # Determine target test volume: shift by 2.0% within bounds
        delta = 2.0 if original_volume <= 90.0 else -2.0
        test_volume = max(0.0, min(100.0, original_volume + delta))

        # 1. Mutate volume
        set_res = svc.set_volume(test_volume)
        assert abs(set_res.volume_percent - test_volume) <= 2.5
        time.sleep(0.1)

        # 2. Verify volume mutated
        new_status = svc.get_audio_status()
        assert abs(new_status.volume_percent - test_volume) <= 2.5

        # 3. Mutate mute state
        test_mute = not original_muted
        mute_res = svc.set_mute(test_mute)
        assert mute_res.is_muted == test_mute
        time.sleep(0.1)

        muted_status = svc.get_audio_status()
        assert muted_status.is_muted == test_mute

    finally:
        # Guaranteed restoration of original audio configuration
        with contextlib.suppress(Exception):
            svc.set_volume(original_volume)
            svc.set_mute(original_muted)

    # Verify restored
    restored_status = svc.get_audio_status()
    assert abs(restored_status.volume_percent - original_volume) <= 2.5
    assert restored_status.is_muted == original_muted


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific native tests")
def test_real_windows_application_launch_minimize_restore_and_close() -> None:
    """Launch notepad.exe, test minimize & restore on its real window, and gracefully close it in finally."""
    import time

    svc = WindowsControlService()
    app_info = svc.resolve_application("notepad")
    if not app_info.is_installed:
        pytest.skip("Notepad application is not installed on this system.")

    launched_pid: int | None = None
    target_hwnd: int | None = None

    try:
        # 1. Launch notepad.exe
        launch_res = svc.launch_application("notepad")
        launched_pid = launch_res.get("pid")
        assert launched_pid is not None and launched_pid > 0

        # Wait for window to appear
        for _ in range(30):
            time.sleep(0.2)
            windows = svc.find_windows(pid=launched_pid)
            if windows:
                target_hwnd = windows[0].hwnd
                break

        if target_hwnd is not None:
            # 2. Test minimize window
            assert svc.minimize_window(target_hwnd) is True
            time.sleep(0.2)

            # 3. Test restore window
            assert svc.restore_window(target_hwnd) is True
            time.sleep(0.2)

    finally:
        # Guaranteed cleanup: close launched application instances gracefully
        if launched_pid is not None:
            with contextlib.suppress(Exception):
                svc.close_application("notepad", pid=launched_pid, graceful=True)

        time.sleep(0.5)
        remaining = svc.find_windows(pid=launched_pid) if launched_pid else []
        for w in remaining:
            with contextlib.suppress(Exception):
                svc.close_window(w.hwnd, graceful=True)
