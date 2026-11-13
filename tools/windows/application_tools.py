"""Windows Application Management Tools for JARVIS Phase 6."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult
from tools.windows.windows_service import WindowsControlService

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


class AppListInput(BaseModel):
    """Empty schema for listing applications."""

    pass


class AppLaunchInput(BaseModel):
    """Input parameters for launching an approved application."""

    app_id: str = Field(
        description="Application identifier or executable name from configured allowlist (e.g. 'notepad', 'calc', 'chrome', 'code')"
    )


class AppCloseInput(BaseModel):
    """Input parameters for closing a desktop application."""

    app_id: str = Field(
        description="Application identifier to close (e.g. 'notepad', 'calc', 'chrome')"
    )
    pid: int | None = Field(
        default=None,
        description="Optional specific process ID to close. If omitted, all instances are gracefully closed.",
    )
    expected_creation_time: int | None = Field(
        default=None,
        description="Optional expected process creation timestamp to defeat PID reuse.",
    )
    graceful: bool = Field(
        default=True,
        description="Whether to perform a graceful close via WM_CLOSE message.",
    )


class WindowsAppListTool(BaseTool):
    """Tool to inspect available, installed, and running desktop applications."""

    name = "windows_app_list"
    description = "List approved desktop applications, installation status on disk, and active running process instances."
    category = PermissionCategory.WINDOWS_APP_READ
    input_schema = AppListInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Application listing cancelled by user")

        try:
            catalog = self.service.get_application_catalog()
            return ToolResult.success(data=[app.model_dump() for app in catalog])
        except Exception as exc:
            return ToolResult.failed(f"Failed to list applications: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={"type": "object", "properties": {}},
            requires_approval=False,
        )


class WindowsAppLaunchTool(BaseTool):
    """Tool to launch an approved desktop application from the safe allowlist."""

    name = "windows_app_launch"
    description = "Launch an approved Windows desktop application (e.g. Notepad, Calculator, Chrome, VS Code) from the safe allowlist."
    category = PermissionCategory.WINDOWS_APP_LAUNCH
    input_schema = AppLaunchInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Application launch cancelled by user")

        app_id = getattr(params, "app_id", "")
        try:
            res = self.service.launch_application(app_id)
            return ToolResult.success(data=res)
        except Exception as exc:
            return ToolResult.failed(f"Failed to launch application '{app_id}': {exc}")

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
                    "app_id": {
                        "type": "string",
                        "description": "Application identifier from allowlist (e.g. 'notepad', 'calc', 'chrome', 'code')",
                    }
                },
                "required": ["app_id"],
            },
            requires_approval=True,
        )


class WindowsAppCloseTool(BaseTool):
    """Tool to gracefully close an active desktop application."""

    name = "windows_app_close"
    description = "Gracefully close an active desktop application by identifier or PID using native Windows messages."
    category = PermissionCategory.WINDOWS_APP_CLOSE
    input_schema = AppCloseInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Application close cancelled by user")

        app_id = getattr(params, "app_id", "")
        pid = getattr(params, "pid", None)
        graceful = getattr(params, "graceful", True)
        expected_creation_time = getattr(params, "expected_creation_time", None)

        try:
            res = self.service.close_application(
                app_id,
                pid=pid,
                graceful=graceful,
                expected_creation_time=expected_creation_time,
            )
            return ToolResult.success(data=res)
        except Exception as exc:
            return ToolResult.failed(f"Failed to close application '{app_id}': {exc}")

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
                    "app_id": {
                        "type": "string",
                        "description": "Application identifier to close (e.g. 'notepad', 'calc', 'chrome')",
                    },
                    "pid": {
                        "type": "integer",
                        "description": "Optional specific process ID",
                    },
                    "graceful": {
                        "type": "boolean",
                        "description": "Whether to request graceful closure",
                        "default": True,
                    },
                },
                "required": ["app_id"],
            },
            requires_approval=True,
        )
