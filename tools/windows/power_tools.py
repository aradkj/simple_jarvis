"""Windows Power Operations and Inspection Tools for JARVIS Phase 6."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult
from tools.windows.windows_service import WindowsControlService

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


class PowerStatusInput(BaseModel):
    """Empty schema for querying power status."""

    pass


class PowerActionInput(BaseModel):
    """Input parameters for disruptive power actions."""

    force: bool = Field(
        default=False,
        description="Whether to force execution if applications are hung (requires high-impact approval)",
    )
    confirmed: bool = Field(
        default=False,
        description="Explicit final confirmation acknowledging unsaved work loss",
    )


class WindowsPowerGetStatusTool(BaseTool):
    """Tool to inspect system AC line power status, battery level, and charging state."""

    name = "windows_power_get_status"
    description = "Inspect Windows AC power status (online/offline), battery percentage, charging state, and remaining life."
    category = PermissionCategory.WINDOWS_POWER_READ
    input_schema = PowerStatusInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Power status query cancelled by user")

        try:
            status = self.service.get_power_status()
            return ToolResult.success(data=status.model_dump())
        except Exception as exc:
            return ToolResult.failed(f"Failed to query power status: {exc}")

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


class WindowsPowerLockTool(BaseTool):
    """Tool to lock the Windows workstation session."""

    name = "windows_power_lock"
    description = "Lock the current Windows workstation session immediately."
    category = PermissionCategory.WINDOWS_POWER_CONTROL
    input_schema = PowerStatusInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Workstation lock cancelled by user")

        try:
            self.service.lock_workstation()
            return ToolResult.success(data={"status": "locked"})
        except Exception as exc:
            return ToolResult.failed(f"Failed to lock workstation: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.HIGH,
            parameters_schema={"type": "object", "properties": {}},
            requires_approval=True,
        )


class WindowsPowerSleepTool(BaseTool):
    """Tool to place the system into sleep or standby state."""

    name = "windows_power_sleep"
    description = "Place the Windows computer into low-power sleep state (requires user approval)."
    category = PermissionCategory.WINDOWS_POWER_CONTROL
    input_schema = PowerStatusInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Sleep transition cancelled by user")

        try:
            self.service.sleep(hibernate=False)
            return ToolResult.success(data={"status": "sleep_initiated"})
        except Exception as exc:
            return ToolResult.failed(f"Failed to initiate sleep: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.CRITICAL,
            parameters_schema={"type": "object", "properties": {}},
            requires_approval=True,
        )


class WindowsPowerRestartTool(BaseTool):
    """Tool to restart the computer with unsaved work warnings."""

    name = "windows_power_restart"
    description = "Restart the Windows computer. High-impact destructive operation requiring explicit confirmation (unsaved work may be lost)."
    category = PermissionCategory.WINDOWS_POWER_CONTROL
    input_schema = PowerActionInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Restart cancelled by user")

        if not getattr(params, "confirmed", False):
            return ToolResult.denied(
                "Restart denied: explicit confirmation acknowledging potential unsaved work loss is required."
            )

        force = getattr(params, "force", False)
        try:
            self.service.restart(force=force)
            return ToolResult.success(
                data={"status": "restart_initiated", "warning": "Unsaved work will be closed."}
            )
        except Exception as exc:
            return ToolResult.failed(f"Failed to initiate restart: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.CRITICAL,
            parameters_schema={
                "type": "object",
                "properties": {
                    "force": {
                        "type": "boolean",
                        "description": "Force restart even if apps are hung",
                        "default": False,
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": "Explicit confirmation acknowledging potential unsaved work loss",
                        "default": False,
                    },
                },
                "required": ["confirmed"],
            },
            requires_approval=True,
        )


class WindowsPowerShutdownTool(BaseTool):
    """Tool to shut down the computer with unsaved work warnings."""

    name = "windows_power_shutdown"
    description = "Shut down the Windows computer. High-impact destructive operation requiring explicit confirmation (unsaved work will be lost)."
    category = PermissionCategory.WINDOWS_POWER_CONTROL
    input_schema = PowerActionInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Shutdown cancelled by user")

        if not getattr(params, "confirmed", False):
            return ToolResult.denied(
                "Shutdown denied: explicit confirmation acknowledging potential unsaved work loss is required."
            )

        force = getattr(params, "force", False)
        try:
            self.service.shutdown(force=force)
            return ToolResult.success(
                data={"status": "shutdown_initiated", "warning": "Unsaved work will be closed."}
            )
        except Exception as exc:
            return ToolResult.failed(f"Failed to initiate shutdown: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.CRITICAL,
            parameters_schema={
                "type": "object",
                "properties": {
                    "force": {
                        "type": "boolean",
                        "description": "Force shutdown even if apps are hung",
                        "default": False,
                    },
                    "confirmed": {
                        "type": "boolean",
                        "description": "Explicit confirmation acknowledging potential unsaved work loss",
                        "default": False,
                    },
                },
                "required": ["confirmed"],
            },
            requires_approval=True,
        )
