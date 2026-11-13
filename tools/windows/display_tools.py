"""Windows Display Brightness Management Tools for JARVIS Phase 6."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult
from tools.windows.windows_service import WindowsControlService

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


class BrightnessStatusInput(BaseModel):
    """Empty schema for querying brightness status."""

    pass


class BrightnessSetInput(BaseModel):
    """Input parameters for setting monitor brightness."""

    percent: int = Field(
        ge=0,
        le=100,
        description="Monitor brightness percentage between 0 and 100",
    )


class WindowsDisplayGetBrightnessTool(BaseTool):
    """Tool to read physical monitor brightness where supported."""

    name = "windows_display_get_brightness"
    description = "Read current physical display monitor brightness level (0-100%) and supported hardware range via DXVA2 API."
    category = PermissionCategory.WINDOWS_DISPLAY_READ
    input_schema = BrightnessStatusInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Brightness query cancelled by user")

        try:
            status = self.service.get_brightness()
            return ToolResult.success(data=status.model_dump())
        except Exception as exc:
            return ToolResult.failed(f"Failed to query display brightness: {exc}")

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


class WindowsDisplaySetBrightnessTool(BaseTool):
    """Tool to set physical monitor brightness percentage where supported."""

    name = "windows_display_set_brightness"
    description = "Set physical display monitor brightness percentage (0 to 100) where supported by monitor hardware."
    category = PermissionCategory.WINDOWS_DISPLAY_CONTROL
    input_schema = BrightnessSetInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Brightness change cancelled by user")

        percent = getattr(params, "percent", 50)
        try:
            status = self.service.set_brightness(percent)
            return ToolResult.success(data=status.model_dump())
        except Exception as exc:
            return ToolResult.failed(f"Failed to set brightness to {percent}%: {exc}")

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
                    "percent": {
                        "type": "integer",
                        "description": "Desired brightness level from 0 to 100",
                        "minimum": 0,
                        "maximum": 100,
                    }
                },
                "required": ["percent"],
            },
            requires_approval=False,
        )
