"""Coordinated Conversational Audio Pipeline for JARVIS Phase 9.

Orchestrates Audio Capture -> Wake Word / PTT -> VAD -> STT -> Transcript Validation ->
Agent Request -> Response Generation -> TTS with real-time Barge-In support.
"""

from __future__ import annotations

import collections
import contextlib
import io
import math
import struct
import threading
import time
import wave
from collections.abc import Callable
from typing import Any

from config import get_settings
from core.events import AgentEvent, AgentEventType, EventBus
from core.execution_context import CancellationToken
from infrastructure.logging import get_logger
from tools.voice.device_manager import AudioDeviceManager
from tools.voice.models import (
    TranscriptResult,
    TTSRequest,
    VoiceState,
)
from tools.voice.stt_service import BaseSTTService, SpeechRecognitionService
from tools.voice.tts_service import BaseTTSService, create_tts_service
from tools.voice.vad import VoiceActivityDetector
from tools.voice.wake_word import WakeWordDetector

logger = get_logger("voice.pipeline")

# 17-tap Hamming-windowed sinc FIR filter coefficients for anti-aliased decimation to 16kHz
# Cutoff frequency fc = 7200 Hz ensures > 40dB attenuation above 10kHz to prevent aliasing.
_FIR_COEFFS_48K: tuple[float, ...] = (
    0.003012434769548987,
    0.0016082431159205482,
    -0.0066630529753613785,
    -0.02305694084783898,
    -0.025134125532388606,
    0.023361800448291923,
    0.13032833900671775,
    0.24728020177948948,
    0.29852620047124057,
    0.2472802017794895,
    0.13032833900671778,
    0.023361800448291933,
    -0.025134125532388613,
    -0.023056940847838978,
    -0.00666305297536138,
    0.0016082431159205497,
    0.003012434769548987,
)

_FIR_COEFFS_32K: tuple[float, ...] = (
    -0.003038334698186257,
    -0.0023830549879629913,
    0.009249754096970141,
    0.016443893271111752,
    -0.025350220521143014,
    -0.06793956966928974,
    0.04271032347579118,
    0.30448758572217494,
    0.45163924662106797,
    0.304487585722175,
    0.042710323475791186,
    -0.06793956966928978,
    -0.02535022052114302,
    0.016443893271111752,
    0.009249754096970143,
    -0.002383054987962994,
    -0.003038334698186257,
)

_FIR_COEFFS_44K: tuple[float, ...] = (
    0.0029748330368738972,
    0.004072059333005319,
    -0.0014507052245013034,
    -0.021099662276410643,
    -0.03509795186633945,
    0.0048474324625100975,
    0.12158822764872372,
    0.2615784322117702,
    0.32517466934873623,
    0.26157843221177024,
    0.12158822764872373,
    0.0048474324625101,
    -0.035097951866339454,
    -0.02109966227641064,
    -0.0014507052245013039,
    0.004072059333005323,
    0.0029748330368738972,
)


def _soft_limit_pcm16(s: float) -> int:
    """Apply hyperbolic soft limiting to prevent harsh digital clipping."""
    if s > 0.95:
        s = 0.95 + 0.05 * math.tanh((s - 0.95) / 0.05)
    elif s < -0.95:
        s = -0.95 + 0.05 * math.tanh((s + 0.95) / 0.05)
    return max(-32768, min(32767, int(s * 32767.0)))


def pcm16_to_wav(pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
    """Package raw 16-bit PCM frames into canonical RIFF WAV format."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)
    return buf.getvalue()


def normalize_audio_to_16k_mono_pcm16(
    raw_bytes: bytes,
    src_rate: int = 16000,
    channels: int = 1,
    is_float: bool = False,
) -> bytes:
    """Normalize hardware audio capture (e.g. 48kHz Stereo Float from AirPods / Realtek)
    to canonical 16000Hz Mono 16-bit signed PCM audio with anti-alias filtering and duration preservation.
    """
    if not raw_bytes:
        return b""

    # Fast path: already 16kHz Mono Int16
    if src_rate == 16000 and channels == 1 and not is_float:
        sample_count = len(raw_bytes) // 2
        if sample_count == 0:
            return b""
        return raw_bytes[: sample_count * 2]

    samples: list[float] = []

    if is_float:
        count = len(raw_bytes) // 4
        if count == 0:
            return b""
        floats = struct.unpack(f"<{count}f", raw_bytes[: count * 4])
        if channels == 1:
            samples = list(floats)
        elif channels == 2:
            # Downmix Stereo L + R
            samples = [(floats[i] + floats[i + 1]) * 0.5 for i in range(0, count - 1, 2)]
        else:
            samples = [
                sum(floats[i : i + channels]) / channels
                for i in range(0, count - channels + 1, channels)
            ]
    else:
        # Int16
        count = len(raw_bytes) // 2
        if count == 0:
            return b""
        ints = struct.unpack(f"<{count}h", raw_bytes[: count * 2])
        if channels == 1:
            samples = [v / 32768.0 for v in ints]
        elif channels == 2:
            samples = [(ints[i] + ints[i + 1]) / 65536.0 for i in range(0, count - 1, 2)]
        else:
            samples = [
                sum(ints[i : i + channels]) / (32768.0 * channels)
                for i in range(0, count - channels + 1, channels)
            ]

    if not samples:
        return b""

    # Downsample / Resample to 16000 Hz if needed
    if src_rate != 16000 and len(samples) > 1:
        target_len = round(len(samples) * 16000.0 / src_rate)
        if target_len <= 0:
            return b""

        if src_rate == 48000:
            padded = [samples[0]] * 8 + samples + [samples[-1]] * 8
            c0, c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12, c13, c14, c15, c16 = (
                _FIR_COEFFS_48K
            )
            samples = [
                (
                    padded[c] * c0
                    + padded[c + 1] * c1
                    + padded[c + 2] * c2
                    + padded[c + 3] * c3
                    + padded[c + 4] * c4
                    + padded[c + 5] * c5
                    + padded[c + 6] * c6
                    + padded[c + 7] * c7
                    + padded[c + 8] * c8
                    + padded[c + 9] * c9
                    + padded[c + 10] * c10
                    + padded[c + 11] * c11
                    + padded[c + 12] * c12
                    + padded[c + 13] * c13
                    + padded[c + 14] * c14
                    + padded[c + 15] * c15
                    + padded[c + 16] * c16
                )
                for c in range(0, target_len * 3, 3)
            ]
        elif src_rate == 32000:
            padded = [samples[0]] * 8 + samples + [samples[-1]] * 8
            c0, c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12, c13, c14, c15, c16 = (
                _FIR_COEFFS_32K
            )
            samples = [
                (
                    padded[c] * c0
                    + padded[c + 1] * c1
                    + padded[c + 2] * c2
                    + padded[c + 3] * c3
                    + padded[c + 4] * c4
                    + padded[c + 5] * c5
                    + padded[c + 6] * c6
                    + padded[c + 7] * c7
                    + padded[c + 8] * c8
                    + padded[c + 9] * c9
                    + padded[c + 10] * c10
                    + padded[c + 11] * c11
                    + padded[c + 12] * c12
                    + padded[c + 13] * c13
                    + padded[c + 14] * c14
                    + padded[c + 15] * c15
                    + padded[c + 16] * c16
                )
                for c in range(0, target_len * 2, 2)
            ]
        elif src_rate == 44100:
            padded = [samples[0]] * 8 + samples + [samples[-1]] * 8
            c0, c1, c2, c3, c4, c5, c6, c7, c8, c9, c10, c11, c12, c13, c14, c15, c16 = (
                _FIR_COEFFS_44K
            )
            filtered = [
                (
                    padded[i] * c0
                    + padded[i + 1] * c1
                    + padded[i + 2] * c2
                    + padded[i + 3] * c3
                    + padded[i + 4] * c4
                    + padded[i + 5] * c5
                    + padded[i + 6] * c6
                    + padded[i + 7] * c7
                    + padded[i + 8] * c8
                    + padded[i + 9] * c9
                    + padded[i + 10] * c10
                    + padded[i + 11] * c11
                    + padded[i + 12] * c12
                    + padded[i + 13] * c13
                    + padded[i + 14] * c14
                    + padded[i + 15] * c15
                    + padded[i + 16] * c16
                )
                for i in range(len(samples))
            ]
            ratio = src_rate / 16000.0
            samples = []
            for k in range(target_len):
                pos = k * ratio
                i0 = int(pos)
                i1 = min(i0 + 1, len(filtered) - 1)
                frac = pos - i0
                samples.append(filtered[i0] * (1.0 - frac) + filtered[i1] * frac)
        else:
            ratio = src_rate / 16000.0
            resampled = []
            for i in range(target_len):
                src_idx = i * ratio
                idx0 = int(src_idx)
                idx1 = min(idx0 + 1, len(samples) - 1)
                frac = src_idx - idx0
                resampled.append(samples[idx0] * (1.0 - frac) + samples[idx1] * frac)
            samples = resampled

    # Pack to 16-bit signed PCM with soft limiting to prevent harsh digital clipping
    out_ints = [_soft_limit_pcm16(s) for s in samples]
    return struct.pack(f"<{len(out_ints)}h", *out_ints)


def clean_text_for_speech(text: str) -> str:
    """Prepare assistant response for natural speech synthesis in Persian or English.

    Strips markdown code blocks, links, headers, emojis, and bullet formatting while preserving full verbal content.
    """
    if not text:
        return ""
    import re

    # Remove code blocks
    cleaned = re.sub(r"```[\s\S]*?```", "", text)
    # Remove markdown link markup: [text](url) -> text
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    # Remove URLs
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    # Remove inline code backticks
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    # Remove divider lines
    cleaned = re.sub(r"^[-=]{3,}\s*$", "", cleaned, flags=re.MULTILINE)
    # Remove markdown headers and list markers at line start
    cleaned = re.sub(r"^[\s*#-]+", "", cleaned, flags=re.MULTILINE)
    # Remove markdown bold/italic/strikethrough formatting
    cleaned = re.sub(r"[*_~>#]+", "", cleaned)
    # Remove table vertical pipes
    cleaned = re.sub(r"[|]", " ", cleaned)
    # Remove 4-byte unicode emojis that trip speech synthesis engines
    cleaned = re.sub(r"[\U00010000-\U0010ffff]", "", cleaned)
    # Collapse multiple whitespaces / newlines
    cleaned = re.sub(r"\n\s*\n+", "\n", cleaned)
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()
    return cleaned


class ConversationalVoicePipeline:
    """End-to-end voice intelligence coordinator with barge-in support."""

    def __init__(
        self,
        device_manager: AudioDeviceManager | None = None,
        vad: VoiceActivityDetector | None = None,
        wake_word_detector: WakeWordDetector | None = None,
        stt_service: BaseSTTService | None = None,
        tts_service: BaseTTSService | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.settings = get_settings()
        self.device_manager = device_manager or AudioDeviceManager()
        self.vad = vad or VoiceActivityDetector(
            energy_threshold=getattr(self.settings, "voice_vad_energy_threshold", 0.015),
            silence_timeout_seconds=getattr(self.settings, "voice_silence_timeout_seconds", 0.8),
        )
        self.wake_word_detector = wake_word_detector or WakeWordDetector(
            wake_word=getattr(self.settings, "voice_wake_word", "Jarvis"),
            enabled=getattr(self.settings, "voice_wake_word_enabled", False),
        )
        self.stt_service = stt_service or SpeechRecognitionService()
        self.tts_service = tts_service or create_tts_service()
        self.event_bus = event_bus

        self._state: VoiceState = VoiceState.IDLE
        self._lock = threading.RLock()
        self._active_buffer: bytearray = bytearray()
        self._pre_roll_buffer: collections.deque[bytes] = collections.deque(maxlen=10)
        self._is_recording = False
        self._is_conversation_mode = False
        self._acoustic_wake_confirmed = False
        self._is_ptt_triggered = False
        self._barge_in_consecutive_frames: int = 0
        self._is_wake_acknowledging: bool = False
        self._on_command_callback: Callable[[str, TranscriptResult], None] | None = None
        self._cancellation_token = CancellationToken()
        self._current_mic_level: float = 0.0
        self._mic_level_callback: Callable[[float], None] | None = None
        self._audio_source: Any = None
        self._audio_io: Any = None
        self._audio_timer: Any = None
        self._active_input_device_name: str = ""
        self._capture_sample_rate: int = 16000
        self._capture_channels: int = 1
        self._capture_is_float: bool = False
        self._speech_queue: collections.deque[tuple[str, str | None, float | None]] = (
            collections.deque()
        )
        self._last_utterance_end_time: float = 0.0
        self._latency_history: list[dict[str, float]] = []

    @property
    def is_conversation_mode(self) -> bool:
        with self._lock:
            return self._is_conversation_mode

    @is_conversation_mode.setter
    def is_conversation_mode(self, value: bool) -> None:
        with self._lock:
            self._is_conversation_mode = bool(value)

    def start_conversation_mode(self) -> bool:
        """Enter continuous multi-turn persistent conversational mode."""
        with self._lock:
            self.set_state(VoiceState.SESSION_ACTIVATING, {"mode": "activating"})
            self._is_conversation_mode = True
            self._acoustic_wake_confirmed = False
            self._speech_queue.clear()
            self._active_buffer.clear()
            self._pre_roll_buffer.clear()
            self.vad.reset()
            self.start_audio_capture()
            logger.info(
                "Persistent conversational session activated: Multi-turn interaction ready."
            )
            self.set_state(VoiceState.LISTENING, {"mode": "conversation_active"})
            return True

    def stop_conversation_mode(self) -> bool:
        """Exit continuous conversational mode and return to idle standby."""
        with self._lock:
            self.set_state(VoiceState.SESSION_STOPPING, {"mode": "stopping"})
            self._is_conversation_mode = False
            self._is_recording = False
            self._acoustic_wake_confirmed = False
            self._speech_queue.clear()
            self._cancellation_token.cancel()
            self._cancellation_token = CancellationToken()
            if self.tts_service.is_speaking():
                self.tts_service.stop()
            self._active_buffer.clear()
            self._pre_roll_buffer.clear()
            self.vad.reset()
            logger.info("Conversational mode stopped: Returning to idle standby.")
            if (
                not getattr(self.settings, "voice_continuous_listening", False)
                and not self.wake_word_detector.enabled
            ):
                self.stop_audio_capture()
            self.set_state(VoiceState.SESSION_ENDED, {"mode": "ended"})
            self.set_state(VoiceState.IDLE, {"mode": "standby"})
            return True

    def toggle_conversation_mode(self) -> bool:
        """Toggle conversational mode on or off."""
        with self._lock:
            if self._is_conversation_mode:
                self.stop_conversation_mode()
                return False
            else:
                self.start_conversation_mode()
                return True

    def set_mic_level_callback(self, callback: Callable[[float], None] | None) -> None:
        """Register a callback for real-time microphone RMS level updates (0.0 to 1.0)."""
        self._mic_level_callback = callback

    def get_current_mic_level(self) -> float:
        """Get the current smoothed microphone input RMS level (0.0 to 1.0)."""
        with self._lock:
            return self._current_mic_level

    def get_active_input_device_name(self) -> str:
        """Return the friendly name of the active audio input device."""
        with self._lock:
            return self._active_input_device_name or "Default System Microphone"

    def restart_audio_capture(self, input_device_id: str | None = None) -> bool:
        """Hot-swap microphone input device and restart capture stream."""
        with self._lock:
            logger.info(f"Restarting audio capture with device target: {input_device_id}")
            self.stop_audio_capture()
            time.sleep(0.05)
            return self.start_audio_capture(input_device_id=input_device_id)

    @property
    def state(self) -> VoiceState:
        with self._lock:
            return self._state

    def set_state(self, new_state: VoiceState, extra: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._state = new_state
            logger.debug(f"Voice pipeline state changed to: {new_state.value}")
            if self.event_bus:
                evt_type = AgentEventType.AGENT_STATUS_CHANGED
                if new_state == VoiceState.LISTENING:
                    evt_type = AgentEventType.VOICE_LISTENING_STARTED
                elif new_state == VoiceState.WAKE_DETECTED:
                    evt_type = AgentEventType.VOICE_WAKE_WORD_DETECTED
                elif new_state == VoiceState.SPEAKING:
                    evt_type = AgentEventType.VOICE_TTS_STARTED
                elif new_state == VoiceState.IDLE:
                    evt_type = AgentEventType.VOICE_LISTENING_STOPPED

                payload = {"state": new_state.value}
                if extra:
                    payload.update(extra)
                self.event_bus.publish(AgentEvent(event_type=evt_type, payload=payload))

    def set_command_callback(self, callback: Callable[[str, TranscriptResult], None]) -> None:
        """Register the agent handler invoked when a validated spoken command is ready."""
        self._on_command_callback = callback

    def start_audio_capture(self, input_device_id: str | None = None) -> bool:
        """Start hardware microphone capture stream using QtMultimedia."""
        with self._lock:
            try:
                from PySide6.QtCore import QTimer
                from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
                from PySide6.QtWidgets import QApplication

                if not QApplication.instance():
                    return False

                if self._audio_source is not None:
                    return True

                target_device = None
                dev_id = input_device_id or getattr(self.settings, "voice_input_device", "")
                if dev_id:
                    for d in QMediaDevices.audioInputs():
                        name = d.description()
                        dev_bytes = d.id().data().decode("utf-8", "ignore")
                        if dev_id.lower() in dev_bytes.lower() or dev_id.lower() in name.lower():
                            target_device = d
                            break

                if target_device is None:
                    target_device = QMediaDevices.defaultAudioInput()

                if not target_device or target_device.isNull():
                    logger.warning("No audio input hardware detected.")
                    return False

                fmt = QAudioFormat()
                fmt.setSampleRate(16000)
                fmt.setChannelCount(1)
                fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)

                if not target_device.isFormatSupported(fmt):
                    fmt = target_device.preferredFormat()

                self._capture_sample_rate = fmt.sampleRate()
                self._capture_channels = fmt.channelCount()
                self._capture_is_float = fmt.sampleFormat() == QAudioFormat.SampleFormat.Float
                self._active_input_device_name = target_device.description()

                self._audio_source = QAudioSource(target_device, fmt)
                self._audio_io = self._audio_source.start()

                def _read_audio_chunk() -> None:
                    if self._audio_io and self._audio_io.isOpen():
                        data = self._audio_io.readAll().data()
                        if data:
                            pcm_16k = normalize_audio_to_16k_mono_pcm16(
                                raw_bytes=data,
                                src_rate=self._capture_sample_rate,
                                channels=self._capture_channels,
                                is_float=self._capture_is_float,
                            )
                            if pcm_16k:
                                self.process_incoming_audio_frame(pcm_16k)

                self._audio_timer = QTimer()
                self._audio_timer.timeout.connect(_read_audio_chunk)
                self._audio_timer.start(50)

                logger.info(
                    f"Microphone capture stream started on device: '{self._active_input_device_name}' "
                    f"({self._capture_sample_rate}Hz, {self._capture_channels}ch, float={self._capture_is_float})"
                )
                return True
            except Exception as exc:
                logger.warning(f"Could not start hardware audio capture: {exc}")
                return False

    def stop_audio_capture(self) -> None:
        """Stop hardware microphone capture stream."""
        with self._lock:
            if self._audio_timer is not None:
                with contextlib.suppress(Exception):
                    self._audio_timer.stop()
                self._audio_timer = None

            if self._audio_source is not None:
                with contextlib.suppress(Exception):
                    self._audio_source.stop()
                self._audio_source = None
                self._audio_io = None
            logger.debug("Microphone capture stream stopped.")

    def trigger_push_to_talk(self) -> bool:
        """User pressed Push-to-Talk button."""
        with self._lock:
            if self.wake_word_detector.is_muted:
                logger.info("PTT ignored: Voice listening is MUTED.")
                return False

            # Barge-in: If JARVIS is currently speaking, stop TTS immediately
            if self.tts_service.is_speaking():
                logger.info("Barge-in: Interrupting TTS due to PTT activation.")
                self.tts_service.stop()
                self._cancellation_token.cancel()
                self._cancellation_token = CancellationToken()

            self.wake_word_detector.trigger_push_to_talk()
            self._is_ptt_triggered = True
            self._active_buffer.clear()
            # Prepend pre-roll buffer to prevent front-syllable clipping
            for chunk in self._pre_roll_buffer:
                self._active_buffer.extend(chunk)
            self._pre_roll_buffer.clear()
            self.vad.reset()
            self._is_recording = True
            self.start_audio_capture()
            self.set_state(VoiceState.RECORDING, {"trigger": "ptt"})
            return True

    def process_incoming_audio_frame(self, pcm_data: bytes) -> None:
        """Ingest real-time microphone PCM audio frame."""
        with self._lock:
            if self.wake_word_detector.is_muted:
                self._current_mic_level = 0.0
                return

            if self._is_wake_acknowledging:
                # Do not ingest microphone feedback while speaking the acknowledgment
                return

            # 1. Real-time RMS calculation for authentic visual metering
            rms = self.vad.compute_rms(pcm_data)
            # Boost RMS slightly (x8) for visual responsiveness on typical microphones, clamped [0.0, 1.0]
            meter_level = min(1.0, max(0.0, rms * 8.0))
            # Smooth with previous value (exponential moving average: 70% current, 30% prev)
            self._current_mic_level = 0.7 * meter_level + 0.3 * self._current_mic_level

            if self._mic_level_callback:
                with contextlib.suppress(Exception):
                    self._mic_level_callback(self._current_mic_level)

            # 2. Acoustic Echo Suppression during active TTS playback
            # Laptop speakers output audio directly into the microphone at RMS ~0.10 to 0.40.
            # To ensure complete, uninterrupted sentence delivery without glitching or self-aborting,
            # acoustic barge-in is only triggered by an intentional, loud user vocal command
            # (RMS > 0.65, amplitude > 21000) or explicit user control (PTT / UI buttons).
            # Normal speaker audio and ambient room noise will NEVER interrupt assistant speech.
            if self.tts_service.is_speaking():
                barge_enabled = getattr(self.settings, "voice_barge_in_enabled", True)
                if barge_enabled and rms > 0.45:
                    logger.info(
                        "Barge-in: Intentional user interruption detected during TTS playback. Stopping speech."
                    )
                    self._barge_in_consecutive_frames = 0
                    self.tts_service.stop()
                    self.wake_word_detector.set_tts_active(False)
                    self._cancellation_token.cancel()
                    self._cancellation_token = CancellationToken()
                    self.set_state(VoiceState.INTERRUPTED, {"reason": "barge_in_speech_detected"})
                    # Discard previous echo in buffers, but preserve this speech onset frame
                    self._active_buffer.clear()
                    self._pre_roll_buffer.clear()
                    self.vad.reset()
                    self._is_recording = True
                    self._active_buffer.extend(pcm_data)
                    self.vad.process_frame(pcm_data)
                    self.set_state(VoiceState.RECORDING, {"trigger": "barge_in"})
                return
            else:
                self._barge_in_consecutive_frames = 0

            vad_result = self.vad.process_frame(pcm_data)

            # 3. Audio Recording State
            if self._is_recording:
                self._active_buffer.extend(pcm_data)
                # Check silence timeout
                if self.vad.is_silence_timeout_reached():
                    logger.info("VAD detected silence end of utterance.")
                    self._finish_recording_and_transcribe()
            else:
                # 4. Continuous listening / Conversation mode / Standby mode
                if self._is_conversation_mode:
                    if vad_result.is_speech:
                        logger.debug("Speech onset in conversation mode. Recording utterance.")
                        self._active_buffer.clear()
                        for chunk in self._pre_roll_buffer:
                            self._active_buffer.extend(chunk)
                        self._pre_roll_buffer.clear()
                        self._active_buffer.extend(pcm_data)
                        self.vad.reset()
                        self._is_recording = True
                        self.set_state(VoiceState.RECORDING, {"mode": "conversation"})
                    else:
                        self._pre_roll_buffer.append(pcm_data)
                else:
                    # Wake Word Standby Mode
                    acoustic_hit, conf = self.wake_word_detector.process_pcm_frame(pcm_data)
                    if acoustic_hit:
                        logger.info(f"Acoustic wake word trigger activated (conf={conf:.2f})")
                        self._acoustic_wake_confirmed = True
                        self.set_state(
                            VoiceState.WAKE_DETECTED,
                            {"wake_word": self.wake_word_detector.wake_word, "confidence": conf},
                        )
                        self._active_buffer.clear()
                        for chunk in self._pre_roll_buffer:
                            self._active_buffer.extend(chunk)
                        self._pre_roll_buffer.clear()
                        self._active_buffer.extend(pcm_data)
                        self.vad.reset()
                        self._is_recording = True
                        self.set_state(VoiceState.RECORDING, {"trigger": "acoustic_wake"})
                        return

                    if vad_result.is_speech and (
                        getattr(self.settings, "voice_continuous_listening", False)
                        or self.wake_word_detector.enabled
                    ):
                        self._active_buffer.clear()
                        for chunk in self._pre_roll_buffer:
                            self._active_buffer.extend(chunk)
                        self._pre_roll_buffer.clear()
                        self._active_buffer.extend(pcm_data)
                        self.vad.reset()
                        self._is_recording = True
                        self.set_state(VoiceState.RECORDING)
                    else:
                        self._pre_roll_buffer.append(pcm_data)

    def _is_session_stop_command(self, text: str) -> bool:
        """Check if user utterance is an explicit command to stop the persistent listening session."""
        if not text:
            return False
        import re

        cleaned = text.strip().lower()
        cleaned = re.sub(r"[.!?،؟]+$", "", cleaned).strip()

        english_stops = (
            "stop listening",
            "end the conversation",
            "end the conversation session",
            "end conversation",
            "stop the conversation",
            "stop conversation",
            "stop listening session",
            "end listening session",
            "stop listening mode",
            "cancel listening",
            "finish conversation",
            "exit conversation",
            "go to standby",
            "sleep now",
        )
        if any(cleaned == s or cleaned.startswith(s) for s in english_stops):
            return True

        persian_stops = (
            "دیگه گوش نکن",
            "دیگه گوش نده",
            "حالت شنیدن رو متوقف کن",
            "حالت شنیدن را متوقف کن",
            "مکالمه رو قطع کن",
            "مکالمه را قطع کن",
            "شنیدن رو قطع کن",
            "شنیدن را قطع کن",
            "بس کن",
            "خاموش شو",
            "برو استندبای",
            "دیگه حرف نزن",
            "گوش نده",
            "مکالمه را تمام کن",
            "مکالمه رو تموم کن",
            "پایان مکالمه",
            "توقف شنیدن",
        )
        norm = cleaned.replace("ي", "ی").replace("ك", "ک").replace("‌", " ")
        norm = re.sub(r"\s+", " ", norm).strip()
        return any(p in norm for p in persian_stops)

    def _finish_recording_and_transcribe(self) -> None:
        """Utterance completed; transcribe and submit to agent."""
        self._is_recording = False
        self._last_utterance_end_time = time.perf_counter()
        audio_snapshot = bytes(self._active_buffer)
        self._active_buffer.clear()
        self.vad.reset()

        if (
            not self._is_conversation_mode
            and not getattr(self.settings, "voice_continuous_listening", False)
            and not self.wake_word_detector.enabled
        ):
            self.stop_audio_capture()

        if len(audio_snapshot) < 800:  # < 50ms of audio, ignore click
            if self._is_conversation_mode:
                self.set_state(VoiceState.LISTENING)
            else:
                self.set_state(VoiceState.IDLE)
            return

        self.set_state(VoiceState.TRANSCRIBING)

        is_ptt = self._is_ptt_triggered
        self._is_ptt_triggered = False

        threading.Thread(
            target=self._transcribe_worker,
            args=(audio_snapshot, is_ptt),
            daemon=True,
            name="VoiceTranscribeWorker",
        ).start()

    def _handle_wake_word_acknowledgment(self, language: str = "en") -> None:
        """User spoke the wake word alone; acknowledge and maintain active listening."""
        ack_text = "Yes, sir? I am listening." if language != "fa" else "بله، در خدمتم."
        with self._lock:
            self._is_recording = False
            self._is_wake_acknowledging = True
            self._active_buffer.clear()
            self._pre_roll_buffer.clear()
            self.vad.reset()
        self.speak(ack_text)

    def _transcribe_worker(self, audio_data: bytes, is_ptt: bool = False) -> None:
        t_start = time.perf_counter()
        try:
            res = self.stt_service.transcribe(
                audio_data=audio_data,
                language=getattr(self.settings, "voice_stt_language", "auto"),
                cancellation_token=self._cancellation_token,
            )
            t_end = time.perf_counter()
            stt_latency_ms = (t_end - t_start) * 1000.0
            self._latency_history.append(
                {
                    "stt_ms": stt_latency_ms,
                    "audio_len": len(audio_data),
                    "duration_s": len(audio_data) / 32000.0,
                }
            )
            logger.info(
                f"STT completed in {stt_latency_ms:.1f}ms: '{res.text}' (lang={res.language})"
            )

            if res.error:
                logger.warning(f"Voice transcription denied or failed: {res.error}")
                self.set_state(VoiceState.ERROR, {"error": res.error})
                time.sleep(0.5)
                if self._is_conversation_mode:
                    self.set_state(VoiceState.LISTENING)
                else:
                    self.set_state(VoiceState.IDLE)
                return

            if not res.text.strip():
                logger.info("Empty transcript from audio.")
                if self._is_conversation_mode:
                    self.set_state(VoiceState.LISTENING)
                else:
                    self.set_state(VoiceState.IDLE)
                return

            require_prefix = getattr(self.settings, "voice_require_prefix", True)
            starts_with_ww, stripped_command = self.wake_word_detector.check_starts_with_wake_word(
                res.text
            )

            # Strict Prefix Policy: Only process if the sentence starts with the wake word ('Jarvis' or 'جارویس')
            # When in active conversation mode or Push-To-Talk, subsequent turns don't require repeating the wake word.
            if require_prefix:
                if not starts_with_ww and not is_ptt and not self._is_conversation_mode:
                    logger.info(
                        f"Speech ignored because utterance did not start with wake word 'Jarvis': '{res.text}'"
                    )
                    self.set_state(VoiceState.IDLE)
                    return

                if starts_with_ww:
                    res.detected_wake_word = True
                    res.text = stripped_command

                    # If wake word spoken alone (e.g. "Jarvis" or "جارویس")
                    if not stripped_command.strip():
                        logger.info(
                            "Wake word detected alone at start of utterance; acknowledging."
                        )
                        if not self._is_conversation_mode:
                            self.start_conversation_mode()
                        self._handle_wake_word_acknowledgment(res.language)
                        return

                    # Check for conversation stop command
                    if self._is_session_stop_command(stripped_command):
                        logger.info(
                            f"Session stop voice command detected: '{stripped_command}'. Stopping session."
                        )
                        self.stop_conversation_mode()
                        stop_ack = (
                            "Listening session ended, sir."
                            if res.language != "fa"
                            else "حالت شنیدن متوقف شد قربان."
                        )
                        self.speak(stop_ack)
                        return

                    if not self._is_conversation_mode:
                        self.start_conversation_mode()
                    self._dispatch_command(res)
                    return
                elif self._is_conversation_mode or is_ptt:
                    # Multi-turn conversation mode active or PTT triggered
                    if self._is_session_stop_command(res.text):
                        self.stop_conversation_mode()
                        stop_ack = (
                            "Listening session ended, sir."
                            if res.language != "fa"
                            else "حالت شنیدن متوقف شد قربان."
                        )
                        self.speak(stop_ack)
                        return
                    res.detected_wake_word = True
                    self._dispatch_command(res)
                    return

            # Legacy mode when voice_require_prefix is explicitly set to False
            detected, legacy_stripped = self.wake_word_detector.check_text(res.text)

            # In Conversation Mode:
            if self._is_conversation_mode:
                if self._is_session_stop_command(res.text):
                    logger.info(
                        f"Session stop voice command detected: '{res.text}'. Stopping listening session."
                    )
                    self.stop_conversation_mode()
                    stop_ack = (
                        "Listening session ended, sir."
                        if res.language != "fa"
                        else "حالت شنیدن متوقف شد قربان."
                    )
                    self.speak(stop_ack)
                    return

                if detected and legacy_stripped:
                    res.text = legacy_stripped
                    res.detected_wake_word = True
                self._dispatch_command(res)
                return

            # In Standby Wake-Word Mode:
            if self.wake_word_detector.enabled:
                if detected:
                    res.detected_wake_word = True
                    self.start_conversation_mode()
                    if legacy_stripped:
                        res.text = legacy_stripped
                        self._dispatch_command(res)
                    else:
                        logger.info(
                            "Wake word detected without command; activating persistent listening session."
                        )
                        self._handle_wake_word_acknowledgment(res.language)
                    return
                elif self._acoustic_wake_confirmed:
                    self.start_conversation_mode()
                    self._dispatch_command(res)
                    return
                else:
                    logger.debug(f"Speech discarded (no wake word in transcript: '{res.text}')")
                    self.set_state(VoiceState.IDLE)
                    return
            else:
                if detected and legacy_stripped:
                    res.text = legacy_stripped
                    res.detected_wake_word = True
                self._dispatch_command(res)
        except Exception as exc:
            logger.error(f"Error during voice transcription: {exc}")
            self.set_state(VoiceState.ERROR, {"error": str(exc)})
            time.sleep(0.5)
            if self._is_conversation_mode:
                self.set_state(VoiceState.LISTENING)
            else:
                self.set_state(VoiceState.IDLE)

    def _dispatch_command(self, transcript: TranscriptResult) -> None:
        logger.info(
            f"Validated voice command: '{transcript.text}' (lang={transcript.language}, conf={transcript.confidence:.2f})"
        )
        if self.event_bus:
            self.event_bus.publish(
                AgentEvent(
                    event_type=AgentEventType.VOICE_TRANSCRIPT_READY,
                    payload={
                        "text": transcript.text,
                        "language": transcript.language,
                        "confidence": transcript.confidence,
                        "is_ambiguous": transcript.is_ambiguous,
                    },
                )
            )

        # Indicate THINKING / UNDERSTANDING while agent generates response
        self.set_state(VoiceState.UNDERSTANDING)
        self.set_state(VoiceState.THINKING)

        if self._on_command_callback:
            try:
                self._on_command_callback(transcript.text, transcript)
            except Exception as exc:
                logger.error(f"Error in on_command_callback: {exc}")
                if self._is_conversation_mode:
                    self.set_state(VoiceState.LISTENING)
                else:
                    self.set_state(VoiceState.IDLE)

    def speak(
        self,
        text: str,
        voice_name: str | None = None,
        rate: float | None = None,
        queue: bool = False,
    ) -> bool:
        """Synthesize agent text response with barge-in and sentence queueing support."""
        if not getattr(self.settings, "voice_tts_enabled", True):
            if self._is_conversation_mode:
                self.set_state(VoiceState.LISTENING)
            return False

        with self._lock:
            if queue and self.tts_service.is_speaking():
                logger.debug(f"Queuing sentence for speech playback: '{text[:40]}...'")
                self._speech_queue.append((text, voice_name, rate))
                return True

        req = TTSRequest(
            text=text,
            voice_name=voice_name or getattr(self.settings, "voice_tts_voice", None),
            rate=rate or getattr(self.settings, "voice_tts_rate", 1.0),
            volume=getattr(self.settings, "voice_tts_volume", 1.0),
        )
        self.set_state(VoiceState.SPEAKING, {"text": text[:100]})
        self.wake_word_detector.set_tts_active(True)
        success = self.tts_service.speak(req)

        # Monitor playback completion in background thread
        def _monitor_playback_completion() -> None:
            time.sleep(0.05)
            while self.tts_service.is_speaking():
                time.sleep(0.03)
            with self._lock:
                self.wake_word_detector.set_tts_active(False)
                was_acknowledgment = self._is_wake_acknowledging
                self._is_wake_acknowledging = False
                self._barge_in_consecutive_frames = 0
                self._active_buffer.clear()
                self._pre_roll_buffer.clear()
                self.vad.reset()

                # If there are queued sentences waiting, pop and play the next one
                if self._speech_queue:
                    next_text, next_voice, next_rate = self._speech_queue.popleft()
                    logger.debug(f"Popping next queued sentence to speak: '{next_text[:40]}...'")
                    threading.Thread(
                        target=self.speak,
                        args=(next_text, next_voice, next_rate, False),
                        daemon=True,
                        name="VoiceTTSQueueSpeaker",
                    ).start()
                    return

                if was_acknowledgment:
                    # Wake word was acknowledged; ready to listen for user command
                    self._is_recording = False
                    self._acoustic_wake_confirmed = False
                    self.set_state(VoiceState.LISTENING, {"mode": "conversation_active"})
                elif self._state == VoiceState.SPEAKING:
                    if self._is_conversation_mode:
                        self.set_state(VoiceState.WAITING)
                        time.sleep(0.1)
                        self.set_state(VoiceState.LISTENING, {"mode": "conversation_active"})
                    else:
                        self.set_state(VoiceState.IDLE)

        threading.Thread(
            target=_monitor_playback_completion,
            daemon=True,
            name="VoiceTTSPlaybackMonitor",
        ).start()

        return success

    def interrupt_speech(self) -> None:
        """User or system triggered barge-in interruption."""
        with self._lock:
            self._speech_queue.clear()
            self.tts_service.stop()
            self.wake_word_detector.set_tts_active(False)
            self.set_state(VoiceState.INTERRUPTED, {"reason": "user_interruption"})
            if self._is_conversation_mode:
                self.set_state(VoiceState.LISTENING)
            else:
                self.set_state(VoiceState.IDLE)

    def cancel_active_speech_and_generation(self) -> None:
        """Immediately cancel active speech, signal cancellation to running workers,
        and clear audio input buffers so stale utterances are discarded.
        """
        with self._lock:
            self._speech_queue.clear()
            self.tts_service.stop()
            self.wake_word_detector.set_tts_active(False)
            self._cancellation_token.cancel()
            self._cancellation_token = CancellationToken()
            self._active_buffer.clear()
            self._pre_roll_buffer.clear()
            self.vad.reset()
            self._is_recording = False
            self.set_state(VoiceState.INTERRUPTED, {"reason": "cancellation_requested"})
            if self._is_conversation_mode:
                self.set_state(VoiceState.LISTENING)
            else:
                self.set_state(VoiceState.IDLE)
            logger.info("Active voice speech and processing cancelled completely.")

    def get_latency_metrics(self) -> dict[str, Any]:
        """Return computed latency metrics from recent turns."""
        with self._lock:
            stt_times = [m["stt_ms"] for m in self._latency_history if "stt_ms" in m]
            if not stt_times:
                return {"count": 0, "median_stt_ms": 0.0, "p90_stt_ms": 0.0, "p95_stt_ms": 0.0}
            sorted_times = sorted(stt_times)
            n = len(sorted_times)
            med = sorted_times[n // 2]
            p90 = sorted_times[min(int(n * 0.9), n - 1)]
            p95 = sorted_times[min(int(n * 0.95), n - 1)]
            return {
                "count": n,
                "median_stt_ms": round(med, 2),
                "p90_stt_ms": round(p90, 2),
                "p95_stt_ms": round(p95, 2),
                "max_stt_ms": round(max(sorted_times), 2),
            }

    def preview_british_voice(self, voice_name: str | None = None) -> bool:
        """Preview British JARVIS neural voice persona."""
        if hasattr(self.tts_service, "preview_voice"):
            return self.tts_service.preview_voice(voice_name=voice_name)
        preview_phrase = (
            "Good day, sir. JARVIS voice identity online, operational, and at your service."
        )
        return self.speak(preview_phrase, voice_name=voice_name)

    def mute(self) -> None:
        """Mute voice listening."""
        self.wake_word_detector.mute()
        self.tts_service.stop()
        self._is_recording = False
        self._active_buffer.clear()
        self.set_state(VoiceState.MUTED)

    def unmute(self) -> None:
        """Unmute voice listening."""
        self.wake_word_detector.unmute()
        self.set_state(VoiceState.IDLE)
