"""Unit test suite for JARVIS Phase 6 Windows Control subsystem."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from config import Settings
from core.agent import JARVISAgent
from core.execution_context import ExecutionContext
from core.permissions import (
    PermissionCategory,
    PermissionDecision,
    PermissionRequest,
    StrictDefaultDenyPermissionManager,
)
from core.tool_proposal import RiskLevel
from tools.windows.application_tools import (
    AppLaunchInput,
    WindowsAppCloseTool,
    WindowsAppLaunchTool,
    WindowsAppListTool,
)
from tools.windows.audio_tools import (
    AudioMuteInput,
    AudioStatusInput,
    AudioVolumeInput,
    WindowsAudioGetStatusTool,
    WindowsAudioSetMuteTool,
    WindowsAudioSetVolumeTool,
)
from tools.windows.display_tools import (
    BrightnessSetInput,
    BrightnessStatusInput,
    WindowsDisplayGetBrightnessTool,
)
from tools.windows.exceptions import (
    ApplicationNotFoundError,
    ProtectedTargetError,
    TargetValidationError,
)
from tools.windows.models import (
    AudioState,
    BrightnessState,
    PowerState,
    WindowInfo,
    WindowState,
)
from tools.windows.power_tools import (
    PowerActionInput,
    PowerStatusInput,
    WindowsPowerGetStatusTool,
    WindowsPowerRestartTool,
    WindowsPowerShutdownTool,
    WindowsPowerSleepTool,
)
from tools.windows.target_validation import TargetValidator
from tools.windows.window_tools import (
    WindowActionInput,
    WindowListInput,
    WindowsWindowCloseTool,
    WindowsWindowFocusTool,
    WindowsWindowListTool,
    WindowsWindowMaximizeTool,
    WindowsWindowMinimizeTool,
    WindowsWindowRestoreTool,
)
from tools.windows.windows_service import WindowsControlService

# ==============================================================================
# 1. Target Validation & Protected System Boundary Tests
# ==============================================================================


def test_protected_processes_denylist() -> None:
    """Security-critical Windows processes are rejected as targets."""
    for proc in (
        "csrss.exe",
        "lsass.exe",
        "smss.exe",
        "wininit.exe",
        "services.exe",
        "dwm.exe",
        "msmpeng.exe",
        "python.exe",
    ):
        assert TargetValidator.is_protected_process(proc) is True
        with pytest.raises(
            ProtectedTargetError, match="protected Windows system/security component"
        ):
            TargetValidator.validate_process_target(pid=1000, process_name=proc)


def test_core_kernel_pids_rejected() -> None:
    """Kernel and idle PIDs <= 4 are strictly rejected."""
    with pytest.raises(ProtectedTargetError, match="core Windows kernel"):
        TargetValidator.validate_process_target(pid=0, process_name="System Idle Process")
    with pytest.raises(ProtectedTargetError, match="core Windows kernel"):
        TargetValidator.validate_process_target(pid=4, process_name="System")


def test_protected_window_classes_rejected() -> None:
    """Desktop shell surfaces (taskbar, desktop, lock screen) are rejected as window targets."""
    for cls_name in (
        "Shell_TrayWnd",
        "Shell_SecondaryTrayWnd",
        "Progman",
        "WorkerW",
        "LockApp",
        "LogonUI",
    ):
        assert TargetValidator.is_protected_window_class(cls_name) is True
        with pytest.raises(ProtectedTargetError, match="protected shell class"):
            TargetValidator.validate_window_handle(hwnd=12345, class_name=cls_name)


def test_window_handle_validation_stale_or_invalid() -> None:
    """Non-existent or zero window handles raise TargetValidationError."""
    with pytest.raises(TargetValidationError, match="Invalid window handle"):
        TargetValidator.validate_window_handle(hwnd=0)
    with pytest.raises(TargetValidationError, match="stale or does not exist"):
        TargetValidator.validate_window_handle(hwnd=999999999)


def test_executable_path_validation(tmp_path: Path) -> None:
    """Executable path must exist, have .exe extension, and not be a protected binary."""
    # Non-existent
    with pytest.raises(TargetValidationError, match="does not exist"):
        TargetValidator.validate_executable_path(str(tmp_path / "ghost.exe"))

    # Non-exe script
    script = tmp_path / "bad.bat"
    script.write_text("echo bad", encoding="utf-8")
    with pytest.raises(TargetValidationError, match="Only native Windows executables"):
        TargetValidator.validate_executable_path(str(script))

    # Protected binary name
    fake_csrss = tmp_path / "csrss.exe"
    fake_csrss.write_bytes(b"MZ\x00\x00")
    with pytest.raises(ProtectedTargetError, match="protected system process list"):
        TargetValidator.validate_executable_path(str(fake_csrss))


# ==============================================================================
# 2. Native Application Management Tests
# ==============================================================================


def test_application_allowlist_enforcement() -> None:
    """Applications not in the configured allowlist are rejected immediately."""
    settings = Settings(windows_app_allowlist=["notepad", "calc"])
    svc = WindowsControlService(settings=settings)

    with pytest.raises(ApplicationNotFoundError, match="not present in the configured allowlist"):
        svc.resolve_application("malicious_hacker_tool")


def test_resolve_standard_application() -> None:
    """Standard Windows application like Notepad resolves to valid AppInfo."""
    settings = Settings(windows_app_allowlist=["notepad"])
    svc = WindowsControlService(settings=settings)
    app = svc.resolve_application("notepad")

    assert app.app_id == "notepad"
    assert app.display_name == "Notepad"
    assert app.is_installed is True
    assert app.executable_path.lower().endswith(".exe")


def test_application_launch_and_close_tools_schema() -> None:
    """Pydantic schemas and ToolDefinitions for app tools are valid."""
    list_tool = WindowsAppListTool()
    launch_tool = WindowsAppLaunchTool()
    close_tool = WindowsAppCloseTool()

    assert list_tool.category == PermissionCategory.WINDOWS_APP_READ
    assert launch_tool.category == PermissionCategory.WINDOWS_APP_LAUNCH
    assert close_tool.category == PermissionCategory.WINDOWS_APP_CLOSE

    assert launch_tool.get_definition().risk_level == RiskLevel.HIGH
    assert launch_tool.get_definition().requires_approval is True
    assert close_tool.get_definition().risk_level == RiskLevel.HIGH
    assert close_tool.get_definition().requires_approval is True


def test_app_launch_disabled_by_policy() -> None:
    """When windows_app_launch_enabled is False, launch fails closed."""
    settings = Settings(windows_app_launch_enabled=False)
    svc = WindowsControlService(settings=settings)
    tool = WindowsAppLaunchTool(service=svc)

    res = tool.execute(AppLaunchInput(app_id="notepad"), context=ExecutionContext())
    assert res.status == "failed"
    assert "disabled by user policy" in res.error


# ==============================================================================
# 3. Window Management Tests
# ==============================================================================


def test_window_tools_definitions() -> None:
    """Window tools have correct definitions, categories, and approval policies."""
    list_tool = WindowsWindowListTool()
    focus_tool = WindowsWindowFocusTool()
    min_tool = WindowsWindowMinimizeTool()
    max_tool = WindowsWindowMaximizeTool()
    restore_tool = WindowsWindowRestoreTool()
    close_tool = WindowsWindowCloseTool()

    assert list_tool.category == PermissionCategory.WINDOWS_WINDOW_READ
    assert focus_tool.category == PermissionCategory.WINDOWS_WINDOW_CONTROL
    assert close_tool.category == PermissionCategory.WINDOWS_WINDOW_CONTROL

    assert list_tool.get_definition().requires_approval is False
    assert focus_tool.get_definition().requires_approval is False
    assert min_tool.get_definition().requires_approval is False
    assert max_tool.get_definition().requires_approval is False
    assert restore_tool.get_definition().requires_approval is False
    assert close_tool.get_definition().requires_approval is True
    assert close_tool.get_definition().risk_level == RiskLevel.HIGH


def test_window_operations_with_mocked_service() -> None:
    """Window operations correctly invoke underlying WindowsControlService methods."""
    mock_svc = MagicMock()
    mock_svc.find_windows.return_value = [
        WindowInfo(
            hwnd=1001,
            title="Document - Notepad",
            class_name="Notepad",
            pid=5000,
            process_name="notepad.exe",
            state=WindowState.NORMAL,
        )
    ]
    mock_svc.focus_window.return_value = True
    mock_svc.minimize_window.return_value = True
    mock_svc.maximize_window.return_value = True
    mock_svc.restore_window.return_value = True
    mock_svc.close_window.return_value = True

    ctx = ExecutionContext()
    list_res = WindowsWindowListTool(service=mock_svc).execute(
        WindowListInput(query="Notepad"), ctx
    )
    assert list_res.status == "success"
    assert len(list_res.data) == 1
    assert list_res.data[0]["hwnd"] == 1001

    focus_res = WindowsWindowFocusTool(service=mock_svc).execute(WindowActionInput(hwnd=1001), ctx)
    assert focus_res.status == "success"
    mock_svc.focus_window.assert_called_once_with(1001)

    min_res = WindowsWindowMinimizeTool(service=mock_svc).execute(WindowActionInput(hwnd=1001), ctx)
    assert min_res.status == "success"
    mock_svc.minimize_window.assert_called_once_with(1001)

    close_res = WindowsWindowCloseTool(service=mock_svc).execute(WindowActionInput(hwnd=1001), ctx)
    assert close_res.status == "success"
    mock_svc.close_window.assert_called_once_with(1001)


# ==============================================================================
# 4. Audio Control Tests
# ==============================================================================


def test_audio_tools_schemas_and_ranges() -> None:
    """Audio input schemas validate percentages strictly (0.0 to 100.0)."""
    # Valid
    v1 = AudioVolumeInput(percent=45.5)
    assert v1.percent == 45.5

    # Out of bounds
    with pytest.raises(ValidationError):
        AudioVolumeInput(percent=-5.0)
    with pytest.raises(ValidationError):
        AudioVolumeInput(percent=105.0)


def test_audio_status_and_volume_tools() -> None:
    """Audio get, set volume, and set mute tools execute accurately."""
    mock_svc = MagicMock()
    mock_svc.get_audio_status.return_value = AudioState(volume_percent=60.0, is_muted=False)
    mock_svc.set_volume.return_value = AudioState(volume_percent=75.0, is_muted=False)
    mock_svc.set_mute.return_value = AudioState(volume_percent=75.0, is_muted=True)

    ctx = ExecutionContext()
    get_tool = WindowsAudioGetStatusTool(service=mock_svc)
    res_get = get_tool.execute(AudioStatusInput(), ctx)
    assert res_get.status == "success"
    assert res_get.data["volume_percent"] == 60.0

    set_vol_tool = WindowsAudioSetVolumeTool(service=mock_svc)
    res_vol = set_vol_tool.execute(AudioVolumeInput(percent=75.0), ctx)
    assert res_vol.status == "success"
    assert res_vol.data["volume_percent"] == 75.0
    mock_svc.set_volume.assert_called_once_with(75.0)

    set_mute_tool = WindowsAudioSetMuteTool(service=mock_svc)
    res_mute = set_mute_tool.execute(AudioMuteInput(mute=True), ctx)
    assert res_mute.status == "success"
    assert res_mute.data["is_muted"] is True
    mock_svc.set_mute.assert_called_once_with(True)


# ==============================================================================
# 5. Display Brightness Tests
# ==============================================================================


def test_display_brightness_graceful_unsupported_handling() -> None:
    """When physical monitor brightness is unsupported, tool reports unsupported without simulating success."""
    mock_svc = MagicMock()
    mock_svc.get_brightness.return_value = BrightnessState(
        supported=False,
        error_reason="Display driver or monitor bus does not expose physical monitor handles.",
    )

    ctx = ExecutionContext()
    tool = WindowsDisplayGetBrightnessTool(service=mock_svc)
    res = tool.execute(BrightnessStatusInput(), ctx)
    assert res.status == "success"
    assert res.data["supported"] is False
    assert "does not expose" in res.data["error_reason"]


def test_display_set_brightness_validation() -> None:
    """Brightness input validates 0 to 100 range."""
    with pytest.raises(ValidationError):
        BrightnessSetInput(percent=-10)
    with pytest.raises(ValidationError):
        BrightnessSetInput(percent=110)


# ==============================================================================
# 6. Power-State Operations Tests
# ==============================================================================


def test_power_status_query() -> None:
    """Power status query returns structured PowerState."""
    mock_svc = MagicMock()
    mock_svc.get_power_status.return_value = PowerState(
        ac_line_status="online",
        battery_percent=100,
        battery_status="charging",
    )

    ctx = ExecutionContext()
    tool = WindowsPowerGetStatusTool(service=mock_svc)
    res = tool.execute(PowerStatusInput(), ctx)
    assert res.status == "success"
    assert res.data["ac_line_status"] == "online"
    assert res.data["battery_percent"] == 100


def test_disruptive_power_tools_require_critical_approval() -> None:
    """Sleep, restart, and shutdown require CRITICAL risk approval and warn about unsaved work."""
    sleep_tool = WindowsPowerSleepTool()
    restart_tool = WindowsPowerRestartTool()
    shutdown_tool = WindowsPowerShutdownTool()

    assert sleep_tool.get_definition().risk_level == RiskLevel.CRITICAL
    assert sleep_tool.get_definition().requires_approval is True

    assert restart_tool.get_definition().risk_level == RiskLevel.CRITICAL
    assert restart_tool.get_definition().requires_approval is True

    assert shutdown_tool.get_definition().risk_level == RiskLevel.CRITICAL
    assert shutdown_tool.get_definition().requires_approval is True


# ==============================================================================
# 7. Security: Default-Deny & Granular Permissions
# ==============================================================================


def test_permission_manager_default_deny_blocks_windows_tools() -> None:
    """Without explicit permission, Windows Control tools are denied by default."""
    pm = StrictDefaultDenyPermissionManager()  # Empty allowed categories

    req = PermissionRequest(
        tool_name="windows_app_launch",
        category=PermissionCategory.WINDOWS_APP_LAUNCH,
        action_summary="Launch Notepad",
        parameters={"app_id": "notepad"},
    )
    result = pm.evaluate(req)
    assert result.decision == PermissionDecision.DENIED
    assert "default-deny security policy" in result.reason


def test_permission_manager_grant_and_revoke_category() -> None:
    """Granting a granular Windows category allows its tools; revoking denies them."""
    pm = StrictDefaultDenyPermissionManager()

    # 1. Grant WINDOWS_AUDIO_READ
    pm.grant(PermissionCategory.WINDOWS_AUDIO_READ)
    req = PermissionRequest(
        tool_name="windows_audio_get_status",
        category=PermissionCategory.WINDOWS_AUDIO_READ,
        action_summary="Get audio volume",
    )
    assert pm.evaluate(req).decision == PermissionDecision.GRANTED

    # 2. WINDOWS_AUDIO_CONTROL remains denied
    req_ctrl = PermissionRequest(
        tool_name="windows_audio_set_volume",
        category=PermissionCategory.WINDOWS_AUDIO_CONTROL,
        action_summary="Set volume",
        parameters={"percent": 50},
    )
    assert pm.evaluate(req_ctrl).decision == PermissionDecision.DENIED

    # 3. Revoke
    pm.revoke(PermissionCategory.WINDOWS_AUDIO_READ)
    assert pm.evaluate(req).decision == PermissionDecision.DENIED


def test_single_use_proposal_approval_with_parameter_tampering() -> None:
    """Modifying parameters after approval invalidates execution authorization."""
    pm = StrictDefaultDenyPermissionManager()

    # Grant proposal for volume 30
    pm.grant_proposal("prop-01", "windows_audio_set_volume", {"percent": 30.0})

    # Tampered parameter 80.0
    req_tampered = PermissionRequest(
        tool_name="windows_audio_set_volume",
        category=PermissionCategory.WINDOWS_AUDIO_CONTROL,
        action_summary="Set volume",
        parameters={"percent": 80.0, "_proposal_id": "prop-01"},
    )
    result = pm.evaluate(req_tampered)
    assert result.decision == PermissionDecision.DENIED
    assert "parameters or tool tampered after approval" in result.reason


# ==============================================================================
# 8. Agent Core & Tool Registry Integration
# ==============================================================================


def test_agent_registers_phase6_windows_tools() -> None:
    """JARVISAgent registers all Phase 6 Windows control tools when enabled in settings."""
    settings = Settings(windows_control_enabled=True)
    agent = JARVISAgent(settings=settings)

    registered_names = agent.tool_registry.list_tool_names()
    expected_tools = [
        "windows_app_list",
        "windows_app_launch",
        "windows_app_close",
        "windows_window_list",
        "windows_window_focus",
        "windows_window_minimize",
        "windows_window_maximize",
        "windows_window_restore",
        "windows_window_close",
        "windows_audio_get_status",
        "windows_audio_set_volume",
        "windows_audio_set_mute",
        "windows_display_get_brightness",
        "windows_display_set_brightness",
        "windows_power_get_status",
        "windows_power_lock",
        "windows_power_sleep",
        "windows_power_restart",
        "windows_power_shutdown",
    ]
    for tool_name in expected_tools:
        assert tool_name in registered_names, (
            f"Expected tool '{tool_name}' not registered in JARVISAgent"
        )


# ==============================================================================
# 9. Final Security Closure Verification Tests
# ==============================================================================


def test_power_restart_and_shutdown_require_explicit_confirmation() -> None:
    """Restart and shutdown strictly require confirmed=True; false or omitted is denied."""
    mock_svc = MagicMock()
    ctx = ExecutionContext()

    restart_tool = WindowsPowerRestartTool(service=mock_svc)
    shutdown_tool = WindowsPowerShutdownTool(service=mock_svc)

    # 1. Unconfirmed restart
    res_restart_unconfirmed = restart_tool.execute(PowerActionInput(confirmed=False), ctx)
    assert res_restart_unconfirmed.status == "denied"
    assert "explicit confirmation" in res_restart_unconfirmed.error.lower()
    mock_svc.restart.assert_not_called()

    # 2. Confirmed restart
    res_restart_confirmed = restart_tool.execute(PowerActionInput(confirmed=True), ctx)
    assert res_restart_confirmed.status == "success"
    mock_svc.restart.assert_called_once_with(force=False)

    # 3. Unconfirmed shutdown
    res_shutdown_unconfirmed = shutdown_tool.execute(PowerActionInput(confirmed=False), ctx)
    assert res_shutdown_unconfirmed.status == "denied"
    assert "explicit confirmation" in res_shutdown_unconfirmed.error.lower()
    mock_svc.shutdown.assert_not_called()

    # 4. Confirmed shutdown
    res_shutdown_confirmed = shutdown_tool.execute(PowerActionInput(confirmed=True), ctx)
    assert res_shutdown_confirmed.status == "success"
    mock_svc.shutdown.assert_called_once_with(force=False)


def test_reparse_point_ancestor_traversal_blocked(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Executable located within a reparse point / junction ancestor directory must be blocked."""
    test_exe = tmp_path / "subdir" / "fake_app.exe"
    test_exe.parent.mkdir(parents=True)
    test_exe.write_bytes(b"MZ")

    real_lstat = os.lstat

    class FakeStat:
        def __init__(self, is_reparse: bool) -> None:
            self.st_file_attributes = 0x00000400 if is_reparse else 0x00000080

    def mock_lstat(path_str: str) -> Any:
        # Simulate ancestor directory "subdir" being a reparse point
        if Path(path_str).name == "subdir":
            return FakeStat(is_reparse=True)
        return real_lstat(path_str)

    monkeypatch.setattr(os, "lstat", mock_lstat)

    with pytest.raises(TargetValidationError) as exc_info:
        TargetValidator.validate_executable_path(str(test_exe))
    assert "reparse point or junction" in str(exc_info.value).lower()


def test_pid_reuse_defense_process_creation_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """PID reuse is detected and blocked when process creation time does not match expected value."""
    # Mock get_process_creation_time to return timestamp 100000
    monkeypatch.setattr(TargetValidator, "get_process_creation_time", lambda pid: 100000)

    # 1. Matching creation time passes
    TargetValidator.validate_process_target(
        pid=9999, process_name="custom.exe", expected_creation_time=100000
    )

    # 2. Mismatched creation time fails
    with pytest.raises(TargetValidationError) as exc_info:
        TargetValidator.validate_process_target(
            pid=9999, process_name="custom.exe", expected_creation_time=200000
        )
    assert "mismatch for pid 9999" in str(exc_info.value).lower()
    assert (
        "pid reuse detected" in str(exc_info.value).lower()
        or "pid was likely reused" in str(exc_info.value).lower()
    )


def test_approval_manager_session_mismatch_and_single_use() -> None:
    """Approval decisions reject session mismatches, and granted proposals can only be used once."""
    from core.approval import ApprovalManager
    from core.tool_proposal import RiskLevel, ToolProposal

    pm = StrictDefaultDenyPermissionManager()
    mgr = ApprovalManager(permission_manager=pm)

    prop = ToolProposal(
        session_id="session-alpha",
        tool_name="windows_power_lock",
        arguments={},
        risk_level=RiskLevel.HIGH,
    )

    # Background wait thread
    import threading

    decision_result = []

    def wait_worker() -> None:
        approved = mgr.request_approval(prop, timeout=2.0)
        decision_result.append(approved)

    t = threading.Thread(target=wait_worker)
    t.start()
    time.sleep(0.05)

    # 1. Reject session mismatch
    wrong_session_res = mgr.submit_decision(
        proposal_id=prop.proposal_id,
        approved=True,
        session_id="session-bravo",
    )
    assert wrong_session_res is False

    # 2. Approve with correct session
    right_session_res = mgr.submit_decision(
        proposal_id=prop.proposal_id,
        approved=True,
        session_id="session-alpha",
    )
    assert right_session_res is True

    t.join(timeout=2.0)
    assert decision_result == [True]

    # 3. Single-use consumption in PermissionManager
    req = PermissionRequest(
        tool_name="windows_power_lock",
        category=PermissionCategory.WINDOWS_POWER_CONTROL,
        action_summary="Lock workstation",
        parameters={"_proposal_id": prop.proposal_id},
    )
    res1 = pm.evaluate(req)
    assert res1.decision == PermissionDecision.GRANTED

    # 4. Duplicate consumption is strictly DENIED
    res2 = pm.evaluate(req)
    assert res2.decision == PermissionDecision.DENIED


def test_approval_card_widget_two_step_confirmation(qtbot: Any) -> None:
    """ApprovalCardWidget for restart/shutdown requires acknowledgment checkbox before Approve is enabled."""
    from ui.chat_panel import ApprovalCardWidget

    card = ApprovalCardWidget(
        proposal_id="prop-pwr-1",
        tool_name="windows_power_restart",
        arguments={"force": False},
        risk_level="CRITICAL",
        rationale="Restart system to apply updates",
        session_id="session-1",
    )
    qtbot.addWidget(card)

    # 1. Warning and Checkbox exist
    assert hasattr(card, "confirm_checkbox")
    assert card.confirm_checkbox is not None
    assert "unsaved work will be lost" in card.confirm_checkbox.text().lower()

    # 2. Approve button is disabled initially
    assert not card.approve_btn.isEnabled()

    # 3. Toggling checkbox enables Approve button
    card.confirm_checkbox.setChecked(True)
    assert card.approve_btn.isEnabled()

    # 4. Untoggling checkbox disables Approve button again
    card.confirm_checkbox.setChecked(False)
    assert not card.approve_btn.isEnabled()
    card.close()
