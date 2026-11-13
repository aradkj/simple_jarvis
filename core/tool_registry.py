"""Tool registry and invocation coordinator for JARVIS."""

from typing import Any

from pydantic import ValidationError

from core.events import AgentEvent, AgentEventType, EventBus
from core.execution_context import ExecutionContext
from core.permissions import (
    BasePermissionManager,
    PermissionDecision,
    PermissionRequest,
    StrictDefaultDenyPermissionManager,
)
from infrastructure.logging import get_logger
from tools.base import BaseTool, ToolResult

logger = get_logger("tool_registry")


class ToolRegistrationError(Exception):
    """Raised when registering an invalid tool or duplicate tool name."""


class ToolNotFoundError(Exception):
    """Raised when requesting an unregistered tool."""


class ToolRegistry:
    """Registry for discovering, validating, and safely invoking tools."""

    def __init__(
        self,
        permission_manager: BasePermissionManager | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._tools: dict[str, BaseTool] = {}
        self.permission_manager = permission_manager or StrictDefaultDenyPermissionManager()
        self.event_bus = event_bus

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance in the registry."""
        if tool.name in self._tools:
            raise ToolRegistrationError(f"Tool with name '{tool.name}' is already registered.")
        self._tools[tool.name] = tool
        logger.debug(f"Registered tool: {tool.name} (category: {tool.category.value})")

    def unregister(self, tool_name: str) -> None:
        """Unregister a tool by name."""
        if tool_name not in self._tools:
            raise ToolNotFoundError(f"Tool '{tool_name}' is not registered.")
        del self._tools[tool_name]
        logger.debug(f"Unregistered tool: {tool_name}")

    def get(self, tool_name: str) -> BaseTool:
        """Retrieve a registered tool by name."""
        if tool_name not in self._tools:
            raise ToolNotFoundError(f"Tool '{tool_name}' not found in registry.")
        return self._tools[tool_name]

    def list_tools(self) -> list[BaseTool]:
        """Return a list of all registered tools."""
        return list(self._tools.values())

    def list_tool_names(self) -> list[str]:
        """Return names of all registered tools."""
        return list(self._tools.keys())

    def execute_tool(
        self,
        tool_name: str,
        params: dict[str, Any],
        context: ExecutionContext,
    ) -> ToolResult:
        """Validate, check permissions, and execute a tool safely.

        No unrestricted tool execution exists.
        """
        # 1. Check tool existence
        if tool_name not in self._tools:
            return ToolResult.failed(f"Tool '{tool_name}' is not registered.")

        tool = self._tools[tool_name]

        # 2. Check cancellation
        if context.is_cancelled():
            return ToolResult.cancelled("Execution cancelled before tool invocation.")

        # 3. Check permissions (Strict default-deny)
        perm_request = PermissionRequest(
            tool_name=tool.name,
            category=tool.category,
            action_summary=f"Execute tool '{tool.name}'",
            parameters=params,
        )
        perm_result = self.permission_manager.evaluate(perm_request)

        if self.event_bus:
            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.TOOL_EXECUTION_REQUESTED,
                    payload={"tool_name": tool_name, "category": tool.category.value},
                )
            )

        if perm_result.decision != PermissionDecision.GRANTED:
            logger.warning(f"Permission denied for tool '{tool_name}': {perm_result.reason}")
            if self.event_bus:
                self.event_bus.publish(
                    AgentEvent(
                        event_type=AgentEventType.PERMISSION_DENIED,
                        payload={"tool_name": tool_name, "reason": perm_result.reason},
                    )
                )
            return ToolResult.denied(perm_result.reason)

        # 4. Validate input schema (filter out internal underscore metadata)
        try:
            clean_params = {k: v for k, v in params.items() if not str(k).startswith("_")}
            validated_params = tool.validate_input(clean_params)
        except ValidationError as val_err:
            logger.error(f"Input validation failed for tool '{tool_name}': {val_err}")
            return ToolResult.failed(f"Invalid parameters for tool '{tool_name}': {val_err}")

        # 5. Execute tool safely
        try:
            result = tool.execute(validated_params, context)
            if self.event_bus:
                self.event_bus.publish(
                    AgentEvent(
                        event_type=AgentEventType.TOOL_EXECUTION_COMPLETED,
                        payload={"tool_name": tool_name, "status": result.status.value},
                    )
                )
            return result
        except Exception as exc:
            logger.exception(f"Unhandled exception during tool execution '{tool_name}': {exc}")
            return ToolResult.failed(f"Tool execution error: {exc}")
