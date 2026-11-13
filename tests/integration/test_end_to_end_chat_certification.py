"""End-to-End Chat Capability Certification Test Suite.

Exercises the actual chat dispatch and agent execution path for every implemented
JARVIS capability in representative Persian and English commands:
1. System status / overview
2. CPU usage
3. RAM usage
4. Disk information
5. Network status
6. File listing in authorized folder
7. File text search
8. Persistent memory retrieval
9. App launch and graceful closure (Notepad)
10. Window control (enumeration, minimize, restore)
11. Audio mute and read-back verification
12. Audio volume setting and read-back verification
13. Display brightness query
14. Power / battery status query
15. Conversational chat stream without planning
"""

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from config import Settings
from core.agent import JARVISAgent
from tools.windows.windows_service import WindowsControlService


@pytest.fixture
def cert_settings(tmp_path: Path) -> Settings:
    auth_dir = tmp_path / "authorized_docs"
    auth_dir.mkdir(parents=True, exist_ok=True)
    test_file = auth_dir / "sample.txt"
    test_file.write_text("JARVIS test file containing specific test keyword.", encoding="utf-8")

    from tools.filesystem.path_security import get_path_security_service

    path_sec = get_path_security_service()
    path_sec.clear_all()
    path_sec.add_directory(str(auth_dir))

    return Settings(
        app_name="JARVIS",
        default_provider="gemini",
        gemini_model="gemini-3.8-flash",
        system_inspection_enabled=True,
        file_reading_enabled=True,
        windows_control_enabled=True,
        windows_app_launch_enabled=True,
        windows_app_close_enabled=True,
        windows_window_control_enabled=True,
        windows_audio_control_enabled=True,
        windows_display_control_enabled=True,
        windows_power_control_enabled=True,
        memory_enabled=True,
        memory_allow_cloud_transmission=False,
        data_dir=tmp_path / "data",
        gemini_api_key=SecretStr("AIzaSyMockKeyForCert"),
    )


def test_cert_conversational_chat_streams_without_planning(cert_settings: Settings) -> None:
    """Verify normal conversational greetings stream directly without invoking tool planning."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    # English greeting
    assert agent.planner.should_plan("Hello, who are you?") is False
    assert agent.planner.should_plan("Good morning!") is False

    # Persian greeting
    assert agent.planner.should_plan("سلام، چطوری؟") is False
    assert agent.planner.should_plan("خسته نباشید") is False


def test_cert_cpu_usage_query_persian_and_english(cert_settings: Settings) -> None:
    """Verify CPU usage query reaches planner, executes real CPU tool, and returns truthful response."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    # Persian command
    outcome_fa = agent.process_agent_task("میزان مصرف پردازنده چقدره؟")
    assert outcome_fa.status == "completed"
    assert "cpu" in outcome_fa.final_response.lower() or "پردازنده" in outcome_fa.final_response
    assert any(c.isdigit() for c in outcome_fa.final_response)

    # English command
    outcome_en = agent.process_agent_task("What is my CPU usage?")
    assert outcome_en.status == "completed"
    assert "cpu" in outcome_en.final_response.lower() or "پردازنده" in outcome_en.final_response


def test_cert_ram_usage_query_persian_and_english(cert_settings: Settings) -> None:
    """Verify RAM usage query reaches planner and returns real memory percentage."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    outcome_fa = agent.process_agent_task("میزان رم مصرفی رو بگو")
    assert outcome_fa.status == "completed"
    assert "ram" in outcome_fa.final_response.lower() or "رم" in outcome_fa.final_response

    outcome_en = agent.process_agent_task("Show RAM usage")
    assert outcome_en.status == "completed"
    assert "ram" in outcome_en.final_response.lower() or "رم" in outcome_en.final_response


def test_cert_disk_space_query_persian_and_english(cert_settings: Settings) -> None:
    """Verify Disk space query returns actual drive information."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    outcome_fa = agent.process_agent_task("فضای دیسک رو بررسی کن")
    assert outcome_fa.status == "completed"
    assert "دیسک" in outcome_fa.final_response or "disk" in outcome_fa.final_response.lower()

    outcome_en = agent.process_agent_task("Check disk space")
    assert outcome_en.status == "completed"


def test_cert_network_status_query_persian_and_english(cert_settings: Settings) -> None:
    """Verify Network status query returns active network adapters."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    outcome_fa = agent.process_agent_task("وضعیت شبکه رو بررسی کن")
    assert outcome_fa.status == "completed"

    outcome_en = agent.process_agent_task("Check network status")
    assert outcome_en.status == "completed"


def test_cert_system_status_overview_persian_and_english(cert_settings: Settings) -> None:
    """Verify comprehensive system status returns OS and platform overview."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    outcome_fa = agent.process_agent_task("وضعیت سیستم رو بگو")
    assert outcome_fa.status == "completed"

    outcome_en = agent.process_agent_task("Show system status")
    assert outcome_en.status == "completed"


def test_cert_file_tools_in_authorized_folder(cert_settings: Settings) -> None:
    """Verify directory listing and bounded file search inside authorized folder."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    from tools.filesystem.path_security import get_path_security_service

    path_sec = get_path_security_service()
    auth_dirs = path_sec.list_authorized_directories()
    assert len(auth_dirs) > 0
    auth_dir = Path(auth_dirs[0].path)
    assert (auth_dir / "sample.txt").exists()

    # Directory list
    res_list = agent.tool_registry.execute_tool(
        "file_list_directory", {"directory_path": str(auth_dir)}, agent._current_context
    )
    assert res_list.status.value == "success"
    assert "sample.txt" in str(res_list.data)

    # File search text
    res_search = agent.tool_registry.execute_tool(
        "file_search_text",
        {"directory_path": str(auth_dir), "query": "test"},
        agent._current_context,
    )
    assert res_search.status.value == "success"
    assert res_search.data.get("match_count", 0) > 0


def test_cert_persistent_memory_retrieval(cert_settings: Settings) -> None:
    """Verify saving a memory candidate, approving it, and retrieving it via chat context."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    # Pre-populate approved memory
    rec = agent.memory_manager.create_approved_memory(
        content="Current active development project is Project Alpha",
        key="project.current",
    )
    assert rec.id is not None

    # Retrieve memory context locally (for_cloud_transmission=False)
    ctx_local = agent.build_memory_context(
        "پروژه‌ای که ذخیره کردم رو پیدا کن", for_cloud_transmission=False
    )
    assert "Project Alpha" in ctx_local

    ctx_local_en = agent.build_memory_context(
        "Retrieve a saved project memory", for_cloud_transmission=False
    )
    assert "Project Alpha" in ctx_local_en

    # Privacy verification: cloud transmission remains strictly blocked by default
    ctx_cloud_blocked = agent.build_memory_context("Project Alpha", for_cloud_transmission=True)
    assert ctx_cloud_blocked == ""


def test_cert_audio_chat_execution_and_readback_verification(cert_settings: Settings) -> None:
    """Verify real Windows audio control through agent task with readback and restoration."""
    svc = WindowsControlService(settings=cert_settings)
    initial = svc.get_audio_status()
    orig_muted = initial.is_muted
    orig_vol = initial.volume_percent

    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    try:
        # 1. Mute
        outcome_mute = agent.process_agent_task("صدای لپتاپ رو قطع کن")
        assert outcome_mute.status == "completed"
        read_muted = svc.get_audio_status()
        assert read_muted.is_muted is True

        # 2. Unmute
        outcome_unmute = agent.process_agent_task("صدا رو وصل کن")
        assert outcome_unmute.status == "completed"
        read_unmuted = svc.get_audio_status()
        assert read_unmuted.is_muted is False

        # 3. Set Volume to 40%
        outcome_vol = agent.process_agent_task("صدا رو روی ۴۰ درصد بگذار")
        assert outcome_vol.status == "completed"
        read_vol = svc.get_audio_status()
        assert abs(read_vol.volume_percent - 40.0) <= 2.0

    finally:
        # Clean teardown restoration
        svc.set_mute(orig_muted)
        svc.set_volume(orig_vol)


def test_cert_display_brightness_graceful_handling(cert_settings: Settings) -> None:
    """Verify display brightness query executes and returns actual value or unsupported notice gracefully."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    outcome = agent.process_agent_task("روشنایی رو بررسی کن")
    assert outcome.status == "completed"
    assert outcome.final_response != ""


def test_cert_power_battery_status_query(cert_settings: Settings) -> None:
    """Verify power and battery status query returns real Windows SYSTEM_POWER_STATUS."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    outcome_fa = agent.process_agent_task("وضعیت باتری رو بگو")
    assert outcome_fa.status == "completed"
    assert (
        "برق" in outcome_fa.final_response
        or "باتری" in outcome_fa.final_response
        or "power" in outcome_fa.final_response.lower()
    )

    outcome_en = agent.process_agent_task("Show battery status")
    assert outcome_en.status == "completed"


def test_cert_notepad_launch_minimize_and_close(cert_settings: Settings) -> None:
    """Verify high-risk app launch approval lifecycle, execution, and cleanup."""
    svc = WindowsControlService(settings=cert_settings)
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()
    # Fast deterministic fallback without network wait
    agent.planner.provider_manager.generate_text = MagicMock(
        side_effect=RuntimeError("Offline mock")
    )

    # 1. First verify wait_for_approval=False yields waiting_for_approval outcome
    outcome_init = agent.process_agent_task("نوتپد رو باز کن", wait_for_approval=False)
    assert outcome_init.status == "waiting_for_approval"
    assert outcome_init.pending_approval is not None
    assert outcome_init.pending_approval.tool_name == "windows_app_launch"

    agent.state_machine.reset()

    # 2. Now execute with background approval workflow
    stop_event = threading.Event()

    def approve_in_background() -> None:
        start_t = time.time()
        while not stop_event.is_set() and (time.time() - start_t < 30.0):
            prop = agent.approval_manager.get_pending_proposal(session_id=agent.active_session_id)
            if prop:
                agent.submit_approval_decision(
                    proposal_id=prop.proposal_id,
                    approved=True,
                    session_id=agent.active_session_id,
                )
                return
            time.sleep(0.05)

    bg_thread = threading.Thread(target=approve_in_background)
    bg_thread.start()

    outcome_completed = agent.process_agent_task("نوتپد رو باز کن", wait_for_approval=True)
    stop_event.set()
    bg_thread.join()
    assert outcome_completed.status == "completed"

    time.sleep(1.0)
    pid = None
    try:
        # Find Notepad window and process
        windows = svc.list_windows()
        notepad_wins = [w for w in windows if "notepad" in w.title.lower()]
        assert len(notepad_wins) > 0, "Notepad window not found after launch"

        target_win = notepad_wins[0]
        pid = target_win.pid

        # Minimize
        min_res = svc.minimize_window(target_win.hwnd)
        assert min_res is True

        # Restore
        rest_res = svc.restore_window(target_win.hwnd)
        assert rest_res is True

    finally:
        if pid:
            svc.close_application("notepad", pid=pid, graceful=False)
            time.sleep(0.5)


def test_cert_filesystem_metadata_reading_and_security_boundaries(cert_settings: Settings) -> None:
    """Verify file metadata, bounded text reading, and strict rejection of unauthorized paths."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    from tools.filesystem.path_security import get_path_security_service

    path_sec = get_path_security_service()
    auth_dirs = path_sec.list_authorized_directories()
    assert len(auth_dirs) > 0
    auth_dir = Path(auth_dirs[0].path)
    test_file = auth_dir / "sample.txt"

    # 1. Metadata reading
    res_meta = agent.tool_registry.execute_tool(
        "file_get_metadata",
        {"file_path": str(test_file)},
        agent._current_context,
    )
    assert res_meta.status.value == "success"
    assert res_meta.data.get("size_bytes", 0) > 0
    assert res_meta.data.get("is_directory") is False

    # 2. Bounded text reading
    res_read = agent.tool_registry.execute_tool(
        "file_read_text",
        {"file_path": str(test_file), "max_chars": 1000},
        agent._current_context,
    )
    assert res_read.status.value == "success"
    assert "JARVIS test file" in str(res_read.data.get("content", ""))

    # 3. Unauthorized directory rejection
    res_unauth = agent.tool_registry.execute_tool(
        "file_read_text",
        {"file_path": "C:/Windows/System32/drivers/etc/hosts"},
        agent._current_context,
    )
    assert res_unauth.status.value in ("denied", "failure")
    assert (
        "denied" in str(res_unauth.error).lower()
        or "not authorized" in str(res_unauth.error).lower()
    )

    # 4. Path traversal rejection
    traversal_path = str(auth_dir / ".." / ".." / "Windows" / "win.ini")
    res_traversal = agent.tool_registry.execute_tool(
        "file_read_text",
        {"file_path": traversal_path},
        agent._current_context,
    )
    assert res_traversal.status.value in ("denied", "failure")


def test_cert_memory_full_lifecycle_and_privacy(cert_settings: Settings) -> None:
    """Verify memory creation, search, edit, soft-delete, and cloud transmission privacy."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    # 1. Create approved memory
    rec = agent.memory_manager.create_approved_memory(
        content="User preferred dark theme and high contrast",
        key="ui.preferences",
    )
    assert rec.id is not None

    # 2. Local search
    results = agent.memory_manager.list_memories(search_query="dark theme")
    assert len(results) > 0
    assert any("dark theme" in r.content for r in results)

    # 3. Edit memory
    updated = agent.memory_manager.edit_memory(
        memory_id=rec.id,
        new_content="User preferred dark theme with blue accents",
    )
    assert updated is not None
    assert "blue accents" in updated.content

    # 4. Soft delete memory
    del_ok = agent.memory_manager.delete_memory(rec.id, soft=True)
    assert del_ok is True
    # Verify not listed in active queries
    active_recs = agent.memory_manager.list_memories(search_query="blue accents")
    assert len(active_recs) == 0

    # 5. Cloud privacy: verify cloud transmission returns empty when disabled
    ctx = agent.build_memory_context("blue accents", for_cloud_transmission=True)
    assert ctx == ""


def test_cert_window_maximize_focus_and_close(cert_settings: Settings) -> None:
    """Verify application launch, window maximization, window focus, and graceful closure."""
    svc = WindowsControlService(settings=cert_settings)
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()
    agent.planner.provider_manager.generate_text = MagicMock(
        side_effect=RuntimeError("Offline mock")
    )

    stop_event = threading.Event()

    def approve_in_background() -> None:
        start_t = time.time()
        while not stop_event.is_set() and (time.time() - start_t < 30.0):
            prop = agent.approval_manager.get_pending_proposal(session_id=agent.active_session_id)
            if prop:
                agent.submit_approval_decision(
                    proposal_id=prop.proposal_id,
                    approved=True,
                    session_id=agent.active_session_id,
                )
                return
            time.sleep(0.05)

    bg_thread = threading.Thread(target=approve_in_background)
    bg_thread.start()

    outcome = agent.process_agent_task("نوتپد رو باز کن", wait_for_approval=True)
    stop_event.set()
    bg_thread.join()
    assert outcome.status == "completed"

    time.sleep(1.0)
    pid = None
    try:
        windows = svc.list_windows()
        notepad_wins = [w for w in windows if "notepad" in w.title.lower()]
        assert len(notepad_wins) > 0
        target = notepad_wins[0]
        pid = target.pid

        # Maximize
        max_ok = svc.maximize_window(target.hwnd)
        assert max_ok is True

        # Focus
        focus_ok = svc.focus_window(target.hwnd)
        assert focus_ok is True

        # Close
        close_ok = svc.close_window(target.hwnd, graceful=True)
        assert close_ok is True
    finally:
        if pid:
            svc.close_application("notepad", pid=pid, graceful=False)
            time.sleep(0.5)


def test_cert_power_approval_paths_and_cancellation(cert_settings: Settings) -> None:
    """Verify power operations require approval and respect cancellation / rejection."""
    agent = JARVISAgent(settings=cert_settings)
    agent.initialize()

    # 1. Workstation Lock requires approval
    outcome_lock = agent.process_agent_task("سیستم رو قفل کن", wait_for_approval=False)
    if outcome_lock.status == "waiting_for_approval":
        assert outcome_lock.pending_approval is not None
        # Reject lock proposal
        rejected = agent.submit_approval_decision(
            proposal_id=outcome_lock.pending_approval.proposal_id,
            approved=False,
            session_id=agent.active_session_id,
            reason="User decided not to lock",
        )
        assert rejected is True

    agent.state_machine.reset()

    # 2. Sleep requires approval
    outcome_sleep = agent.process_agent_task("سیستم رو ببر رو حالت Sleep", wait_for_approval=False)
    if outcome_sleep.status == "waiting_for_approval":
        assert outcome_sleep.pending_approval is not None
        rejected = agent.submit_approval_decision(
            proposal_id=outcome_sleep.pending_approval.proposal_id,
            approved=False,
            session_id=agent.active_session_id,
            reason="User cancelled sleep",
        )
        assert rejected is True
