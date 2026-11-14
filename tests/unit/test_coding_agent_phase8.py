"""Unit tests for Antigravity Coding Agent Subsystem in Phase 8."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.execution_context import ExecutionContext
from tools.base import ToolExecutionStatus
from tools.coding_agent.coding_tools import (
    CodingAgentStatusInput,
    CodingAgentStatusTool,
    CodingAgentVerifyTaskInput,
    CodingAgentVerifyTaskTool,
)
from tools.coding_agent.exceptions import (
    AntigravityNotFoundError,
    WorkspacePolicyViolationError,
)
from tools.coding_agent.models import CodingTaskStatus, VerificationResult
from tools.coding_agent.process_manager import AntigravityProcessManager
from tools.coding_agent.result_verifier import CodingResultVerifier
from tools.coding_agent.stream_parser import StreamParser
from tools.coding_agent.task_manager import CodingTaskManager
from tools.coding_agent.workspace_policy import WorkspacePolicy


class TestWorkspacePolicy:
    """Tests for workspace containment and security policies."""

    def test_current_workspace_valid(self):
        ws = Path.cwd().resolve()
        res = WorkspacePolicy.validate_workspace(ws)
        assert res == ws

    def test_root_drive_rejected(self):
        root_path = Path("C:\\") if Path("C:\\").exists() else Path("/")
        with pytest.raises(WorkspacePolicyViolationError) as exc:
            WorkspacePolicy.validate_workspace(root_path)
        assert "Root drive cannot be" in str(exc.value)

    def test_system_directories_rejected(self):
        sys_dir = Path("C:\\Windows")
        if sys_dir.exists():
            with pytest.raises(WorkspacePolicyViolationError) as exc:
                WorkspacePolicy.validate_workspace(sys_dir)
            assert "System directory cannot be" in str(exc.value)

    def test_non_existent_workspace_rejected(self):
        fake = Path("C:\\AI\\jarvis\\non_existent_folder_xyz_123")
        with pytest.raises(WorkspacePolicyViolationError):
            WorkspacePolicy.validate_workspace(fake)


class TestStreamParser:
    """Tests for parsing NDJSON streams emitted by agy CLI."""

    def test_parse_init_event(self):
        parser = StreamParser()
        raw = json.dumps(
            {
                "event": "init",
                "conversation_id": "test-conv-123",
                "init": {"cwd": "C:\\test", "tools": ["view_file", "run_command"]},
            }
        )
        ev = parser.parse_line(raw)
        assert ev is not None
        assert ev.event_type == "init"
        assert parser.conversation_id == "test-conv-123"

    def test_parse_step_update_and_accumulate_text(self):
        parser = StreamParser()
        raw1 = json.dumps(
            {
                "event": "step_update",
                "step_update": {
                    "conversation_id": "test-conv-123",
                    "step_index": 1,
                    "state": "ACTIVE",
                    "text_delta": "def foo():\n",
                },
            }
        )
        raw2 = json.dumps(
            {
                "event": "step_update",
                "step_update": {
                    "conversation_id": "test-conv-123",
                    "step_index": 1,
                    "state": "DONE",
                    "text_delta": "    return 42\n",
                },
            }
        )
        parser.parse_line(raw1)
        parser.parse_line(raw2)

        full = parser.get_full_response()
        assert full == "def foo():\n    return 42\n"
        assert parser.detected_soft_denial is False

    def test_parse_result_event(self):
        parser = StreamParser()
        raw = json.dumps(
            {
                "event": "result",
                "result": {
                    "conversation_id": "test-conv-123",
                    "status": "SUCCESS",
                    "response": "Done implementing feature.",
                    "duration_seconds": 2.5,
                    "usage": {"total_tokens": 1000},
                },
            }
        )
        ev = parser.parse_line(raw)
        assert ev is not None
        assert ev.event_type == "result"
        assert parser.get_full_response() == "Done implementing feature."
        assert parser.final_result["usage"]["total_tokens"] == 1000

    def test_soft_denial_detection(self):
        parser = StreamParser()
        raw = json.dumps(
            {
                "event": "step_update",
                "step_update": {
                    "text_delta": "I cannot perform this operation due to safety limits."
                },
            }
        )
        parser.parse_line(raw)
        assert parser.detected_soft_denial is True


class TestProcessManagerAndHealth:
    """Tests for discovering agy CLI and health inspection."""

    def test_locate_executable_explicit_path(self, tmp_path: Path):
        dummy_exe = tmp_path / "mock_agy.exe"
        dummy_exe.touch()
        mgr = AntigravityProcessManager(executable_path=str(dummy_exe))
        exe = mgr.locate_executable()
        assert exe == dummy_exe.resolve()

    def test_locate_executable_via_path_lookup(self, tmp_path: Path):
        dummy_exe = tmp_path / "agy.exe"
        dummy_exe.touch()
        with patch("shutil.which", return_value=str(dummy_exe)):
            mgr = AntigravityProcessManager()
            exe = mgr.locate_executable()
            assert exe == dummy_exe.resolve()

    def test_locate_executable_not_found_raises_error(self):
        with (
            patch("shutil.which", return_value=None),
            patch.object(AntigravityProcessManager, "COMMON_AGY_PATHS", []),
        ):
            mgr = AntigravityProcessManager()
            with pytest.raises(AntigravityNotFoundError) as exc:
                mgr.locate_executable()
            assert "could not be found" in str(exc.value)

    def test_check_health_healthy(self):
        mgr = AntigravityProcessManager()
        mock_path = Path("/mock/bin/agy")
        with (
            patch.object(mgr, "locate_executable", return_value=mock_path),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            health = mgr.check_health()
            assert health["installed"] is True
            assert health["healthy"] is True
            assert health["executable_path"] == str(mock_path)

    def test_check_health_not_installed(self):
        mgr = AntigravityProcessManager()
        with patch.object(
            mgr, "locate_executable", side_effect=AntigravityNotFoundError("CLI not installed")
        ):
            health = mgr.check_health()
            assert health["installed"] is False
            assert health["healthy"] is False
            assert "CLI not installed" in health["error"]


class TestCodingTaskManagerAndRemediation:
    """Tests for task lifecycle and automated verification/remediation loop."""

    def test_task_delegation_with_mocked_process(self, tmp_path: Path):
        mgr = CodingTaskManager()
        sample_ndjson = [
            json.dumps({"event": "init", "conversation_id": "mock-conv", "init": {}}) + "\n",
            json.dumps({"event": "step_update", "step_update": {"text_delta": "Task completed."}})
            + "\n",
            json.dumps(
                {"event": "result", "result": {"status": "SUCCESS", "response": "Task completed."}}
            )
            + "\n",
        ]

        with patch.object(mgr.process_manager, "execute_stream") as mock_exec:
            mock_exec.return_value = (0, sample_ndjson, "", 1.5)
            with patch.object(CodingResultVerifier, "verify_workspace") as mock_verify:
                mock_verify.return_value = VerificationResult(
                    verified=True,
                    git_changed_files=["app.py"],
                    git_diff_summary="app.py | 2 +-",
                    tests_executed=True,
                    tests_passed=True,
                )

                task = mgr.delegate_task(
                    prompt="Add a new route",
                    workspace_path=tmp_path,
                    auto_verify=True,
                )

                assert task.status == CodingTaskStatus.COMPLETED
                assert task.response_text == "Task completed."
                assert task.verification is not None
                assert task.verification.verified is True
                assert task.remediation_attempts == 0

    def test_remediation_loop_on_failing_tests(self, tmp_path: Path):
        mgr = CodingTaskManager()
        sample_ndjson = [
            json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "Done."}})
            + "\n",
        ]

        # First verification fails, second verification passes
        fail_verif = VerificationResult(
            verified=False,
            git_changed_files=["app.py"],
            tests_executed=True,
            tests_passed=False,
            test_output="AssertionError: 1 != 2",
        )
        pass_verif = VerificationResult(
            verified=True,
            git_changed_files=["app.py"],
            tests_executed=True,
            tests_passed=True,
        )

        with patch.object(mgr.process_manager, "execute_stream") as mock_exec:
            mock_exec.return_value = (0, sample_ndjson, "", 1.0)
            with patch.object(CodingResultVerifier, "verify_workspace") as mock_verify:
                mock_verify.side_effect = [fail_verif, pass_verif]

                task = mgr.delegate_task(
                    prompt="Fix the bug",
                    workspace_path=tmp_path,
                    auto_verify=True,
                )

                assert task.status == CodingTaskStatus.COMPLETED
                assert task.remediation_attempts == 1
                assert task.verification.verified is True


class TestCodingTools:
    """Tests for Antigravity coding tools."""

    def test_status_tool(self):
        tool = CodingAgentStatusTool()
        ctx = ExecutionContext()
        res = tool.execute(CodingAgentStatusInput(), ctx)
        assert res.status == ToolExecutionStatus.SUCCESS
        assert "enabled" in res.data
        assert isinstance(res.data["installed"], bool)

    def test_status_tool_with_mocked_installed_status(self):
        tool = CodingAgentStatusTool()
        ctx = ExecutionContext()
        mock_health = {
            "installed": True,
            "healthy": True,
            "executable_path": "/mock/bin/agy",
            "return_code": 0,
        }
        with patch.object(AntigravityProcessManager, "check_health", return_value=mock_health):
            res = tool.execute(CodingAgentStatusInput(), ctx)
            assert res.status == ToolExecutionStatus.SUCCESS
            assert res.data["installed"] is True
            assert res.data["executable_path"] == "/mock/bin/agy"

    def test_verify_tool(self):
        tool = CodingAgentVerifyTaskTool()
        ctx = ExecutionContext()
        res = tool.execute(
            CodingAgentVerifyTaskInput(workspace_path=".", run_tests=False, run_linter=False), ctx
        )
        assert res.status == ToolExecutionStatus.SUCCESS
        assert "verified" in res.data
