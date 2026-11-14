"""Tools for delegating and monitoring coding tasks via Antigravity."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult
from tools.coding_agent.antigravity_adapter import get_antigravity_adapter

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


class CodingAgentStatusInput(BaseModel):
    pass


class CodingAgentDelegateTaskInput(BaseModel):
    prompt: str = Field(description="The coding task instructions and goals for Antigravity")
    workspace_path: str | None = Field(
        default=None,
        description="Target workspace directory (defaults to current project root)",
    )
    model: str | None = Field(
        default=None,
        description="Model to use for coding task (defaults to configured antigravity_model)",
    )
    auto_verify: bool = Field(
        default=True,
        description="Whether to automatically verify git changes and run tests upon completion",
    )


class CodingAgentGetTaskStatusInput(BaseModel):
    task_id: str = Field(description="Unique ID of the delegated coding task")


class CodingAgentCancelTaskInput(BaseModel):
    task_id: str = Field(description="Unique ID of the coding task to cancel")


class CodingAgentVerifyTaskInput(BaseModel):
    workspace_path: str | None = Field(
        default=None,
        description="Workspace directory to verify (defaults to current project root)",
    )
    run_tests: bool = Field(default=True, description="Whether to execute project test suite")
    run_linter: bool = Field(default=True, description="Whether to execute project linter")


class CodingAgentStatusTool(BaseTool):
    """Tool to inspect Antigravity CLI installation and readiness."""

    name = "coding_agent_status"
    description = (
        "Check Google Antigravity CLI installation status, model configuration, and active tasks."
    )
    category = PermissionCategory.CODING_AGENT_DELEGATE
    input_schema = CodingAgentStatusInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Status check cancelled by user")

        adapter = get_antigravity_adapter()
        status_info = adapter.get_status()
        return ToolResult.success(data=status_info, message="Antigravity status retrieved.")

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


class CodingAgentDelegateTaskTool(BaseTool):
    """Tool to delegate a software development or code repair task to Google Antigravity."""

    name = "coding_agent_delegate_task"
    description = (
        "Delegate a programming or codebase modification task to Google Antigravity (agy CLI). "
        "Streams progress and independently verifies git diff and tests."
    )
    category = PermissionCategory.CODING_AGENT_DELEGATE
    input_schema = CodingAgentDelegateTaskInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Coding delegation cancelled by user")

        prompt = getattr(params, "prompt", "")
        workspace_path = getattr(params, "workspace_path", None)
        model = getattr(params, "model", None)
        auto_verify = getattr(params, "auto_verify", True)

        adapter = get_antigravity_adapter()
        task = adapter.delegate(
            prompt=prompt,
            workspace_path=workspace_path,
            model=model,
            auto_verify=auto_verify,
            context=context,
        )

        if task.status.value == "failed":
            return ToolResult.failed(
                f"Antigravity task failed: {task.error_message}",
                data=task.to_dict(),
            )

        return ToolResult.success(
            message=f"Antigravity task completed ({task.duration_seconds:.1f}s).",
            data=task.to_dict(),
        )

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.HIGH,
            parameters_schema={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Software engineering instructions",
                    },
                    "workspace_path": {
                        "type": "string",
                        "description": "Target workspace directory",
                    },
                    "model": {"type": "string", "description": "Model override for agy"},
                    "auto_verify": {"type": "boolean", "default": True},
                },
                "required": ["prompt"],
            },
            requires_approval=True,
            timeout_seconds=300.0,
        )


class CodingAgentGetTaskStatusTool(BaseTool):
    """Tool to query status and verification results of a delegated coding task."""

    name = "coding_agent_get_task_status"
    description = "Inspect the status, events, and verification outcome of a delegated coding task."
    category = PermissionCategory.CODING_AGENT_DELEGATE
    input_schema = CodingAgentGetTaskStatusInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Query cancelled by user")

        task_id = getattr(params, "task_id", "")
        adapter = get_antigravity_adapter()
        task = adapter.get_task(task_id)
        if not task:
            return ToolResult.failed(f"Task with ID '{task_id}' not found.")

        return ToolResult.success(data=task.to_dict())

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {"task_id": {"type": "string", "description": "Task ID"}},
                "required": ["task_id"],
            },
            requires_approval=False,
            timeout_seconds=10.0,
        )


class CodingAgentVerifyTaskTool(BaseTool):
    """Tool to independently verify git status, diff, tests, and linter for a workspace."""

    name = "coding_agent_verify_task"
    description = (
        "Independently inspect git diff, run tests, and check linter in an authorized workspace."
    )
    category = PermissionCategory.CODING_AGENT_VERIFY
    input_schema = CodingAgentVerifyTaskInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Verification cancelled by user")

        workspace_path = getattr(params, "workspace_path", None)
        run_tests = getattr(params, "run_tests", True)
        run_linter = getattr(params, "run_linter", True)

        adapter = get_antigravity_adapter()
        target_ws = workspace_path or "."
        res = adapter.verify_workspace(target_ws, run_tests=run_tests, run_linter=run_linter)

        return ToolResult.success(
            message=res.message,
            data={
                "verified": res.verified,
                "changed_files": res.git_changed_files,
                "diff_summary": res.git_diff_summary,
                "tests_executed": res.tests_executed,
                "tests_passed": res.tests_passed,
                "test_output": res.test_output,
                "linter_clean": res.linter_clean,
            },
        )

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "workspace_path": {"type": "string", "description": "Workspace to verify"},
                    "run_tests": {"type": "boolean", "default": True},
                    "run_linter": {"type": "boolean", "default": True},
                },
            },
            requires_approval=False,
            timeout_seconds=60.0,
        )
