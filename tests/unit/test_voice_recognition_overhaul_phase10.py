"""Unit and integration test suite for JARVIS Voice Recognition Overhaul & UI Redesign.

Tests:
1. Pre-roll ring buffer and elimination of front-syllable clipping.
2. Continuous multi-turn conversation mode and wake-word bypass.
3. Full-duplex barge-in interruption, token cancellation, and echo purge.
4. Real-time microphone RMS level metering and hardware device validation.
5. Cinematic visualizer state reactivity, theme palette mapping, and rendering.
"""

from __future__ import annotations

import math

from tools.voice.device_manager import AudioDeviceManager
from tools.voice.models import TranscriptResult, TTSRequest, VoiceState
from tools.voice.stt_service import MockSTTService
from tools.voice.tts_service import MockTTSService
from tools.voice.voice_pipeline import (
    ConversationalVoicePipeline,
    normalize_audio_to_16k_mono_pcm16,
)
from tools.voice.wake_word import WakeWordDetector
from ui.visualizer import JarvisVisualizerWidget


def generate_pcm_sine(
    freq_hz: float = 440.0,
    duration_s: float = 0.1,
    amplitude: float = 0.5,
    sample_rate: int = 16000,
) -> bytes:
    """Generate synthetic 16-bit mono signed PCM audio."""
    total_samples = int(sample_rate * duration_s)
    pcm = bytearray()
    amp_int = int(32767 * amplitude)
    for i in range(total_samples):
        val = int(amp_int * math.sin(2.0 * math.pi * freq_hz * i / sample_rate))
        val = max(-32768, min(32767, val))
        pcm.extend(val.to_bytes(2, "little", signed=True))
    return bytes(pcm)


# ============================================================================
# 1. Pre-Roll Ring Buffer & Elimination of Syllable Front-Clipping
# ============================================================================
class TestPreRollRingBufferAndCapture:
    """Verify pre-roll ring buffer captures early audio and prevents syllable truncation."""

    def test_preroll_buffer_collects_sliding_window_chunks(self) -> None:
        pipeline = ConversationalVoicePipeline()
        assert len(pipeline._pre_roll_buffer) == 0
        assert pipeline._pre_roll_buffer.maxlen == 10

        chunk = b"\x05\x00" * 800  # 50ms chunk
        for _ in range(15):
            pipeline.process_incoming_audio_frame(chunk)

        # Buffer must maintain maximum 10 chunks (~500ms sliding history)
        assert len(pipeline._pre_roll_buffer) == 10

    def test_preroll_prepended_on_speech_onset_in_conversation_mode(self) -> None:
        pipeline = ConversationalVoicePipeline()
        pipeline.start_conversation_mode()
        assert pipeline.is_conversation_mode is True

        # Ingest 3 pre-roll ambient frames (low amplitude)
        quiet_chunk = generate_pcm_sine(amplitude=0.005, duration_s=0.05)
        for _ in range(3):
            pipeline.process_incoming_audio_frame(quiet_chunk)

        assert len(pipeline._pre_roll_buffer) == 3

        # Now simulate loud user speech frame that crosses VAD threshold
        speech_chunk = generate_pcm_sine(amplitude=0.6, duration_s=0.15)
        pipeline.process_incoming_audio_frame(speech_chunk)

        # Pipeline must have transitioned to RECORDING
        assert pipeline.state == VoiceState.RECORDING
        assert pipeline._is_recording is True

        # Pre-roll buffer must have been prepended into active buffer and cleared
        assert len(pipeline._pre_roll_buffer) == 0
        # Active buffer contains the 3 quiet chunks plus the speech chunk
        expected_min_bytes = (3 * len(quiet_chunk)) + len(speech_chunk)
        assert len(pipeline._active_buffer) >= expected_min_bytes

    def test_preroll_prepended_on_push_to_talk(self) -> None:
        pipeline = ConversationalVoicePipeline()
        quiet_chunk = b"\x10\x00" * 400
        for _ in range(4):
            pipeline._pre_roll_buffer.append(quiet_chunk)

        assert len(pipeline._pre_roll_buffer) == 4

        # User presses Push-to-Talk
        success = pipeline.trigger_push_to_talk()
        assert success is True
        assert pipeline.state == VoiceState.RECORDING
        # Active buffer got pre-roll prepended
        assert len(pipeline._active_buffer) == 4 * len(quiet_chunk)
        assert len(pipeline._pre_roll_buffer) == 0


# ============================================================================
# 2. Continuous Multi-Turn Conversation Mode
# ============================================================================
class TestConversationModeLifecycleAndDispatches:
    """Verify multi-turn conversation mode and wake-word bypass."""

    def test_conversation_mode_toggle_and_state(self) -> None:
        pipeline = ConversationalVoicePipeline()
        assert pipeline.is_conversation_mode is False

        # Start conversation mode
        pipeline.start_conversation_mode()
        assert pipeline.is_conversation_mode is True
        assert pipeline.state == VoiceState.LISTENING

        # Toggle off
        active = pipeline.toggle_conversation_mode()
        assert active is False
        assert pipeline.is_conversation_mode is False
        assert pipeline.state == VoiceState.IDLE

        # Toggle on
        active = pipeline.toggle_conversation_mode()
        assert active is True
        assert pipeline.is_conversation_mode is True
        assert pipeline.state == VoiceState.LISTENING

    def test_conversation_mode_dispatches_without_wake_word(self) -> None:
        """In active conversation mode, user speech without 'Hey Jarvis' must NOT be discarded."""
        mock_stt = MockSTTService(preset_transcript="وضعیت حافظه سیستم رو گزارش کن")
        mock_tts = MockTTSService()
        detector = WakeWordDetector(wake_word="Jarvis", enabled=True)

        pipeline = ConversationalVoicePipeline(
            stt_service=mock_stt,
            tts_service=mock_tts,
            wake_word_detector=detector,
        )
        pipeline.start_conversation_mode()

        received_commands = []
        pipeline.set_command_callback(lambda txt, res: received_commands.append(txt))

        # Utterance does not contain "Hey Jarvis"
        audio_data = b"\x20\x00" * 4000
        pipeline._transcribe_worker(audio_data)

        # Must be dispatched directly without being discarded!
        assert len(received_commands) == 1
        assert received_commands[0] == "وضعیت حافظه سیستم رو گزارش کن"

    def test_conversation_mode_strips_wake_word_if_user_speaks_it(self) -> None:
        """If user happens to speak 'Jarvis, what is the time?', wake word is stripped cleanly."""
        mock_stt = MockSTTService(preset_transcript="Hey Jarvis, what is my CPU temperature?")
        detector = WakeWordDetector(wake_word="Hey Jarvis", enabled=True)

        pipeline = ConversationalVoicePipeline(
            stt_service=mock_stt,
            wake_word_detector=detector,
        )
        pipeline.start_conversation_mode()

        dispatched = []
        pipeline.set_command_callback(lambda txt, res: dispatched.append(txt))

        pipeline._transcribe_worker(b"\x20\x00" * 4000)

        assert len(dispatched) == 1
        assert "what is my CPU temperature?" in dispatched[0]

    def test_command_dispatch_transitions_to_thinking_state(self) -> None:
        pipeline = ConversationalVoicePipeline()
        transcript = TranscriptResult(text="Test Command", language="en", confidence=0.95)

        pipeline._dispatch_command(transcript)
        assert pipeline.state == VoiceState.THINKING


# ============================================================================
# 3. Full-Duplex Barge-In & Speaker Echo Suppression
# ============================================================================
class TestFullDuplexBargeInAndEchoPurge:
    """Verify instant TTS purge and cancellation on user barge-in."""

    def test_barge_in_instantly_stops_tts_and_purges_buffers(self) -> None:
        mock_tts = MockTTSService()
        pipeline = ConversationalVoicePipeline(tts_service=mock_tts)

        # JARVIS is speaking
        mock_tts.speak(TTSRequest(text="JARVIS is explaining a complex operation..."))
        assert mock_tts.is_speaking() is True
        pipeline.set_state(VoiceState.SPEAKING)

        # User barges in with loud voice frame
        loud_speech = generate_pcm_sine(amplitude=0.7, duration_s=0.1)
        pipeline.process_incoming_audio_frame(loud_speech)

        # TTS must be stopped instantly
        assert mock_tts.is_speaking() is False
        # State must transition to RECORDING
        assert pipeline.state == VoiceState.RECORDING
        assert pipeline._is_recording is True

    def test_cancel_active_speech_and_generation_clears_all_buffers(self) -> None:
        mock_tts = MockTTSService()
        pipeline = ConversationalVoicePipeline(tts_service=mock_tts)

        pipeline._active_buffer.extend(b"\x12\x34" * 100)
        pipeline._pre_roll_buffer.append(b"\x56\x78" * 100)
        pipeline._is_recording = True

        pipeline.cancel_active_speech_and_generation()

        assert len(pipeline._active_buffer) == 0
        assert len(pipeline._pre_roll_buffer) == 0
        assert pipeline._is_recording is False
        assert pipeline.state == VoiceState.IDLE


# ============================================================================
# 4. Microphone RMS Metering & Device Management
# ============================================================================
class TestMicrophoneLevelMeteringAndDeviceManager:
    """Verify authentic RMS metering and device validation."""

    def test_real_time_rms_callback_invoked_with_normalized_float(self) -> None:
        pipeline = ConversationalVoicePipeline()
        reported_levels: list[float] = []

        pipeline.set_mic_level_callback(lambda lvl: reported_levels.append(lvl))

        # Ingest frame
        audio = generate_pcm_sine(amplitude=0.3, duration_s=0.05)
        pipeline.process_incoming_audio_frame(audio)

        assert len(reported_levels) == 1
        assert 0.0 <= reported_levels[0] <= 1.0
        assert pipeline.get_current_mic_level() > 0.0

    def test_audio_device_manager_device_options_and_validation(self) -> None:
        mgr = AudioDeviceManager()
        options = AudioDeviceManager.get_device_options(is_input=True)
        assert len(options) >= 1
        label, dev_id = options[0]
        assert isinstance(label, str)
        assert isinstance(dev_id, str)

        # Validate operational status
        is_ok, msg = mgr.validate_device(dev_id, is_input=True)
        assert is_ok is True
        assert "operational" in msg

        # Validate nonexistent device
        is_bad, bad_msg = mgr.validate_device("non_existent_mic_xyz", is_input=True)
        assert is_bad is False
        assert "disconnected" in bad_msg

    def test_device_name_and_restart(self) -> None:
        pipeline = ConversationalVoicePipeline()
        name = pipeline.get_active_input_device_name()
        assert isinstance(name, str)
        assert len(name) > 0


# ============================================================================
# 5. Cinematic Visualizer Widget
# ============================================================================
class TestCinematicVisualizerWidget:
    """Verify JarvisVisualizerWidget state updates, mic level scaling, and palette mapping."""

    def test_visualizer_state_updates(self, qtbot) -> None:
        widget = JarvisVisualizerWidget()
        qtbot.addWidget(widget)

        # IDLE
        widget.set_voice_state(VoiceState.IDLE)
        assert widget.get_voice_state() == "idle"
        assert "STANDBY" in widget._status_text

        # LISTENING
        widget.set_voice_state(VoiceState.LISTENING)
        assert widget.get_voice_state() == "listening"
        assert "LISTENING" in widget._status_text

        # RECORDING
        widget.set_voice_state(VoiceState.RECORDING)
        assert widget.get_voice_state() == "recording"
        assert "RECORDING" in widget._status_text

        # THINKING
        widget.set_voice_state(VoiceState.THINKING)
        assert widget.get_voice_state() == "thinking"
        assert "ANALYZING" in widget._status_text

        # SPEAKING
        widget.set_voice_state(VoiceState.SPEAKING)
        assert widget.get_voice_state() == "speaking"
        assert "GEORGE NEURAL" in widget._status_text

    def test_visualizer_mic_level_clamping(self, qtbot) -> None:
        widget = JarvisVisualizerWidget()
        qtbot.addWidget(widget)

        widget.set_mic_level(0.75)
        assert widget._target_mic_level == 0.75

        # Overclamped
        widget.set_mic_level(2.5)
        assert widget._target_mic_level == 1.0

        # Underclamped
        widget.set_mic_level(-0.5)
        assert widget._target_mic_level == 0.0

    def test_visualizer_palette_contains_required_keys_for_all_states(self, qtbot) -> None:
        widget = JarvisVisualizerWidget()
        qtbot.addWidget(widget)

        for state in VoiceState:
            widget._voice_state = state.value
            pal = widget._get_theme_palette()
            assert "core_color" in pal
            assert "glow_color" in pal
            assert "ring_color" in pal
            assert "meter_color" in pal
            assert "speed_mult" in pal
            assert "spike_amp" in pal

    def test_audio_normalization_utility(self) -> None:
        # Stereo 48kHz float -> 16kHz mono int16
        import struct

        raw_floats = [0.1, -0.1] * 240  # 480 floats = 240 stereo frames at 48kHz
        raw_bytes = struct.pack(f"<{len(raw_floats)}f", *raw_floats)
        norm = normalize_audio_to_16k_mono_pcm16(
            raw_bytes=raw_bytes,
            src_rate=48000,
            channels=2,
            is_float=True,
        )
        assert len(norm) > 0
        # 240 samples downsampled 3x = 80 samples * 2 bytes = 160 bytes
        assert len(norm) == 160
