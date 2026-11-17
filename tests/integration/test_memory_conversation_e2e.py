"""Integration tests for Human-Level Conversational Intelligence & Memory in JARVIS."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.conversation_session import get_conversation_session_manager
from core.execution_context import ExecutionContext
from core.memory import PersonalStore
from core.planner import AgentPlanner, ToolDefinition


@pytest.fixture
def clean_env(tmp_path: Path):
    db_file = tmp_path / "e2e_personal_memory.db"
    store = PersonalStore(db_path=db_file)
    old_instance = PersonalStore._instance
    PersonalStore._instance = store
    session_mgr = get_conversation_session_manager()
    yield store, session_mgr
    PersonalStore._instance = old_instance


class TestProjectResolutionAndAnaphoraE2E:
    def test_open_jarvis_project_resolves_accurately(self, clean_env):
        store, session_mgr = clean_env
        planner = AgentPlanner(provider_manager=MagicMock())
        context = ExecutionContext(session_id="test_proj_session")

        tools = [
            ToolDefinition(
                name="file_open",
                description="Open file or project directory",
                parameters_schema={"file_path": "str", "application": "str"},
            ),
            ToolDefinition(
                name="windows_app_launch",
                description="Launch desktop app",
                parameters_schema={"app_id": "str"},
            ),
        ]

        plan = planner.create_plan(
            goal="Open the JARVIS project",
            context=context,
            available_tools=tools,
        )

        assert len(plan.steps) >= 2
        file_step = next((s for s in plan.steps if s.tool_name == "file_open"), None)
        assert file_step is not None
        assert "jarvis" in str(file_step.parameters.get("file_path", "")).lower()

        # Verify active project session context was populated
        sess = session_mgr.get_session("test_proj_session")
        assert sess is not None
        assert sess.active_project_path is not None
        assert "jarvis" in sess.active_project_name.lower()

    def test_anaphoric_followup_open_it_in_vscode(self, clean_env):
        store, session_mgr = clean_env
        sess = session_mgr.get_or_create_session("test_anaphora_sess")
        sess.active_project_name = "jarvis"
        sess.active_project_path = Path(r"C:\AI\jarvis")

        resolved_text, inferred = session_mgr.resolve_contextual_references(
            current_prompt="Open it in VS Code",
            history=[],
            session_id="test_anaphora_sess",
        )

        assert "jarvis" in resolved_text.lower()
        assert inferred.get("anaphoric_reference_resolved") is True
        assert inferred.get("resolved_project") == "jarvis"

    def test_anaphoric_followup_antigravity_coding_agent(self, clean_env):
        store, session_mgr = clean_env
        sess = session_mgr.get_or_create_session("test_coding_sess")
        sess.active_project_name = "jarvis"
        sess.active_project_path = Path(r"C:\AI\jarvis")

        planner = AgentPlanner(provider_manager=MagicMock())
        context = ExecutionContext(session_id="test_coding_sess")

        tools = [
            ToolDefinition(
                name="coding_agent_delegate_task",
                description="Delegate task to Antigravity",
                parameters_schema={"prompt": "str", "workspace_path": "str"},
            )
        ]

        plan = planner.create_plan(
            goal="Now ask Antigravity to fix failing tests",
            context=context,
            available_tools=tools,
        )

        agy_step = next(
            (s for s in plan.steps if s.tool_name == "coding_agent_delegate_task"), None
        )
        assert agy_step is not None
        assert "C:\\AI\\jarvis" in agy_step.parameters.get("workspace_path", "")

    def test_generic_coding_application_without_preference_asks_clarification(self, clean_env):
        store, session_mgr = clean_env
        store.delete_preference("coding", "preferred_editor")

        planner = AgentPlanner(provider_manager=MagicMock())
        context = ExecutionContext(session_id="test_generic_code_sess")

        tools = [
            ToolDefinition(
                name="windows_app_launch",
                description="Launch desktop app",
                parameters_schema={"app_id": "str"},
            )
        ]

        plan = planner.create_plan(
            goal="Open a coding application",
            context=context,
            available_tools=tools,
        )

        # Must NOT loop or launch Application Stack Builder
        app_step = next((s for s in plan.steps if s.tool_name == "windows_app_launch"), None)
        assert app_step is None or app_step.parameters.get("app_id") != "application stack builder"

        # Should include clarification step
        thought_step = next((s for s in plan.steps if s.step_type.value == "thought"), None)
        assert thought_step is not None
        params = thought_step.parameters
        assert "clarification_prompt" in params or "Analyze goal" in thought_step.description

    def test_generic_coding_application_with_stored_preference_launches_preferred(self, clean_env):
        store, session_mgr = clean_env
        store.set_preference("coding", "preferred_editor", "Cursor")

        planner = AgentPlanner(provider_manager=MagicMock())
        context = ExecutionContext(session_id="test_pref_code_sess")

        tools = [
            ToolDefinition(
                name="windows_app_launch",
                description="Launch desktop app",
                parameters_schema={"app_id": "str"},
            )
        ]

        plan = planner.create_plan(
            goal="Open a coding application",
            context=context,
            available_tools=tools,
        )

        app_step = next((s for s in plan.steps if s.tool_name == "windows_app_launch"), None)
        assert app_step is not None
        assert app_step.parameters.get("app_id") == "cursor"
