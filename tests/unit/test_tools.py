"""Unit tests for tool definitions and registry execution contracts."""

from typing import Any

import pytest
from pydantic import BaseModel, Field

from core.events import EventBus
from core.execution_context import ExecutionContext
from core.permissions import (
    PermissionCategory,
    StrictDefaultDenyPermissionManager,
)
from core.tool_registry import (
    ToolNotFoundError,
    ToolRegistrationError,
    ToolRegistry,
)
from tools.base import BaseTool, ToolExecutionStatus, ToolResult


class DummyInput(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=5, ge=1, le=100)


class MockEchoTool(BaseTool):
    name = "mock_echo"
    description = "A mock tool that echoes input parameters"
    category = PermissionCategory.READ_ONLY
    input_schema = DummyInput

    def execute(self, params: DummyInput, context: ExecutionContext) -> ToolResult:
        return ToolResult.success(data={"echo": params.query, "limit": params.limit})


def test_tool_definition_validation() -> None:
    """Verify tool without mandatory attributes raises an exception at instantiation."""

    class MissingExecuteTool(BaseTool):
        name = "bad_tool"
        description = "bad description"
        category = PermissionCategory.READ_ONLY
        input_schema = DummyInput

    with pytest.raises(TypeError):
        MissingExecuteTool()  # Missing abstract method 'execute'

    class MissingMetadataTool(BaseTool):
        def execute(self, params: Any, context: ExecutionContext) -> ToolResult:
            return ToolResult.success()

    with pytest.raises(ValueError):
        MissingMetadataTool()  # Missing name, description, category, input_schema


def test_tool_registry_registration() -> None:
    """Verify tool can be registered, retrieved, and unregistered."""
    registry = ToolRegistry()
    tool = MockEchoTool()

    registry.register(tool)
    assert tool.name in registry.list_tool_names()
    assert registry.get(tool.name) is tool

    # Duplicate registration must fail
    with pytest.raises(ToolRegistrationError):
        registry.register(tool)

    registry.unregister(tool.name)
    assert tool.name not in registry.list_tool_names()

    # Unregistering non-existent tool raises ToolNotFoundError
    with pytest.raises(ToolNotFoundError):
        registry.unregister("non_existent_tool")


def test_tool_execution_permission_enforcement() -> None:
    """Verify registry strictly blocks execution when permission is denied."""
    perm_manager = StrictDefaultDenyPermissionManager()
    event_bus = EventBus()
    registry = ToolRegistry(permission_manager=perm_manager, event_bus=event_bus)
    tool = MockEchoTool()
    registry.register(tool)

    context = ExecutionContext()

    # Default-deny: must return denied
    denied_res = registry.execute_tool(tool.name, {"query": "hello"}, context)
    assert denied_res.status == ToolExecutionStatus.DENIED
    assert "default-deny" in str(denied_res.error).lower()

    # Grant permission and re-execute: must succeed
    perm_manager.grant(PermissionCategory.READ_ONLY)
    success_res = registry.execute_tool(tool.name, {"query": "hello", "limit": 10}, context)
    assert success_res.status == ToolExecutionStatus.SUCCESS
    assert success_res.data == {"echo": "hello", "limit": 10}


def test_tool_execution_schema_validation() -> None:
    """Verify invalid input schema parameters return failed status."""
    perm_manager = StrictDefaultDenyPermissionManager()
    perm_manager.grant(PermissionCategory.READ_ONLY)
    registry = ToolRegistry(permission_manager=perm_manager)
    tool = MockEchoTool()
    registry.register(tool)

    # Missing mandatory 'query' field
    res = registry.execute_tool(tool.name, {"limit": 10}, ExecutionContext())
    assert res.status == ToolExecutionStatus.FAILED
    assert "Invalid parameters" in str(res.error)


def test_tool_execution_cancellation() -> None:
    """Verify tool invocation aborts if execution context is cancelled."""
    perm_manager = StrictDefaultDenyPermissionManager()
    perm_manager.grant(PermissionCategory.READ_ONLY)
    registry = ToolRegistry(permission_manager=perm_manager)
    tool = MockEchoTool()
    registry.register(tool)

    context = ExecutionContext()
    context.cancel()  # Signal cancellation

    res = registry.execute_tool(tool.name, {"query": "test"}, context)
    assert res.status == ToolExecutionStatus.CANCELLED
