"""Voice tools registered with Agent Core for inspecting and controlling voice subsystem."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext
    from tools.voice.voice_pipeline import ConversationalVoicePipeline


class VoiceStatusInput(BaseModel):
    pass


class VoiceSpeakInput(BaseModel):
    text: str = Field(description="The natural language text to synthesize into spoken audio")
    rate: float | None = Field(default=None, description="Speech rate multiplier (default 1.0)")


class VoiceMuteInput(BaseModel):
    mute: bool = Field(description="True to mute listening, False to unmute")


class VoiceStatusTool(BaseTool):
    """Tool to inspect active voice intelligence hardware, VAD, and wake-word status."""

    name = "voice_status"
    description = "Check voice subsystem status, active microphone, speaker, and listening state."
    category = PermissionCategory.VOICE_CONTROL
    input_schema = VoiceStatusInput

    def __init__(self, pipeline: ConversationalVoicePipeline | None = None) -> None:
        self.pipeline = pipeline

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if self.pipeline is None:
            return ToolResult.success(
                data={"enabled": False, "state": "not_initialized"},
                message="Voice pipeline not initialized.",
            )

        mic = self.pipeline.device_manager.get_selected_input()
        spk = self.pipeline.device_manager.get_selected_output()
        data: dict[str, Any] = {
            "state": self.pipeline.state.value,
            "microphone": {"name": mic.name, "id": mic.id, "default": mic.is_default},
            "speaker": {"name": spk.name, "id": spk.id, "default": spk.is_default},
            "wake_word": self.pipeline.wake_word_detector.get_status(),
            "vad_energy_threshold": self.pipeline.vad.energy_threshold,
            "noise_floor": round(self.pipeline.vad.noise_floor, 4),
            "available_voices": self.pipeline.tts_service.get_available_voices(),
        }
        return ToolResult.success(data=data, message="Voice status retrieved.")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={"type": "object", "properties": {}},
            requires_approval=False,
            timeout_seconds=5.0,
        )


class VoiceSpeakTool(BaseTool):
    """Tool to speak a natural language response through system speakers."""

    name = "voice_speak"
    description = "Synthesize and speak text through the configured audio output device."
    category = PermissionCategory.VOICE_CONTROL
    input_schema = VoiceSpeakInput

    def __init__(self, pipeline: ConversationalVoicePipeline | None = None) -> None:
        self.pipeline = pipeline

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        p = (
            params
            if isinstance(params, VoiceSpeakInput)
            else VoiceSpeakInput.model_validate(
                params if isinstance(params, dict) else params.model_dump()
            )
        )
        if not self.pipeline:
            return ToolResult.failed("Voice pipeline not initialized.")

        ok = self.pipeline.speak(p.text, rate=p.rate)
        return ToolResult.success(
            data={"spoken": ok, "character_count": len(p.text)},
            message=f"Spoke {len(p.text)} characters.",
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
                    "text": {"type": "string", "description": "Text to speak"},
                    "rate": {"type": "number", "description": "Speech rate"},
                },
                "required": ["text"],
            },
            requires_approval=False,
            timeout_seconds=30.0,
        )


class VoiceMuteTool(BaseTool):
    """Tool to mute or unmute microphone listening."""

    name = "voice_mute"
    description = "Mute or unmute voice capture and wake-word listening."
    category = PermissionCategory.VOICE_CONTROL
    input_schema = VoiceMuteInput

    def __init__(self, pipeline: ConversationalVoicePipeline | None = None) -> None:
        self.pipeline = pipeline

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        p = (
            params
            if isinstance(params, VoiceMuteInput)
            else VoiceMuteInput.model_validate(
                params if isinstance(params, dict) else params.model_dump()
            )
        )
        if not self.pipeline:
            return ToolResult.failed("Voice pipeline not initialized.")

        if p.mute:
            self.pipeline.mute()
            msg = "Voice listening muted."
        else:
            self.pipeline.unmute()
            msg = "Voice listening unmuted."

        return ToolResult.success(
            data={"muted": self.pipeline.wake_word_detector.is_muted},
            message=msg,
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
                    "mute": {"type": "boolean", "description": "True to mute, False to unmute"},
                },
                "required": ["mute"],
            },
            requires_approval=False,
            timeout_seconds=5.0,
        )
