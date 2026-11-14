"""JARVIS Phase 9 Voice Intelligence Subsystem."""

from tools.voice.device_manager import AudioDeviceManager
from tools.voice.elevenlabs_provider import (
    ElevenLabsTTSProvider,
    ElevenLabsTTSService,
    ElevenLabsVoiceMetadata,
    SentenceStreamingBuffer,
)
from tools.voice.models import (
    AudioDeviceInfo,
    TranscriptResult,
    TTSRequest,
    VADResult,
    VoiceState,
)
from tools.voice.stt_service import (
    BaseSTTService,
    MockSTTService,
    SpeechRecognitionService,
)
from tools.voice.tts_service import (
    BaseTTSService,
    MockTTSService,
    WindowsTTSService,
)
from tools.voice.vad import VoiceActivityDetector
from tools.voice.voice_pipeline import ConversationalVoicePipeline
from tools.voice.voice_tools import (
    VoiceMuteInput,
    VoiceMuteTool,
    VoiceSpeakInput,
    VoiceSpeakTool,
    VoiceStatusInput,
    VoiceStatusTool,
)
from tools.voice.wake_word import WakeWordDetector

__all__ = [
    "AudioDeviceInfo",
    "AudioDeviceManager",
    "BaseSTTService",
    "BaseTTSService",
    "ConversationalVoicePipeline",
    "ElevenLabsTTSProvider",
    "ElevenLabsTTSService",
    "ElevenLabsVoiceMetadata",
    "MockSTTService",
    "MockTTSService",
    "SentenceStreamingBuffer",
    "SpeechRecognitionService",
    "TTSRequest",
    "TranscriptResult",
    "VADResult",
    "VoiceActivityDetector",
    "VoiceMuteInput",
    "VoiceMuteTool",
    "VoiceSpeakInput",
    "VoiceSpeakTool",
    "VoiceState",
    "VoiceStatusInput",
    "VoiceStatusTool",
    "WakeWordDetector",
    "WindowsTTSService",
]
