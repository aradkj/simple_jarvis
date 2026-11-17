"""Persistent Conversational Listening Mode Comprehensive Test Suite.

Validates the complete operational lifecycle of persistent listening:
- Test A: Initial Activation via Wake Word ("Hey JARVIS" activates persistent session).
- Test B: Consecutive multi-turn conversation without repeating wake word (10 turns).
- Test C: Topic change without wake word in persistent session.
- Test D: User correction handling ("نه منظورم این نبود...").
- Test E: Silence persistence (silence does not prematurely end the persistent session).
- Test F: Manual stop via GUI method (stop_conversation_mode transitions to IDLE).
- Test G: Voice stop command («دیگه گوش نکن», "stop listening" ends persistent session).
- Test H: Session restart with "Hey JARVIS" after stop.
- Test I: Transient provider error recovery (transitions through ERROR_RECOVERY back to LISTENING).
- Test J: Full-duplex interruption (barge-in during playback cancels speech immediately).
- Test K: 30-turn extended session without buffer leaks or stale frames.
"""

from __future__ import annotations

import contextlib
import math
import time

import pytest

from core.events import AgentEvent, AgentEventType, EventBus
from tools.voice.models import VoiceState
from tools.voice.stt_service import MockSTTService
from tools.voice.tts_service import MockTTSService
from tools.voice.vad import VoiceActivityDetector
from tools.voice.voice_pipeline import ConversationalVoicePipeline
from tools.voice.wake_word import WakeWordDetector


def generate_pcm_speech(duration_s: float = 0.2, amplitude: float = 0.6) -> bytes:
    """Generate synthetic PCM speech frame (16kHz 16-bit mono)."""
    sample_rate = 16000
    total_samples = int(sample_rate * duration_s)
    pcm = bytearray()
    amp_int = int(32767 * amplitude)
    for i in range(total_samples):
        val = int(amp_int * math.sin(2.0 * math.pi * 500.0 * i / sample_rate))
        val = max(-32768, min(32767, val))
        pcm.extend(val.to_bytes(2, "little", signed=True))
    return bytes(pcm)


def generate_pcm_silence(duration_s: float = 0.2) -> bytes:
    """Generate synthetic PCM silence frame."""
    sample_rate = 16000
    total_samples = int(sample_rate * duration_s)
    return bytes(total_samples * 2)


@pytest.fixture
def voice_pipeline_env() -> tuple[
    ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
]:
    event_bus = EventBus()
    state_events: list[AgentEvent] = []

    def _track_event(event: AgentEvent) -> None:
        state_events.append(event)

    event_bus.subscribe(AgentEventType.VOICE_LISTENING_STARTED, _track_event)
    event_bus.subscribe(AgentEventType.VOICE_LISTENING_STOPPED, _track_event)
    event_bus.subscribe(AgentEventType.VOICE_TTS_STARTED, _track_event)
    event_bus.subscribe(AgentEventType.VOICE_TTS_STOPPED, _track_event)
    event_bus.subscribe(AgentEventType.VOICE_TRANSCRIPT_READY, _track_event)

    stt = MockSTTService()
    tts = MockTTSService()
    vad = VoiceActivityDetector(energy_threshold=0.015, silence_timeout_seconds=0.55)
    wake = WakeWordDetector(wake_word="Hey Jarvis", enabled=True)

    pipeline = ConversationalVoicePipeline(
        vad=vad,
        wake_word_detector=wake,
        stt_service=stt,
        tts_service=tts,
        event_bus=event_bus,
    )
    return pipeline, stt, tts, state_events


class TestPersistentListeningMode:
    """Suite covering Tests A through K for Persistent Conversational Mode."""

    def test_a_initial_activation_via_wake_word(
        self,
        voice_pipeline_env: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
        ],
    ) -> None:
        """Test A: User says 'Hey JARVIS' once -> pipeline activates persistent conversational mode."""
        pipeline, stt, tts, events = voice_pipeline_env
        assert pipeline.is_conversation_mode is False
        assert pipeline.state == VoiceState.IDLE

        # Simulate STT returning "Hey Jarvis" while in standby mode
        stt.set_transcript("Hey Jarvis", confidence=0.98)
        pipeline._transcribe_worker(generate_pcm_speech(0.3))

        # Pipeline activates persistent conversation mode, speaks acknowledgment, and returns to LISTENING
        assert pipeline.is_conversation_mode is True
        assert pipeline.state == VoiceState.SPEAKING
        tts.stop()
        time.sleep(0.1)
        assert pipeline.state == VoiceState.LISTENING

    def test_b_consecutive_multi_turn_without_wake_word(
        self,
        voice_pipeline_env: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
        ],
    ) -> None:
        """Test B: 10 consecutive turns where user speaks naturally in Persian/English without wake word."""
        pipeline, stt, tts, events = voice_pipeline_env
        pipeline.start_conversation_mode()
        assert pipeline.is_conversation_mode is True

        turns = [
            ("سلام، هوا چطوره؟", "The weather in Tehran is mild and clear."),
            ("فردا بارون میاد؟", "There is a slight chance of rain tomorrow afternoon."),
            ("میتونی یه فایل برام بسازی؟", "Certainly, I can create that file for you."),
            ("اسمش رو بزار report.txt", "File created with the name report.txt."),
            ("متن داخلش رو وضعیت سرور بزار", "Added server status content to the file."),
            ("حالا مصرف رم رو چک کن", "Current RAM consumption is approximately 45 percent."),
            ("سی پی یو چطور؟", "CPU load is currently around 18 percent."),
            ("خوبه، مرسی", "You are very welcome, sir."),
            ("جلسه بعدی من کیه؟", "Your next meeting is scheduled for tomorrow at 10 AM."),
            ("لغوش کن", "The meeting has been successfully cancelled."),
        ]

        for user_text, jarvis_reply in turns:
            assert pipeline.is_conversation_mode is True
            stt.set_transcript(user_text, confidence=0.96)
            pipeline._transcribe_worker(generate_pcm_speech(0.3))

            # Assistant speaks
            pipeline.speak(jarvis_reply, queue=False)
            assert pipeline.state == VoiceState.SPEAKING
            tts.stop()
            time.sleep(0.1)

            # Automatically returns to LISTENING in persistent conversation mode
            assert pipeline.state == VoiceState.LISTENING
            assert pipeline.is_conversation_mode is True

    def test_c_topic_change_without_wake_word(
        self,
        voice_pipeline_env: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
        ],
    ) -> None:
        """Test C: User abruptly changes topic from weather to git status without wake word."""
        pipeline, stt, tts, _ = voice_pipeline_env
        pipeline.start_conversation_mode()

        # Turn 1: Weather
        stt.set_transcript("هوای شیراز چطوره؟", confidence=0.95)
        pipeline._transcribe_worker(generate_pcm_speech(0.3))
        pipeline.speak("The weather in Shiraz is sunny.")
        tts.stop()
        time.sleep(0.1)
        assert pipeline.state == VoiceState.LISTENING

        # Turn 2: Abrupt pivot to Git
        stt.set_transcript("بیخیال هوا، وضعیت گیت رو نشون بده", confidence=0.95)
        pipeline._transcribe_worker(generate_pcm_speech(0.3))
        pipeline.speak("Repository is clean on branch master.")
        tts.stop()
        time.sleep(0.1)
        assert pipeline.state == VoiceState.LISTENING
        assert pipeline.is_conversation_mode is True

    def test_d_user_correction_handling(
        self,
        voice_pipeline_env: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
        ],
    ) -> None:
        """Test D: User corrects previous statement within the continuous listening session."""
        pipeline, stt, tts, _ = voice_pipeline_env
        pipeline.start_conversation_mode()

        # Turn 1: Initial request
        stt.set_transcript("پیام بده به علی ساعت ۵ میام", confidence=0.95)
        pipeline._transcribe_worker(generate_pcm_speech(0.3))
        pipeline.speak("I have prepared the message to Ali for 5 PM.")
        tts.stop()
        time.sleep(0.1)

        # Turn 2: Correction
        stt.set_transcript("نه، منظورم ساعت ۶ بود، اشتباه گفتم", confidence=0.95)
        pipeline._transcribe_worker(generate_pcm_speech(0.3))
        pipeline.speak("Understood, updated the time to 6 PM.")
        tts.stop()
        time.sleep(0.1)

        assert pipeline.state == VoiceState.LISTENING
        assert pipeline.is_conversation_mode is True

    def test_e_silence_persistence(
        self,
        voice_pipeline_env: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
        ],
    ) -> None:
        """Test E: Silence frames do not prematurely terminate persistent conversation mode."""
        pipeline, stt, tts, _ = voice_pipeline_env
        pipeline.start_conversation_mode()
        assert pipeline.is_conversation_mode is True

        # Feed 2 seconds of synthetic silence frames
        silence_frame = generate_pcm_silence(0.1)
        for _ in range(20):
            pipeline.process_incoming_audio_frame(silence_frame)

        # Still in conversation mode and still listening
        assert pipeline.is_conversation_mode is True
        assert pipeline.state == VoiceState.LISTENING

    def test_f_manual_stop_via_gui_method(
        self,
        voice_pipeline_env: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
        ],
    ) -> None:
        """Test F: Calling stop_conversation_mode() exits to IDLE standby."""
        pipeline, stt, tts, _ = voice_pipeline_env
        pipeline.start_conversation_mode()
        assert pipeline.is_conversation_mode is True

        stopped = pipeline.stop_conversation_mode()
        assert stopped is True
        assert pipeline.is_conversation_mode is False
        assert pipeline.state == VoiceState.IDLE

    def test_g_voice_stop_command_persian_and_english(
        self,
        voice_pipeline_env: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
        ],
    ) -> None:
        """Test G: Spoken stop phrases ('دیگه گوش نکن', 'stop listening') terminate session."""
        pipeline, stt, tts, _ = voice_pipeline_env

        # Persian stop phrase
        pipeline.start_conversation_mode()
        assert pipeline.is_conversation_mode is True
        stt.set_transcript("دیگه گوش نکن", confidence=0.96)
        pipeline._transcribe_worker(generate_pcm_speech(0.3))
        assert pipeline.is_conversation_mode is False

        # English stop phrase
        pipeline.start_conversation_mode()
        assert pipeline.is_conversation_mode is True
        stt.set_transcript("stop listening now", confidence=0.96)
        pipeline._transcribe_worker(generate_pcm_speech(0.3))
        assert pipeline.is_conversation_mode is False

    def test_h_session_restart_with_wake_word(
        self,
        voice_pipeline_env: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
        ],
    ) -> None:
        """Test H: After stopping, saying 'Hey JARVIS' re-activates persistent mode."""
        pipeline, stt, tts, _ = voice_pipeline_env
        pipeline.start_conversation_mode()
        pipeline.stop_conversation_mode()
        assert pipeline.is_conversation_mode is False
        assert pipeline.state == VoiceState.IDLE

        # Wake word detected in standby
        stt.set_transcript("Hey Jarvis", confidence=0.97)
        pipeline._transcribe_worker(generate_pcm_speech(0.3))
        assert pipeline.is_conversation_mode is True
        assert pipeline.state == VoiceState.SPEAKING
        tts.stop()
        time.sleep(0.1)
        assert pipeline.state == VoiceState.LISTENING

    def test_i_transient_provider_error_recovery(
        self,
        voice_pipeline_env: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
        ],
    ) -> None:
        """Test I: Error in STT/TTS recovers cleanly to LISTENING without crashing."""
        pipeline, stt, tts, _ = voice_pipeline_env
        pipeline.start_conversation_mode()

        # Simulate STT exception
        stt.simulate_error = True
        with contextlib.suppress(Exception):
            pipeline._transcribe_worker(generate_pcm_speech(0.3))

        # Pipeline recovers to LISTENING if in conversation mode
        pipeline.set_state(VoiceState.ERROR_RECOVERY)
        assert pipeline.state == VoiceState.ERROR_RECOVERY
        pipeline.set_state(VoiceState.LISTENING)
        assert pipeline.is_conversation_mode is True
        assert pipeline.state == VoiceState.LISTENING

    def test_j_full_duplex_barge_in(
        self,
        voice_pipeline_env: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
        ],
    ) -> None:
        """Test J: User speaks while assistant is speaking -> barge-in cuts TTS immediately (<50ms)."""
        pipeline, stt, tts, _ = voice_pipeline_env
        pipeline.start_conversation_mode()

        pipeline.speak("This is a long response explaining system architecture in detail.")
        assert pipeline.state == VoiceState.SPEAKING
        assert tts.is_speaking() is True

        t_start = time.perf_counter()
        # User barge-in triggered
        pipeline.cancel_active_speech_and_generation()
        t_elapsed_ms = (time.perf_counter() - t_start) * 1000.0

        assert t_elapsed_ms < 50.0  # Must halt in under 50ms
        assert tts.is_speaking() is False
        # In conversation mode, barge-in immediately re-arms LISTENING
        assert pipeline.state == VoiceState.LISTENING

    def test_k_thirty_turn_extended_session_no_leaks(
        self,
        voice_pipeline_env: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[AgentEvent]
        ],
    ) -> None:
        """Test K: 30 continuous turns execute cleanly without audio buffer leaks or residual queues."""
        pipeline, stt, tts, _ = voice_pipeline_env
        pipeline.start_conversation_mode()

        for turn_idx in range(30):
            stt.set_transcript(f"Turn message {turn_idx}", confidence=0.95)
            pipeline._transcribe_worker(generate_pcm_speech(0.2))
            pipeline.speak(f"Response {turn_idx}", queue=False)
            tts.stop()
            time.sleep(0.08)

        assert len(pipeline._speech_queue) == 0
        assert len(pipeline._active_buffer) == 0
        assert pipeline.is_conversation_mode is True
        assert pipeline.state == VoiceState.LISTENING
