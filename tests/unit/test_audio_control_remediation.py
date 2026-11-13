"""Unit tests for JARVIS Windows Audio Control & Truthful Action Verification Remediation."""

from __future__ import annotations

import threading
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from core.agent import JARVISAgent
from core.execution_context import ExecutionContext
from core.permissions import PermissionCategory, PermissionRequest
from core.planner import AgentPlanner
from tools.base import ToolExecutionStatus
from tools.windows.audio_tools import (
    AudioMuteInput,
    AudioVolumeInput,
    WindowsAudioSetMuteTool,
)
from tools.windows.exceptions import AudioEndpointError, TargetValidationError
from tools.windows.models import AudioOperationResult, AudioState
from tools.windows.windows_service import WindowsControlService


def test_audio_mute_and_unmute_argument_handling() -> None:
    """Verify AudioMuteInput validates boolean values and tool calls service correctly."""
    mock_svc = MagicMock()
    mock_svc.set_mute.return_value = AudioOperationResult(
        volume_percent=80.0,
        is_muted=True,
        operation="mute",
        requested_value=True,
        actual_value=True,
        verified=True,
        success=True,
    )

    ctx = ExecutionContext()
    tool = WindowsAudioSetMuteTool(service=mock_svc)

    # Test Mute = True
    input_mute = AudioMuteInput(mute=True)
    res_mute = tool.execute(input_mute, ctx)
    assert res_mute.status == ToolExecutionStatus.SUCCESS
    assert res_mute.data["is_muted"] is True
    assert res_mute.data["verified"] is True
    assert res_mute.data["operation"] == "mute"
    mock_svc.set_mute.assert_called_with(True)

    # Test Mute = False (Unmute)
    mock_svc.set_mute.return_value = AudioOperationResult(
        volume_percent=80.0,
        is_muted=False,
        operation="unmute",
        requested_value=False,
        actual_value=False,
        verified=True,
        success=True,
    )
    input_unmute = AudioMuteInput(mute=False)
    res_unmute = tool.execute(input_unmute, ctx)
    assert res_unmute.status == ToolExecutionStatus.SUCCESS
    assert res_unmute.data["is_muted"] is False
    assert res_unmute.data["verified"] is True
    mock_svc.set_mute.assert_called_with(False)


def test_audio_volume_boundary_validation() -> None:
    """Verify volume percentage rejects negative values and values exceeding 100."""
    # Valid boundaries
    v0 = AudioVolumeInput(percent=0.0)
    assert v0.percent == 0.0
    v100 = AudioVolumeInput(percent=100.0)
    assert v100.percent == 100.0

    # Invalid boundaries rejected by schema
    with pytest.raises(ValidationError):
        AudioVolumeInput(percent=-0.1)

    with pytest.raises(ValidationError):
        AudioVolumeInput(percent=100.1)

    # Service-level validation
    svc = WindowsControlService()
    with pytest.raises(TargetValidationError):
        svc.set_volume(-10.0)

    with pytest.raises(TargetValidationError):
        svc.set_volume(150.0)


def test_audio_windows_api_exceptions_propagated_without_false_success() -> None:
    """When the underlying audio API fails, the tool must fail and never report success."""
    mock_svc = MagicMock()
    mock_svc.set_mute.side_effect = AudioEndpointError(
        "Windows Core Audio HRESULT failure: 0x80004005"
    )

    ctx = ExecutionContext()
    tool = WindowsAudioSetMuteTool(service=mock_svc)
    result = tool.execute(AudioMuteInput(mute=True), ctx)

    assert result.status == ToolExecutionStatus.FAILED
    assert "0x80004005" in str(result.error)
    assert result.data is None


def test_audio_com_per_thread_initialization() -> None:
    """Invoking audio service from a new worker thread must ensure COM is initialized."""
    svc = WindowsControlService()
    result_container: list[Any] = []

    def worker_target() -> None:
        try:
            status = svc.get_audio_status()
            result_container.append(status)
        except Exception as exc:
            result_container.append(exc)

    t = threading.Thread(target=worker_target)
    t.start()
    t.join()

    assert len(result_container) == 1
    res = result_container[0]
    # On Windows with an audio endpoint, must return AudioOperationResult or AudioState.
    # On headless CI runners without audio devices, GetDefaultAudioEndpoint raises AudioEndpointError,
    # which confirms COM was successfully initialized and CoCreateInstance succeeded without CO_E_NOTINITIALIZED.
    if isinstance(res, Exception):
        assert isinstance(res, AudioEndpointError)
        assert "CO_E_NOTINITIALIZED" not in str(res)
    else:
        assert isinstance(res, (AudioOperationResult, AudioState)), (
            f"Expected AudioState but got: {res}"
        )


def test_audio_state_verification_failure_detection() -> None:
    """If API call succeeds but read-back state does not match requested state, return failure."""
    mock_svc = MagicMock()
    # Simulated broken hardware: requested mute=True, but read-back is_muted=False
    mock_svc.set_mute.return_value = AudioOperationResult(
        volume_percent=70.0,
        is_muted=False,
        success=False,
        operation="mute",
        requested_value=True,
        actual_value=False,
        verified=False,
        error_code="VERIFICATION_FAILED",
        error_message="Read-back state is_muted=False does not match requested mute=True",
    )

    ctx = ExecutionContext()
    tool = WindowsAudioSetMuteTool(service=mock_svc)
    res = tool.execute(AudioMuteInput(mute=True), ctx)

    assert res.status == ToolExecutionStatus.FAILED
    assert res.metadata["data"]["error_code"] == "VERIFICATION_FAILED"
    assert res.metadata["data"]["verified"] is False


def test_audio_structured_results_schema() -> None:
    """Verify AudioOperationResult contains all required structured verification fields."""
    result = AudioOperationResult(
        volume_percent=42.0,
        is_muted=True,
        device_name="Headphones",
        supported=True,
        success=True,
        operation="mute",
        requested_value=True,
        actual_value=True,
        verified=True,
        error_code=None,
        error_message=None,
    )
    dump = result.model_dump()
    assert dump["volume_percent"] == 42.0
    assert dump["is_muted"] is True
    assert dump["success"] is True
    assert dump["operation"] == "mute"
    assert dump["requested_value"] is True
    assert dump["actual_value"] is True
    assert dump["verified"] is True
    assert dump["error_code"] is None


def test_audio_persian_and_english_intent_mapping() -> None:
    """Verify all 17 natural Persian and English command variations trigger planning and intent mapping."""
    planner = AgentPlanner(provider_manager=MagicMock())

    audio_test_prompts = [
        # Mute variations
        ("Mute the laptop.", "windows_audio_set_mute", {"mute": True}),
        ("Mute system audio.", "windows_audio_set_mute", {"mute": True}),
        ("Turn off the sound.", "windows_audio_set_mute", {"mute": True}),
        ("صدای لپتاپ رو قطع کن.", "windows_audio_set_mute", {"mute": True}),
        ("صدا رو بیصدا کن.", "windows_audio_set_mute", {"mute": True}),
        ("سیستم رو Mute کن.", "windows_audio_set_mute", {"mute": True}),
        ("صدای دستگاه رو قطع کن", "windows_audio_set_mute", {"mute": True}),
        # Unmute variations
        ("Unmute the laptop.", "windows_audio_set_mute", {"mute": False}),
        ("Restore system audio.", "windows_audio_set_mute", {"mute": False}),
        ("صدای سیستم رو وصل کن.", "windows_audio_set_mute", {"mute": False}),
        ("صدا رو از حالت بیصدا خارج کن.", "windows_audio_set_mute", {"mute": False}),
        # Volume variations
        ("Set volume to 50%.", "windows_audio_set_volume", {"percent": 50.0}),
        ("میزان صدا رو روی ۵۰ درصد بذار.", "windows_audio_set_volume", {"percent": 50.0}),
        ("Set system volume to 30 percent.", "windows_audio_set_volume", {"percent": 30.0}),
        ("صدای سیستم رو روی ۳۰ درصد بذار.", "windows_audio_set_volume", {"percent": 30.0}),
        ("Increase system volume.", "windows_audio_set_volume", {}),
        ("Decrease system volume.", "windows_audio_set_volume", {}),
        ("صدای لپتاپ رو زیاد کن.", "windows_audio_set_volume", {}),
        ("صدای سیستم رو کم کن.", "windows_audio_set_volume", {}),
    ]

    tool_names = {"windows_audio_set_mute", "windows_audio_set_volume", "windows_audio_get_status"}

    for prompt, expected_tool, expected_params in audio_test_prompts:
        # 1. should_plan MUST return True
        assert planner.should_plan(prompt) is True, f"Failed should_plan for: {prompt}"

        # 2. _detect_audio_intent MUST map to the expected tool and parameters
        intent = planner._detect_audio_intent(prompt, tool_names)
        assert intent is not None, f"Failed _detect_audio_intent for: {prompt}"
        assert intent["tool_name"] == expected_tool, (
            f"Expected {expected_tool} for '{prompt}', got {intent['tool_name']}"
        )
        for param_key, param_val in expected_params.items():
            assert intent["parameters"].get(param_key) == param_val, (
                f"Param mismatch for '{prompt}': {intent['parameters']} vs {expected_params}"
            )


def test_audio_tools_registration_and_discovery() -> None:
    """Agent tool registry registers all audio tools and permission manager grants them."""
    agent = JARVISAgent()

    # Discoverability
    assert agent.tool_registry.get("windows_audio_set_mute") is not None
    assert agent.tool_registry.get("windows_audio_set_volume") is not None
    assert agent.tool_registry.get("windows_audio_get_status") is not None

    # Permission evaluation
    req = PermissionRequest(
        tool_name="windows_audio_set_mute",
        category=PermissionCategory.WINDOWS_AUDIO_CONTROL,
        action_summary="Mute master audio",
        parameters={"mute": True},
    )
    perm = agent.permission_manager.evaluate(req)
    assert perm.decision.value == "granted"


def test_agent_false_success_prevention_on_tool_failure() -> None:
    """If the audio tool fails, agent execution must report failure and NEVER claim success."""
    agent = JARVISAgent()
    mute_tool = agent.tool_registry.get("windows_audio_set_mute")

    # Mock service to simulate endpoint failure
    mock_svc = MagicMock()
    mock_svc.set_mute.return_value = AudioOperationResult(
        volume_percent=60.0,
        is_muted=False,
        success=False,
        operation="mute",
        requested_value=True,
        actual_value=False,
        verified=False,
        error_code="ENDPOINT_UNAVAILABLE",
        error_message="Audio output endpoint was disconnected",
    )
    mute_tool.service = mock_svc

    outcome = agent.process_agent_task("صدای لپتاپ رو قطع کن")
    reply = outcome.final_response

    # Must NOT claim audio was muted
    assert "قطع شد" not in reply, f"False success claim detected: {reply}"
    assert "با موفقیت" not in reply, f"False success claim detected: {reply}"
    # Must truthfully state inability to complete
    assert any(
        err_indicator in reply
        for err_indicator in ("نتوانستم", "انجام نشد", "خطا", "Unable", "Failed")
    ), f"Expected truthful failure report but got: {reply}"


def test_com_lifecycle_s_ok_and_s_false_cleanup() -> None:
    """Verify S_OK (0) and S_FALSE (1) invoke CoUninitialize on exit."""
    svc = WindowsControlService()
    mock_ole = MagicMock()
    svc._ole32 = mock_ole

    # S_OK = 0
    mock_ole.CoInitialize.return_value = 0
    with svc._com_session():
        pass
    mock_ole.CoUninitialize.assert_called_once()

    # S_FALSE = 1
    mock_ole.reset_mock()
    mock_ole.CoInitialize.return_value = 1
    with svc._com_session():
        pass
    mock_ole.CoUninitialize.assert_called_once()


def test_com_lifecycle_rpc_e_changed_mode_no_uninit_and_clean_thread_recovery() -> None:
    """RPC_E_CHANGED_MODE must NOT call CoUninitialize on current thread and recovers via clean worker thread."""
    svc = WindowsControlService()
    mock_ole = MagicMock()
    svc._ole32 = mock_ole

    # First call on caller thread returns RPC_E_CHANGED_MODE (-2147417850)
    # Subsequent call on worker thread returns S_OK (0)
    mock_ole.CoInitialize.side_effect = [-2147417850, 0]

    executed = []

    def mock_audio_action():
        executed.append("done")
        return "success_val"

    result = svc._run_with_com(mock_audio_action)

    assert result == "success_val"
    assert executed == ["done"]
    # Verify CoUninitialize was called exactly once (from the successful worker thread, NOT the failed caller thread)
    assert mock_ole.CoUninitialize.call_count == 1
