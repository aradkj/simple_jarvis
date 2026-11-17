"""Unit tests for deep conversational intelligence, intent reasoning, and multi-turn anaphora."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.conversation_session import ConversationSessionManager, get_conversation_session_manager
from core.execution_context import ExecutionContext
from core.executor import AgentExecutor
from core.planner import AgentPlanner, PlanStep, StepStatus, StepType
from tools.filesystem.file_tools import FileCreateDirectoryTool
from tools.windows import WindowsAppLaunchTool


class TestImpliedCodingIntentReasoning:
    """Test recognizing implied coding intentions and routing them to IDE launch."""

    @pytest.fixture
    def planner(self):
        mock_pm = MagicMock()
        return AgentPlanner(provider_manager=mock_pm)

    @pytest.fixture
    def tools_def(self):
        tool1 = WindowsAppLaunchTool()
        tool2 = FileCreateDirectoryTool()
        return [tool1.get_definition(), tool2.get_definition()]

    def test_should_plan_implied_coding(self, planner):
        assert planner.should_plan("I need to code now") is True
        assert planner.should_plan("Let's start programming") is True
        assert planner.should_plan("time to code") is True
        assert planner.should_plan("میخوام کدنویسی کنم") is True
        assert planner.should_plan("وقت کدزدنه") is True

    def test_create_plan_implied_coding_routes_to_editor(self, planner, tools_def):
        ctx = ExecutionContext(session_id="test_coding_sess")
        plan = planner.create_plan("I need to code now", context=ctx, available_tools=tools_def)

        # Plan should contain a tool_call step launching VS Code / IDE
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "windows_app_launch"
        assert tool_steps[0].parameters.get("app_id") in ("code", "vscode", "cursor")

    def test_persian_implied_coding_routes_to_editor(self, planner, tools_def):
        ctx = ExecutionContext(session_id="test_fa_coding_sess")
        plan = planner.create_plan("میخوام کدنویسی کنم", context=ctx, available_tools=tools_def)

        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "windows_app_launch"


class TestMissingInformationClarification:
    """Test single concise clarification when folder name is missing."""

    @pytest.fixture
    def planner(self):
        mock_pm = MagicMock()
        return AgentPlanner(provider_manager=mock_pm)

    @pytest.fixture
    def tools_def(self):
        tool = FileCreateDirectoryTool()
        return [tool.get_definition()]

    def test_english_missing_folder_name(self, planner, tools_def):
        ctx = ExecutionContext(session_id="test_clarif_en")
        plan = planner.create_plan(
            "Create a folder on my Desktop", context=ctx, available_tools=tools_def
        )

        # Should produce thought step with clarification prompt without re-asking destination
        thought_steps = [
            s
            for s in plan.steps
            if s.step_type == StepType.THOUGHT and s.parameters.get("clarification_prompt")
        ]
        assert len(thought_steps) == 1
        prompt = thought_steps[0].parameters["clarification_prompt"]
        assert "What would you like to name the folder on your Desktop?" in prompt

        # Check session recorded pending clarification
        mgr = get_conversation_session_manager()
        sess = mgr.get_session("test_clarif_en")
        assert sess is not None
        assert sess.pending_clarification is not None
        assert sess.pending_clarification.get("type") == "folder_name"
        assert sess.pending_clarification.get("destination") == "Desktop"

    def test_persian_missing_folder_name(self, planner, tools_def):
        ctx = ExecutionContext(session_id="test_clarif_fa")
        plan = planner.create_plan(
            "یه پوشه روی دسکتاپ بساز", context=ctx, available_tools=tools_def
        )

        thought_steps = [
            s
            for s in plan.steps
            if s.step_type == StepType.THOUGHT and s.parameters.get("clarification_prompt")
        ]
        assert len(thought_steps) == 1
        prompt = thought_steps[0].parameters["clarification_prompt"]
        assert "مایلید نام این پوشه روی دسکتاپ چه باشد" in prompt


class TestMultiTurnAnaphoraAndFolderNesting:
    """Test cross-turn entity resolution, nesting, and destination corrections."""

    @pytest.fixture
    def session_mgr(self):
        mgr = ConversationSessionManager()
        return mgr

    def test_clarification_followup_resolution(self, session_mgr):
        sess_id = "test_turn_clarif"
        session = session_mgr.get_or_create_session(sess_id)
        session.pending_clarification = {
            "type": "folder_name",
            "destination": "Desktop",
            "target_dir": "C:\\Users\\aradb\\Desktop",
        }

        # User replies with the folder name
        resolved, inferred = session_mgr.resolve_contextual_references(
            current_prompt="JARVIS Projects",
            history=[],
            session_id=sess_id,
        )
        assert "Create a folder on Desktop called JARVIS Projects" in resolved
        assert inferred.get("resolved_folder_name") == "JARVIS Projects"
        assert session.pending_clarification is None

    def test_anaphoric_nested_folder_creation(self, session_mgr):
        sess_id = "test_turn_nesting"
        session = session_mgr.get_or_create_session(sess_id)
        python_dir = Path("C:\\Users\\aradb\\Desktop\\Python")
        session.last_created_directory_path = python_dir
        session.last_created_directory_name = "Python"

        # User says: "Put another folder inside it called Projects"
        resolved, inferred = session_mgr.resolve_contextual_references(
            current_prompt="Put another folder inside it called Projects",
            history=[],
            session_id=sess_id,
        )
        assert str(python_dir) in resolved
        assert "Projects" in resolved
        assert inferred.get("parent_directory_path") == str(python_dir)

    def test_persian_nested_folder_creation(self, session_mgr):
        sess_id = "test_turn_nesting_fa"
        session = session_mgr.get_or_create_session(sess_id)
        parent_dir = Path("C:\\Users\\aradb\\Desktop\\MyCode")
        session.last_created_directory_path = parent_dir
        session.last_created_directory_name = "MyCode"

        # User says: "یه پوشه داخلش بساز به اسم Tests"
        resolved, inferred = session_mgr.resolve_contextual_references(
            current_prompt="یه پوشه داخلش بساز به اسم Tests",
            history=[],
            session_id=sess_id,
        )
        assert str(parent_dir) in resolved
        assert "Tests" in resolved

    def test_destination_correction(self, session_mgr):
        sess_id = "test_turn_correction"
        session = session_mgr.get_or_create_session(sess_id)
        session.last_created_directory_name = "Reports"

        # User corrects destination: "No, I meant Documents"
        resolved, inferred = session_mgr.resolve_contextual_references(
            current_prompt="No, I meant Documents",
            history=[],
            session_id=sess_id,
        )
        assert "Create a folder in Documents called Reports" in resolved
        assert inferred.get("destination_correction") == "Documents"


class TestTruthfulOutcomeSynthesis:
    """Test deterministic outcome synthesis for directory creation and tool results."""

    @pytest.fixture
    def executor(self):
        return AgentExecutor(
            tool_registry=MagicMock(),
            provider_manager=MagicMock(),
            planner=MagicMock(),
            state_machine=MagicMock(),
        )

    def test_directory_created_synthesis(self, executor):
        step = PlanStep(
            description="Create folder",
            step_type=StepType.TOOL_CALL,
            tool_name="file_create_directory",
            status=StepStatus.COMPLETED,
            result={
                "directory_name": "TestDir",
                "directory_path": r"C:\Users\aradb\Desktop\TestDir",
                "already_exists": False,
                "verified": True,
            },
        )
        msg = executor._synthesize_deterministic_outcome([step], "create folder TestDir on desktop")
        assert "created the folder 'TestDir' on your Desktop" in msg

    def test_directory_already_exists_synthesis(self, executor):
        step = PlanStep(
            description="Create folder",
            step_type=StepType.TOOL_CALL,
            tool_name="file_create_directory",
            status=StepStatus.COMPLETED,
            result={
                "directory_name": "TestDir",
                "directory_path": r"C:\Users\aradb\Desktop\TestDir",
                "already_exists": True,
                "verified": True,
            },
        )
        msg = executor._synthesize_deterministic_outcome([step], "create folder TestDir on desktop")
        assert "already exists on your Desktop" in msg
