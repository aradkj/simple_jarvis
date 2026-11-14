"""Unit tests for Restricted Terminal Agent in Phase 8."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.execution_context import ExecutionContext
from tools.base import ToolExecutionStatus
from tools.terminal.command_registry import (
    CommandRegistry,
    CommandRegistryError,
)
from tools.terminal.terminal_service import (
    TerminalService,
)
from tools.terminal.terminal_tools import (
    TerminalExecuteCommandInput,
    TerminalExecuteCommandTool,
    TerminalListCommandsInput,
    TerminalListCommandsTool,
)


class TestCommandRegistry:
    """Tests for central command registry security and whitelisting."""

    def test_default_commands_registered(self):
        reg = CommandRegistry()
        commands = reg.list_commands()
        cmd_ids = {c["command_id"] for c in commands}

        assert "git_status" in cmd_ids
        assert "git_diff" in cmd_ids
        assert "git_log" in cmd_ids
        assert "python_env_info" in cmd_ids
        assert "pip_list" in cmd_ids
        assert "run_tests" in cmd_ids
        assert "run_linter" in cmd_ids

    def test_unregistered_command_rejected(self):
        reg = CommandRegistry()
        with pytest.raises(CommandRegistryError) as exc_info:
            reg.build_command_args("rm_rf_root", {}, Path.cwd())
        assert "not in the approved terminal command registry" in str(exc_info.value)

    def test_arbitrary_shell_strings_rejected(self):
        reg = CommandRegistry()
        with pytest.raises(CommandRegistryError):
            reg.build_command_args("bash -c 'whoami'", {}, Path.cwd())

    def test_metacharacters_in_parameters_blocked(self):
        reg = CommandRegistry()
        # git_diff with malicious target_path containing pipe or semicolon
        with pytest.raises(CommandRegistryError) as exc:
            reg.build_command_args("git_diff", {"target_path": "file.py; rm -rf /"}, Path.cwd())
        assert "Dangerous shell characters detected" in str(exc.value)

        with pytest.raises(CommandRegistryError):
            reg.build_command_args("git_diff", {"target_path": "file.py | echo pwned"}, Path.cwd())


class TestTerminalService:
    """Tests for terminal execution service and isolation."""

    def test_execute_python_env_info(self):
        svc = TerminalService()
        res = svc.execute_command("python_env_info")
        assert res.success is True
        assert res.exit_code == 0
        assert "Python 3." in (res.stdout + res.stderr)
        assert res.duration_ms > 0

    def test_environment_sanitization_strips_secrets(self):
        svc = TerminalService()
        with patch.dict(
            os.environ, {"GEMINI_API_KEY": "secret_key_123", "AWS_SECRET_ACCESS_KEY": "aws_secret"}
        ):
            clean_env = svc._prepare_environment()
            assert "GEMINI_API_KEY" not in clean_env
            assert "AWS_SECRET_ACCESS_KEY" not in clean_env
            assert clean_env.get("PYTHONUNBUFFERED") == "1"

    def test_execution_timeout_enforced(self):
        svc = TerminalService()
        # Test short timeout with a mock or long command
        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None  # simulate hanging process
            mock_popen.return_value = mock_proc

            res = svc.execute_command("git_status", timeout_seconds=0.1)
            assert res.success is False
            assert "timed out" in res.stderr
            mock_proc.kill.assert_called()

    def test_cancellation_enforced(self):
        svc = TerminalService()
        ctx = ExecutionContext()
        ctx.cancel()

        with patch("subprocess.Popen") as mock_popen:
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            res = svc.execute_command("git_status", context=ctx)
            assert res.success is False
            assert "cancelled by user" in res.stderr
            mock_proc.kill.assert_called()


class TestTerminalTools:
    """Tests executing terminal tools."""

    def test_list_commands_tool(self):
        tool = TerminalListCommandsTool()
        ctx = ExecutionContext()
        res = tool.execute(TerminalListCommandsInput(), ctx)
        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["commands_count"] >= 7

    def test_execute_command_tool_success(self):
        tool = TerminalExecuteCommandTool()
        ctx = ExecutionContext()
        res = tool.execute(TerminalExecuteCommandInput(command_id="python_env_info"), ctx)
        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["exit_code"] == 0

    def test_execute_command_tool_unregistered_fails(self):
        tool = TerminalExecuteCommandTool()
        ctx = ExecutionContext()
        res = tool.execute(
            TerminalExecuteCommandInput(command_id="unregistered_malicious_cmd"), ctx
        )
        assert res.status == ToolExecutionStatus.FAILED
