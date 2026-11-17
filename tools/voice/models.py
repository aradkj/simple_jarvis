"""Data models and enums for JARVIS Phase 9 Voice Intelligence Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class VoiceState(StrEnum):
    """Current state of the voice intelligence subsystem."""

    IDLE = "idle"
    WAKE_DETECTED = "wake_detected"
    SESSION_ACTIVATING = "session_activating"
    LISTENING = "listening"
    RECORDING = "recording"
    TRANSCRIBING = "transcribing"
    UNDERSTANDING = "understanding"
    THINKING = "thinking"
    GENERATING_RESPONSE = "generating_response"
    SPEAKING = "speaking"
    INTERRUPTED = "interrupted"
    WAITING = "waiting"
    SESSION_STOPPING = "session_stopping"
    SESSION_ENDED = "session_ended"
    MUTED = "muted"
    ERROR = "error"
    ERROR_RECOVERY = "error_recovery"


@dataclass
class AudioDeviceInfo:
    """Information regarding a detected audio capture or playback device."""

    id: str
    name: str
    is_default: bool = False
    is_input: bool = True
    sample_rates: list[int] = field(default_factory=lambda: [16000, 44100, 48000])
    channels: int = 1


@dataclass
class VADResult:
    """Voice Activity Detection result for an audio segment."""

    is_speech: bool
    energy_rms: float
    speech_duration_ms: float = 0.0
    silence_duration_ms: float = 0.0
    noise_floor: float = 0.0


@dataclass
class TranscriptResult:
    """Structured result returned by Speech-to-Text engine."""

    text: str
    language: str = "en"
    confidence: float = 1.0
    is_final: bool = True
    duration_seconds: float = 0.0
    is_ambiguous: bool = False
    detected_wake_word: bool = False
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSRequest:
    """Request payload for speech synthesis."""

    text: str
    language: str = "en"
    voice_name: str | None = None
    rate: float = 1.0
    pitch: float = 0.0
    volume: float = 1.0


@dataclass
class VoiceEvent:
    """Event emitted across voice pipeline stages."""

    event_type: str
    state: VoiceState
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
