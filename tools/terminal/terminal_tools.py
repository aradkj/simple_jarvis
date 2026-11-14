"""Terminal Tools for JARVIS Phase 8.

Provides:
- TerminalExecuteCommandTool: Safely executes an approved command from the central registry.
- TerminalListCommandsTool: Lists available registry commands and their argument schemas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult
from tools.terminal.terminal_service import get_terminal_service

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


class TerminalExecuteCommandInput(BaseModel):
    command_id: str = Field(
        description="ID of the command to execute from the approved registry (e.g., git_status, git_diff, git_log, run_tests, run_linter, pip_list)"
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value arguments for the registered command",
    )
    working_directory: str | None = Field(
        default=None,
        description="Authorized working directory path (defaults to current project workspace)",
    )
    timeout_seconds: float | None = Field(
        default=None,
        description="Optional execution timeout override in seconds",
    )


class TerminalListCommandsInput(BaseModel):
    pass


class TerminalExecuteCommandTool(BaseTool):
    """Tool to execute pre-approved commands safely without arbitrary shell execution."""

    name = "terminal_execute_command"
    description = (
        "Execute a safe, pre-approved terminal command (git status/diff/log, pytest, ruff, pip) "
        "inside an authorized workspace. Arbitrary shell strings are strictly prohibited."
    )
    category = PermissionCategory.TERMINAL_EXECUTE
    input_schema = TerminalExecuteCommandInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Terminal command cancelled by user")

        command_id = getattr(params, "command_id", "")
        parameters = getattr(params, "parameters", {})
        working_directory = getattr(params, "working_directory", None)
        timeout_seconds = getattr(params, "timeout_seconds", None)

        service = get_terminal_service()
        res = service.execute_command(
            command_id=command_id,
            parameters=parameters,
            working_directory=working_directory,
            timeout_seconds=timeout_seconds,
            context=context,
        )

        if not res.success:
            return ToolResult.failed(
                f"Command '{command_id}' failed: {res.stderr or res.message}",
                data={
                    "command_id": command_id,
                    "exit_code": res.exit_code,
                    "stdout": res.stdout,
                    "stderr": res.stderr,
                    "duration_ms": res.duration_ms,
                    "working_directory": res.working_directory,
                },
            )

        return ToolResult.success(
            message=res.message,
            data={
                "command_id": command_id,
                "exit_code": res.exit_code,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "duration_ms": res.duration_ms,
                "working_directory": res.working_directory,
                "truncated": res.truncated,
            },
        )

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.MEDIUM,
            parameters_schema={
                "type": "object",
                "properties": {
                    "command_id": {
                        "type": "string",
                        "description": "Registered command ID (e.g. git_status, git_diff, run_tests, run_linter)",
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Optional parameters dict for command",
                    },
                    "working_directory": {
                        "type": "string",
                        "description": "Authorized working directory",
                    },
                    "timeout_seconds": {
                        "type": "number",
                        "description": "Execution timeout in seconds",
                    },
                },
                "required": ["command_id"],
            },
            requires_approval=False,
            timeout_seconds=60.0,
        )


class TerminalListCommandsTool(BaseTool):
    """Tool to inspect the approved registry of terminal commands."""

    name = "terminal_list_commands"
    description = "List all permitted commands in the restricted terminal registry along with their parameters and risk levels."
    category = PermissionCategory.TERMINAL_EXECUTE
    input_schema = TerminalListCommandsInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Command listing cancelled by user")

        service = get_terminal_service()
        commands = service.registry.list_commands()
        return ToolResult.success(
            data={"commands_count": len(commands), "commands": commands},
            message=f"Found {len(commands)} registered terminal commands.",
        )

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={"type": "object", "properties": {}},
            requires_approval=False,
            timeout_seconds=10.0,
        )
