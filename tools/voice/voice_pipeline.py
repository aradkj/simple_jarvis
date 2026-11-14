"""Coordinated Conversational Audio Pipeline for JARVIS Phase 9.

Orchestrates Audio Capture -> Wake Word / PTT -> VAD -> STT -> Transcript Validation ->
Agent Request -> Response Generation -> TTS with real-time Barge-In support.
"""

from __future__ import annotations

import contextlib
import threading
import time
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


def normalize_audio_to_16k_mono_pcm16(
    raw_bytes: bytes,
    src_rate: int = 16000,
    channels: int = 1,
    is_float: bool = False,
) -> bytes:
    """Normalize hardware audio capture (e.g. 48kHz Stereo Float from AirPods / Realtek)

    to canonical 16000Hz Mono 16-bit signed PCM audio.
    """
    if not raw_bytes:
        return b""

    # Fast path: already 16kHz Mono Int16
    if src_rate == 16000 and channels == 1 and not is_float:
        return raw_bytes

    import struct

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
        if src_rate == 48000:
            samples = samples[::3]
        elif src_rate == 32000:
            samples = samples[::2]
        else:
            ratio = src_rate / 16000.0
            target_len = int(len(samples) / ratio)
            if target_len <= 0:
                return b""
            resampled = []
            for i in range(target_len):
                src_idx = i * ratio
                idx0 = int(src_idx)
                idx1 = min(idx0 + 1, len(samples) - 1)
                frac = src_idx - idx0
                resampled.append(samples[idx0] * (1.0 - frac) + samples[idx1] * frac)
            samples = resampled

    # Pack to 16-bit signed PCM
    out_ints = [max(-32768, min(32767, int(s * 32767.0))) for s in samples]
    return struct.pack(f"<{len(out_ints)}h", *out_ints)


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
            silence_timeout_seconds=getattr(self.settings, "voice_silence_timeout_seconds", 1.8),
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
        self._is_recording = False
        self._acoustic_wake_confirmed = False
        self._on_command_callback: Callable[[str, TranscriptResult], None] | None = None
        self._cancellation_token = CancellationToken()
        self._audio_source: Any = None
        self._audio_io: Any = None
        self._audio_timer: Any = None
        self._capture_sample_rate: int = 16000
        self._capture_channels: int = 1
        self._capture_is_float: bool = False

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
                    f"Microphone capture stream started on device: '{target_device.description()}' "
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
                logger.info("Barge-in: Interrupting TTS due to user speech.")
                self.tts_service.stop()

            self.wake_word_detector.trigger_push_to_talk()
            self._active_buffer.clear()
            self.vad.reset()
            self._is_recording = True
            self.start_audio_capture()
            self.set_state(VoiceState.RECORDING)
            return True

    def process_incoming_audio_frame(self, pcm_data: bytes) -> None:
        """Ingest real-time microphone PCM audio frame."""
        with self._lock:
            if self.wake_word_detector.is_muted:
                return

            vad_result = self.vad.process_frame(pcm_data)

            # Barge-in detection: If speech is detected while TTS is actively playing, interrupt TTS
            if vad_result.is_speech and self.tts_service.is_speaking():
                logger.info("Barge-in: Active speech detected while speaking, stopping TTS.")
                self.tts_service.stop()
                self.wake_word_detector.set_tts_active(False)
                self.set_state(VoiceState.INTERRUPTED, {"reason": "barge_in_speech_detected"})

            if self._is_recording:
                self._active_buffer.extend(pcm_data)
                # Check silence timeout
                if self.vad.is_silence_timeout_reached():
                    logger.info("VAD detected silence end of utterance.")
                    self._finish_recording_and_transcribe()
            else:
                # 1. Real-time acoustic wake word check on raw PCM audio frame
                acoustic_hit, conf = self.wake_word_detector.process_pcm_frame(pcm_data)
                if acoustic_hit:
                    logger.info(f"Acoustic wake word trigger activated (conf={conf:.2f})")
                    self._acoustic_wake_confirmed = True
                    self.set_state(
                        VoiceState.WAKE_DETECTED,
                        {"wake_word": self.wake_word_detector.wake_word, "confidence": conf},
                    )
                    self._active_buffer.clear()
                    self.vad.reset()
                    self._is_recording = True
                    self.set_state(VoiceState.LISTENING)
                    return

                # 2. Continuous listening or speech buffer
                if vad_result.is_speech and (
                    getattr(self.settings, "voice_continuous_listening", False)
                    or self.wake_word_detector.enabled
                ):
                    self._acoustic_wake_confirmed = False
                    self._active_buffer.clear()
                    self._active_buffer.extend(pcm_data)
                    self.vad.reset()
                    self._is_recording = True
                    self.set_state(VoiceState.RECORDING)

    def _finish_recording_and_transcribe(self) -> None:
        """Utterance completed; transcribe and submit to agent."""
        self._is_recording = False
        audio_snapshot = bytes(self._active_buffer)
        self._active_buffer.clear()
        self.vad.reset()

        if (
            not getattr(self.settings, "voice_continuous_listening", False)
            and not self.wake_word_detector.enabled
        ):
            self.stop_audio_capture()

        if len(audio_snapshot) < 800:  # < 50ms of audio, ignore click
            self.set_state(VoiceState.IDLE)
            return

        self.set_state(VoiceState.TRANSCRIBING)

        threading.Thread(
            target=self._transcribe_worker,
            args=(audio_snapshot,),
            daemon=True,
            name="VoiceTranscribeWorker",
        ).start()

    def _handle_wake_word_acknowledgment(self, language: str = "en") -> None:
        """User spoke the wake word alone; acknowledge and maintain active listening."""
        ack_text = "Yes, sir? I am listening."
        self.speak(ack_text)
        self.set_state(VoiceState.LISTENING)
        self._active_buffer.clear()
        self.vad.reset()
        self._is_recording = True
        self._acoustic_wake_confirmed = True

    def _transcribe_worker(self, audio_data: bytes) -> None:
        try:
            res = self.stt_service.transcribe(
                audio_data=audio_data,
                language=getattr(self.settings, "voice_stt_language", "auto"),
                cancellation_token=self._cancellation_token,
            )
            if res.error:
                logger.warning(f"Voice transcription denied or failed: {res.error}")
                self.set_state(VoiceState.ERROR, {"error": res.error})
                time.sleep(0.5)
                self.set_state(VoiceState.IDLE)
                return

            if not res.text.strip():
                logger.info("Empty transcript from audio.")
                self.set_state(VoiceState.IDLE)
                return

            detected, stripped_command = self.wake_word_detector.check_text(res.text)
            if self.wake_word_detector.enabled:
                if detected:
                    res.detected_wake_word = True
                    if stripped_command:
                        res.text = stripped_command
                        self._dispatch_command(res)
                    else:
                        logger.info(
                            "Wake word detected without command; acknowledging and listening."
                        )
                        self._handle_wake_word_acknowledgment(res.language)
                    return
                elif self._acoustic_wake_confirmed:
                    # Acoustic detector was already confirmed on frame
                    self._dispatch_command(res)
                    return
                else:
                    logger.debug(f"Speech discarded (no wake word in transcript: '{res.text}')")
                    self.set_state(VoiceState.IDLE)
                    return
            else:
                if detected and stripped_command:
                    res.text = stripped_command
                    res.detected_wake_word = True
                self._dispatch_command(res)
        except Exception as exc:
            logger.error(f"Error during voice transcription: {exc}")
            self.set_state(VoiceState.ERROR, {"error": str(exc)})
            time.sleep(1.0)
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

        self.set_state(VoiceState.IDLE)

        if self._on_command_callback:
            try:
                self._on_command_callback(transcript.text, transcript)
            except Exception as exc:
                logger.error(f"Error in on_command_callback: {exc}")

    def speak(self, text: str, voice_name: str | None = None, rate: float | None = None) -> bool:
        """Synthesize agent text response with barge-in support."""
        if not getattr(self.settings, "voice_tts_enabled", True):
            return False

        req = TTSRequest(
            text=text,
            voice_name=voice_name or getattr(self.settings, "voice_tts_voice", None),
            rate=rate or getattr(self.settings, "voice_tts_rate", 1.0),
            volume=getattr(self.settings, "voice_tts_volume", 1.0),
        )
        self.set_state(VoiceState.SPEAKING, {"text": text[:100]})
        self.wake_word_detector.set_tts_active(True)
        success = self.tts_service.speak(req)
        # If speech completed or failed synchronously, release TTS active lock
        if not self.tts_service.is_speaking():
            self.wake_word_detector.set_tts_active(False)
            if self.state == VoiceState.SPEAKING:
                self.set_state(VoiceState.IDLE)
        return success

    def interrupt_speech(self) -> None:
        """User or system triggered barge-in interruption."""
        self.tts_service.stop()
        self.wake_word_detector.set_tts_active(False)
        self.set_state(VoiceState.INTERRUPTED, {"reason": "user_interruption"})
        self.set_state(VoiceState.IDLE)

    def cancel_active_speech_and_generation(self) -> None:
        """Immediately cancel active speech, signal cancellation to running workers,
        and clear audio input buffers so stale utterances are discarded.
        """
        with self._lock:
            self.tts_service.stop()
            self.wake_word_detector.set_tts_active(False)
            self._cancellation_token.cancel()
            self._cancellation_token = CancellationToken()
            self._active_buffer.clear()
            self.vad.reset()
            self._is_recording = False
            self.set_state(VoiceState.INTERRUPTED, {"reason": "cancellation_requested"})
            self.set_state(VoiceState.IDLE)
            logger.info("Active voice speech and processing cancelled completely.")

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
