"""Voice Activity Detection (VAD) and Energy Tracking for JARVIS.

Processes raw PCM audio frames, computes RMS energy levels, adapts to background
noise floor, and detects transitions between silence and active speech.
"""

from __future__ import annotations

import math
import struct

from tools.voice.models import VADResult


class VoiceActivityDetector:
    """Energy-based Voice Activity Detector with adaptive noise tracking."""

    def __init__(
        self,
        energy_threshold: float = 0.015,
        silence_timeout_seconds: float = 1.8,
        sample_rate: int = 16000,
        sample_width_bytes: int = 2,
    ) -> None:
        self.energy_threshold = energy_threshold
        self.silence_timeout_seconds = silence_timeout_seconds
        self.sample_rate = sample_rate
        self.sample_width_bytes = sample_width_bytes

        self.noise_floor: float = 0.005
        self._noise_adaptation_rate: float = 0.05
        self.continuous_speech_seconds: float = 0.0
        self.continuous_silence_seconds: float = 0.0
        self.is_speech_active: bool = False
        self.speech_detected_in_utterance: bool = False

    def reset(self) -> None:
        """Reset state tracking for a new utterance."""
        self.continuous_speech_seconds = 0.0
        self.continuous_silence_seconds = 0.0
        self.is_speech_active = False
        self.speech_detected_in_utterance = False

    def compute_rms(self, pcm_data: bytes) -> float:
        """Calculate Root Mean Square (RMS) normalized energy of 16-bit PCM bytes."""
        if not pcm_data:
            return 0.0

        num_samples = len(pcm_data) // self.sample_width_bytes
        if num_samples == 0:
            return 0.0

        fmt = f"<{num_samples}h"
        try:
            samples = struct.unpack(fmt, pcm_data[: num_samples * 2])
        except Exception:
            return 0.0

        sum_squares = sum(s * s for s in samples)
        mean_square = sum_squares / num_samples
        # Normalize to 0.0 - 1.0 (32768 is max for 16-bit signed integer)
        rms = math.sqrt(mean_square) / 32768.0
        return rms

    def process_frame(
        self, pcm_data: bytes, frame_duration_seconds: float | None = None
    ) -> VADResult:
        """Process an incoming audio frame and return speech detection status."""
        rms = self.compute_rms(pcm_data)

        if frame_duration_seconds is None:
            bytes_per_second = self.sample_rate * self.sample_width_bytes
            frame_duration_seconds = (
                len(pcm_data) / bytes_per_second if bytes_per_second > 0 else 0.02
            )

        # Effective threshold adapts to background ambient noise
        effective_threshold = max(self.energy_threshold, self.noise_floor * 1.8)

        is_frame_speech = rms > effective_threshold

        if is_frame_speech:
            self.continuous_speech_seconds += frame_duration_seconds
            self.continuous_silence_seconds = 0.0
            if self.continuous_speech_seconds >= 0.1:  # Debounce transient clicks
                self.is_speech_active = True
                self.speech_detected_in_utterance = True
        else:
            self.continuous_silence_seconds += frame_duration_seconds
            # Slowly adapt noise floor during confirmed silence
            if not self.is_speech_active:
                self.noise_floor = (
                    1.0 - self._noise_adaptation_rate
                ) * self.noise_floor + self._noise_adaptation_rate * rms

            if self.continuous_silence_seconds >= self.silence_timeout_seconds:
                self.is_speech_active = False
                self.continuous_speech_seconds = 0.0

        return VADResult(
            is_speech=self.is_speech_active,
            energy_rms=rms,
            speech_duration_ms=self.continuous_speech_seconds * 1000.0,
            silence_duration_ms=self.continuous_silence_seconds * 1000.0,
            noise_floor=self.noise_floor,
        )

    def is_silence_timeout_reached(self) -> bool:
        """Return True if user was speaking and has now been silent past timeout."""
        return (self.is_speech_active or self.speech_detected_in_utterance) and (
            self.continuous_silence_seconds >= self.silence_timeout_seconds
        )
