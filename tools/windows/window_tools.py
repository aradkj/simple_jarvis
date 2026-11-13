"""Windows Window Management Tools for JARVIS Phase 6."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult
from tools.windows.windows_service import WindowsControlService

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


class WindowListInput(BaseModel):
    """Input parameters for listing windows."""

    query: str | None = Field(
        default=None, description="Optional title substring to filter windows"
    )
    pid: int | None = Field(default=None, description="Optional process ID to filter windows")
    app_name: str | None = Field(
        default=None, description="Optional process image name to filter windows"
    )


class WindowActionInput(BaseModel):
    """Input parameters for window state operations (focus, minimize, maximize, restore, close)."""

    hwnd: int = Field(description="Win32 Window Handle integer identifier")
    expected_pid: int | None = Field(
        default=None, description="Optional expected process ID owning the window"
    )
    expected_creation_time: int | None = Field(
        default=None, description="Optional expected creation timestamp to defeat PID reuse"
    )


class WindowsWindowListTool(BaseTool):
    """Tool to inspect active top-level desktop windows."""

    name = "windows_window_list"
    description = "Enumerate open desktop windows with window handles (HWND), titles, process names, and states (normal, minimized, maximized)."
    category = PermissionCategory.WINDOWS_WINDOW_READ
    input_schema = WindowListInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Window enumeration cancelled by user")

        query = getattr(params, "query", None)
        pid = getattr(params, "pid", None)
        app_name = getattr(params, "app_name", None)

        try:
            windows = self.service.find_windows(query=query, pid=pid, app_name=app_name)
            return ToolResult.success(data=[w.model_dump() for w in windows])
        except Exception as exc:
            return ToolResult.failed(f"Failed to enumerate windows: {exc}")

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
                    "query": {"type": "string", "description": "Optional title filter"},
                    "pid": {"type": "integer", "description": "Optional PID filter"},
                    "app_name": {"type": "string", "description": "Optional process name filter"},
                },
            },
            requires_approval=False,
        )


class WindowsWindowFocusTool(BaseTool):
    """Tool to activate and bring a window to the foreground."""

    name = "windows_window_focus"
    description = "Bring an open window to the foreground and activate desktop focus."
    category = PermissionCategory.WINDOWS_WINDOW_CONTROL
    input_schema = WindowActionInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Window focus cancelled by user")

        hwnd = getattr(params, "hwnd", 0)
        expected_pid = getattr(params, "expected_pid", None)
        expected_creation_time = getattr(params, "expected_creation_time", None)
        kwargs = {}
        if expected_pid is not None:
            kwargs["expected_pid"] = expected_pid
        if expected_creation_time is not None:
            kwargs["expected_creation_time"] = expected_creation_time

        try:
            self.service.focus_window(hwnd, **kwargs)
            return ToolResult.success(data={"hwnd": hwnd, "status": "focused"})
        except Exception as exc:
            return ToolResult.failed(f"Failed to focus window {hwnd}: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {"hwnd": {"type": "integer", "description": "Target window handle"}},
                "required": ["hwnd"],
            },
            requires_approval=False,
        )


class WindowsWindowMinimizeTool(BaseTool):
    """Tool to minimize a desktop window."""

    name = "windows_window_minimize"
    description = "Minimize an open desktop window to the taskbar."
    category = PermissionCategory.WINDOWS_WINDOW_CONTROL
    input_schema = WindowActionInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Window minimize cancelled by user")

        hwnd = getattr(params, "hwnd", 0)
        expected_pid = getattr(params, "expected_pid", None)
        expected_creation_time = getattr(params, "expected_creation_time", None)
        kwargs = {}
        if expected_pid is not None:
            kwargs["expected_pid"] = expected_pid
        if expected_creation_time is not None:
            kwargs["expected_creation_time"] = expected_creation_time

        try:
            self.service.minimize_window(hwnd, **kwargs)
            return ToolResult.success(data={"hwnd": hwnd, "status": "minimized"})
        except Exception as exc:
            return ToolResult.failed(f"Failed to minimize window {hwnd}: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {"hwnd": {"type": "integer", "description": "Target window handle"}},
                "required": ["hwnd"],
            },
            requires_approval=False,
        )


class WindowsWindowMaximizeTool(BaseTool):
    """Tool to maximize a desktop window."""

    name = "windows_window_maximize"
    description = "Maximize an open desktop window to fill the monitor."
    category = PermissionCategory.WINDOWS_WINDOW_CONTROL
    input_schema = WindowActionInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Window maximize cancelled by user")

        hwnd = getattr(params, "hwnd", 0)
        expected_pid = getattr(params, "expected_pid", None)
        expected_creation_time = getattr(params, "expected_creation_time", None)
        kwargs = {}
        if expected_pid is not None:
            kwargs["expected_pid"] = expected_pid
        if expected_creation_time is not None:
            kwargs["expected_creation_time"] = expected_creation_time

        try:
            self.service.maximize_window(hwnd, **kwargs)
            return ToolResult.success(data={"hwnd": hwnd, "status": "maximized"})
        except Exception as exc:
            return ToolResult.failed(f"Failed to maximize window {hwnd}: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {"hwnd": {"type": "integer", "description": "Target window handle"}},
                "required": ["hwnd"],
            },
            requires_approval=False,
        )


class WindowsWindowRestoreTool(BaseTool):
    """Tool to restore a minimized or maximized desktop window."""

    name = "windows_window_restore"
    description = "Restore an open desktop window to its normal desktop placement."
    category = PermissionCategory.WINDOWS_WINDOW_CONTROL
    input_schema = WindowActionInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Window restore cancelled by user")

        hwnd = getattr(params, "hwnd", 0)
        expected_pid = getattr(params, "expected_pid", None)
        expected_creation_time = getattr(params, "expected_creation_time", None)
        kwargs = {}
        if expected_pid is not None:
            kwargs["expected_pid"] = expected_pid
        if expected_creation_time is not None:
            kwargs["expected_creation_time"] = expected_creation_time

        try:
            self.service.restore_window(hwnd, **kwargs)
            return ToolResult.success(data={"hwnd": hwnd, "status": "restored"})
        except Exception as exc:
            return ToolResult.failed(f"Failed to restore window {hwnd}: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {"hwnd": {"type": "integer", "description": "Target window handle"}},
                "required": ["hwnd"],
            },
            requires_approval=False,
        )


class WindowsWindowCloseTool(BaseTool):
    """Tool to gracefully close a desktop window."""

    name = "windows_window_close"
    description = "Gracefully close a desktop window by handle using native Win32 WM_CLOSE message."
    category = PermissionCategory.WINDOWS_WINDOW_CONTROL
    input_schema = WindowActionInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Window close cancelled by user")

        hwnd = getattr(params, "hwnd", 0)
        expected_pid = getattr(params, "expected_pid", None)
        expected_creation_time = getattr(params, "expected_creation_time", None)
        kwargs = {}
        if expected_pid is not None:
            kwargs["expected_pid"] = expected_pid
        if expected_creation_time is not None:
            kwargs["expected_creation_time"] = expected_creation_time

        try:
            self.service.close_window(hwnd, **kwargs)
            return ToolResult.success(data={"hwnd": hwnd, "status": "closed"})
        except Exception as exc:
            return ToolResult.failed(f"Failed to close window {hwnd}: {exc}")

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
                    "hwnd": {"type": "integer", "description": "Target window handle to close"}
                },
                "required": ["hwnd"],
            },
            requires_approval=True,
        )
