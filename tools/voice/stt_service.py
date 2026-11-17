"""Provider-independent Speech-to-Text (STT) interface and implementations.

Supports real Persian (fa-IR) and English (en-US) speech recognition via Gemini
multimodal ProviderManager integration, language selection, confidence scoring,
local/cloud privacy consent controls, and ambiguity detection.
"""

from __future__ import annotations

import io
import re
import wave
from abc import ABC, abstractmethod
from typing import Any

from ai.manager import ProviderManager
from config import get_settings
from core.execution_context import CancellationToken
from infrastructure.logging import get_logger
from tools.voice.models import TranscriptResult

logger = get_logger("voice.stt")


class BaseSTTService(ABC):
    """Abstract interface for Speech-to-Text transcription engines."""

    @abstractmethod
    def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: str = "auto",
        cancellation_token: CancellationToken | None = None,
    ) -> TranscriptResult:
        """Transcribe PCM audio bytes to structured text."""
        raise NotImplementedError


class SpeechRecognitionService(BaseSTTService):
    """Production STT service utilizing Gemini Multimodal AI Provider for real speech recognition.

    Supports:
    - Real Persian (fa-IR) and English (en-US) transcription.
    - Mixed technical Persian-English vocabulary (e.g. "پایتون", "کد", "واتساپ", "سیستم").
    - Accurate digit, phone number, name, and date transcription.
    - Privacy consent enforcement: Checks cloud transcription policy before sending audio.
    - Uncertainty and pronoun ambiguity analysis.
    - Timeouts and cancellation recovery.
    """

    def __init__(self, provider_manager: ProviderManager | None = None) -> None:
        self.settings = get_settings()
        self._provider_manager = provider_manager

    @property
    def provider_manager(self) -> ProviderManager:
        if self._provider_manager is None:
            self._provider_manager = ProviderManager()
        return self._provider_manager

    def detect_language(self, text: str) -> str:
        """Heuristically identify Persian vs English based on Unicode ranges."""
        persian_chars = len(re.findall(r"[\u0600-\u06FF\uFB8A\u067E\u0686\u06AF]", text))
        latin_chars = len(re.findall(r"[a-zA-Z]", text))
        if persian_chars > latin_chars:
            return "fa"
        return "en"

    def analyze_ambiguity(self, text: str, confidence: float) -> bool:
        """Check whether the recognized transcript is ambiguous or uncertain."""
        if confidence < 0.65:
            return True

        text_lower = text.strip().lower()

        # Pronoun without clear reference or missing parameters
        ambiguous_patterns = [
            r"^(بهش|به اون|برای اون)\s+(پیام|ایمیل)\s+(بده|بزن)[.،!]?$",
            r"^send (him|her|them) (?:a|an) (message|email)[.!]?$",
            r"^(ایمیل|پیام)\s+(بفرست|بزن)[.،!]?$",  # Missing recipient and content
            r"^send (?:an email|a message)[.!]?$",
        ]
        return any(re.match(pat, text_lower) for pat in ambiguous_patterns)

    def has_cloud_consent(self) -> bool:
        """Check whether the user has granted explicit consent for cloud transcription.

        Returns False if settings are missing, corrupted, non-boolean, or False.
        Local microphone capture does not imply cloud consent.
        """
        try:
            if not self.settings:
                return False
            val = getattr(self.settings, "voice_cloud_stt_consent", False)
            if not isinstance(val, bool):
                return False
            return val is True
        except Exception:
            return False

    def pcm_to_wav(self, pcm_data: bytes, sample_rate: int = 16000) -> bytes:
        """Wrap raw 16-bit mono PCM bytes into canonical WAV container format."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_data)
        return buf.getvalue()

    def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: str = "auto",
        cancellation_token: CancellationToken | None = None,
    ) -> TranscriptResult:
        if cancellation_token and cancellation_token.is_cancelled():
            return TranscriptResult(text="", confidence=0.0, is_final=True)

        if not audio_data or len(audio_data) < 320:  # < 10ms of audio
            return TranscriptResult(text="", confidence=0.0, is_final=True)

        duration = len(audio_data) / max(sample_rate * 2, 1)

        # 1. Privacy & Cloud Consent Enforcement
        if not self.has_cloud_consent():
            logger.warning(
                "Cloud transcription requested but user cloud consent is disabled or unverified."
            )
            return TranscriptResult(
                text="",
                language=language if language != "auto" else "en",
                confidence=0.0,
                is_final=True,
                duration_seconds=duration,
                error="Cloud transcription blocked by local privacy policy. Consent not granted.",
            )

        # 2. Real Multimodal Transcription via ProviderManager boundary
        try:
            wav_bytes = self.pcm_to_wav(audio_data, sample_rate)

            transcription_result = self.provider_manager.transcribe_audio(
                audio_data=wav_bytes,
                mime_type="audio/wav",
                language=language,
                cancellation_token=cancellation_token,
            )

            text = transcription_result.text
            detected_lang = transcription_result.language or self.detect_language(text)
            conf = transcription_result.confidence
            is_ambiguous = transcription_result.is_ambiguous or self.analyze_ambiguity(text, conf)

            logger.info(
                f"STT transcribed ({duration:.2f}s): '{text}' "
                f"[lang={detected_lang}, conf={conf:.2f}, ambiguous={is_ambiguous}]"
            )

            return TranscriptResult(
                text=text,
                language=detected_lang,
                confidence=conf,
                is_final=True,
                duration_seconds=duration,
                is_ambiguous=is_ambiguous,
            )

        except Exception as exc:
            logger.warning(f"Live STT failed or unavailable: {exc}. Graceful error return.")
            lang = language if language != "auto" else "en"
            return TranscriptResult(
                text="",
                language=lang,
                confidence=0.0,
                is_final=True,
                duration_seconds=duration,
                is_ambiguous=False,
                error=f"Live STT provider error: {exc}",
            )


class MockSTTService(BaseSTTService):
    """Deterministic Mock STT engine for automated testing."""

    def __init__(self, preset_transcript: str = "سلام جارویس", confidence: float = 0.95) -> None:
        self.preset_transcript = preset_transcript
        self.confidence = confidence
        self.invocations: list[dict[str, Any]] = []

    def set_transcript(self, text: str, confidence: float = 0.95) -> None:
        self.preset_transcript = text
        self.confidence = confidence

    def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: str = "auto",
        cancellation_token: CancellationToken | None = None,
    ) -> TranscriptResult:
        self.invocations.append(
            {"bytes_len": len(audio_data), "sample_rate": sample_rate, "language": language}
        )
        if cancellation_token and cancellation_token.is_cancelled():
            return TranscriptResult(text="", confidence=0.0, is_final=True)

        lang = "fa" if any("\u0600" <= c <= "\u06ff" for c in self.preset_transcript) else "en"
        ambiguous = self.confidence < 0.65 or self.preset_transcript.strip().lower() in (
            "بهش پیام بده",
            "send him a message",
            "ایمیل بفرست",
        )
        return TranscriptResult(
            text=self.preset_transcript,
            language=lang,
            confidence=self.confidence,
            is_final=True,
            duration_seconds=len(audio_data) / max(sample_rate * 2, 1),
            is_ambiguous=ambiguous,
        )
