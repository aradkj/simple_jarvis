"""Windows Audio Management Tools for JARVIS Phase 6."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult
from tools.windows.windows_service import WindowsControlService

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


class AudioStatusInput(BaseModel):
    """Empty schema for querying audio endpoint status."""

    pass


class AudioVolumeInput(BaseModel):
    """Input parameters for setting master output volume."""

    percent: float = Field(
        ge=0.0,
        le=100.0,
        description="Master output volume percentage between 0.0 and 100.0",
    )


class AudioMuteInput(BaseModel):
    """Input parameters for muting or unmuting audio."""

    mute: bool = Field(description="True to mute master output, False to unmute")


class WindowsAudioGetStatusTool(BaseTool):
    """Tool to read current master audio volume percentage and mute state."""

    name = "windows_audio_get_status"
    description = "Read current Windows master audio output volume percentage (0-100) and mute state via Core Audio APIs."
    category = PermissionCategory.WINDOWS_AUDIO_READ
    input_schema = AudioStatusInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Audio status query cancelled by user")

        try:
            status = self.service.get_audio_status()
            return ToolResult.success(data=status.model_dump())
        except Exception as exc:
            return ToolResult.failed(f"Failed to query audio status: {exc}")

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


class WindowsAudioSetVolumeTool(BaseTool):
    """Tool to adjust master output volume percentage."""

    name = "windows_audio_set_volume"
    description = "Set Windows master audio output volume percentage (0.0 to 100.0) and report resulting state."
    category = PermissionCategory.WINDOWS_AUDIO_CONTROL
    input_schema = AudioVolumeInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Volume adjustment cancelled by user")

        percent = getattr(params, "percent", 50.0)
        try:
            status = self.service.set_volume(percent)
            if not getattr(status, "verified", True) or not getattr(status, "success", True):
                return ToolResult.failed(
                    getattr(status, "error_message", None) or f"Failed to verify volume {percent}%",
                    data=status.model_dump(),
                )
            return ToolResult.success(data=status.model_dump())
        except Exception as exc:
            return ToolResult.failed(f"Failed to set volume to {percent}%: {exc}")

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
                        "type": "number",
                        "description": "Desired volume level from 0.0 to 100.0",
                        "minimum": 0.0,
                        "maximum": 100.0,
                    }
                },
                "required": ["percent"],
            },
            requires_approval=False,
        )


class WindowsAudioSetMuteTool(BaseTool):
    """Tool to mute or unmute master output audio."""

    name = "windows_audio_set_mute"
    description = "Mute or unmute Windows master audio output and report resulting state."
    category = PermissionCategory.WINDOWS_AUDIO_CONTROL
    input_schema = AudioMuteInput

    def __init__(self, service: WindowsControlService | None = None) -> None:
        super().__init__()
        self.service = service or WindowsControlService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Mute change cancelled by user")

        mute = getattr(params, "mute", True)
        try:
            status = self.service.set_mute(mute)
            if not getattr(status, "verified", True) or not getattr(status, "success", True):
                return ToolResult.failed(
                    getattr(status, "error_message", None) or f"Failed to verify mute state {mute}",
                    data=status.model_dump(),
                )
            return ToolResult.success(data=status.model_dump())
        except Exception as exc:
            return ToolResult.failed(f"Failed to set mute state to {mute}: {exc}")

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
                    "mute": {
                        "type": "boolean",
                        "description": "True to mute, False to unmute",
                    }
                },
                "required": ["mute"],
            },
            requires_approval=False,
        )
