"""Unit tests for Adaptive Multi-Step Execution, Capability Registry, and Anaphora in JARVIS.

Tests:
1. Multi-turn project, nested directory, and correction flow:
   - Turn 1: "Find my PC Shop project"
   - Turn 2: "Open it in VS Code"
   - Turn 3: "Create a folder called Python inside it"
   - Turn 4: "Actually, call it Backend instead"
2. Universal State Machine Lifecycle:
   - Transitions across UNDERSTANDING, CONTEXT_RETRIEVAL, ENVIRONMENT_DISCOVERY,
     PLANNING, EXECUTING, VERIFYING, RECOVERING, WAITING_FOR_USER, COMPLETED.
3. Capability Registry & Structured Operations.
"""

from __future__ import annotations

from pathlib import Path

from core.conversation_session import ConversationSessionManager
from core.events import EventBus
from core.permissions import PermissionCategory, StrictDefaultDenyPermissionManager
from core.state_machine import AgentState, AgentStateMachine
from core.tool_registry import ToolRegistry
from tools.filesystem.file_tools import FileCreateDirectoryTool
from tools.windows.application_tools import WindowsAppLaunchTool


def test_multi_turn_project_and_nested_folder_flow(tmp_path: Path) -> None:
    """End-to-end multi-turn conversation test for project discovery, app launch, nested folder, and rename."""
    sess_mgr = ConversationSessionManager.get_instance()
    sess_id = "test_multi_turn_pc_shop_session"
    sess_mgr.reset_session(sess_id)
    session = sess_mgr.get_or_create_session(sess_id)

    # In CI environments where C:\docker\pc-shop is absent, register a simulated workspace
    if not Path("C:/docker/pc-shop").is_dir():
        fake_shop = tmp_path / "pc-shop"
        fake_shop.mkdir(parents=True, exist_ok=True)
        (fake_shop / ".git").mkdir(exist_ok=True)
        sess_mgr.register_project("pc shop", fake_shop)
        sess_mgr.register_project("pc-shop", fake_shop)

    # --- Turn 1: Find my PC Shop project ---
    t1_text, t1_inf = sess_mgr.resolve_contextual_references("Find my PC Shop project", [], sess_id)
    assert session.active_project_path is not None
    assert "pc-shop" in str(session.active_project_path).lower()
    assert session.active_project_name is not None
    assert t1_inf.get("resolved_project") is not None

    # --- Turn 2: Open it in VS Code ---
    t2_text, t2_inf = sess_mgr.resolve_contextual_references("Open it in VS Code", [], sess_id)
    assert t2_inf.get("resolved_project") == session.active_project_name
    assert t2_inf.get("project_path") == str(session.active_project_path)
    assert t2_inf.get("anaphoric_reference_resolved") is True

    # --- Turn 3: Create a folder called Python inside it ---
    t3_text, t3_inf = sess_mgr.resolve_contextual_references(
        "Create a folder called Python inside it", [], sess_id
    )
    assert t3_inf.get("resolved_child_folder") == "Python"
    assert t3_inf.get("parent_directory_path") == str(session.active_project_path)

    # Simulate executor setting last created directory
    expected_child = session.active_project_path / "Python"
    session.last_created_directory_path = expected_child
    session.last_created_directory_name = "Python"

    # --- Turn 4: Actually, call it Backend instead ---
    t4_text, t4_inf = sess_mgr.resolve_contextual_references(
        "Actually, call it Backend instead", [], sess_id
    )
    assert t4_inf.get("resolved_folder_name") == "Backend"
    assert t4_inf.get("rename_target") == str(session.active_project_path / "Backend")


def test_state_machine_extended_lifecycle() -> None:
    """Test transitions through the extended universal state machine lifecycle."""
    sm = AgentStateMachine()
    assert sm.current_state == AgentState.IDLE

    # IDLE -> UNDERSTANDING
    sm.transition_to(AgentState.UNDERSTANDING, reason="Analyzing request")
    assert sm.current_state == AgentState.UNDERSTANDING

    # UNDERSTANDING -> CONTEXT_RETRIEVAL
    sm.transition_to(AgentState.CONTEXT_RETRIEVAL, reason="Retrieving project context")
    assert sm.current_state == AgentState.CONTEXT_RETRIEVAL

    # CONTEXT_RETRIEVAL -> ENVIRONMENT_DISCOVERY
    sm.transition_to(AgentState.ENVIRONMENT_DISCOVERY, reason="Scanning drives for project")
    assert sm.current_state == AgentState.ENVIRONMENT_DISCOVERY

    # ENVIRONMENT_DISCOVERY -> PLANNING
    sm.transition_to(AgentState.PLANNING, reason="Creating execution plan")
    assert sm.current_state == AgentState.PLANNING

    # PLANNING -> PLAN_READY -> EXECUTING
    sm.transition_to(AgentState.PLAN_READY, reason="Plan constructed")
    sm.transition_to(AgentState.EXECUTING, reason="Executing steps")
    assert sm.current_state == AgentState.EXECUTING

    # EXECUTING -> VERIFYING
    sm.transition_to(AgentState.VERIFYING, reason="Verifying filesystem results")
    assert sm.current_state == AgentState.VERIFYING

    # VERIFYING -> COMPLETED
    sm.transition_to(AgentState.COMPLETED, reason="Execution verified on disk")
    assert sm.current_state == AgentState.COMPLETED

    # COMPLETED -> IDLE
    sm.transition_to(AgentState.IDLE, reason="Reset for next user turn")
    assert sm.current_state == AgentState.IDLE


def test_capability_registry_operations() -> None:
    """Test ToolRegistry structured capability lookup and operation mapping."""
    perm_mgr = StrictDefaultDenyPermissionManager()
    bus = EventBus()
    registry = ToolRegistry(permission_manager=perm_mgr, event_bus=bus)

    # Register filesystem and application tools
    fs_tool = FileCreateDirectoryTool()
    app_tool = WindowsAppLaunchTool()
    registry.register(fs_tool)
    registry.register(app_tool)

    # Query capabilities dictionary
    capabilities = registry.get_capabilities()
    assert "file_create_directory" in capabilities
    assert "windows_app_launch" in capabilities
    assert "operations" in capabilities["file_create_directory"]
    assert "verification_strategy" in capabilities["file_create_directory"]

    # Query tools for operation
    matched = registry.find_tools_for_operation("file_create_directory")
    assert len(matched) == 1
    assert matched[0].name == "file_create_directory"

    # Query tools by permission category
    cat_matched = registry.find_tools_by_category(PermissionCategory.WINDOWS_APP_LAUNCH)
    assert len(cat_matched) == 1
    assert cat_matched[0].name == "windows_app_launch"
