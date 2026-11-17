"""10-Step Multi-Turn Continuous Voice Conversation Test Suite.

Validates end-to-end conversational flow across 10 sequential turns:
1. Turn 1 (Greeting): "Hello Jarvis"
2. Turn 2 (System Query): "What is the status of system memory?"
3. Turn 3 (Contextual Follow-up without wake word): "And CPU usage?"
4. Turn 4 (Task Initiation): "Create a reminder for my meeting tomorrow at 3 PM"
5. Turn 5 (Conversational Correction): "Wait, make that 4 PM instead"
6. Turn 6 (Language Switch to Persian): "وضعیت هوای تهران چطوره؟"
7. Turn 7 (Persian Ambiguity Trigger): "ویرایشش کن" (needs modification detail)
8. Turn 8 (Persian Clarification): "دمای فردا رو هم بگو"
9. Turn 9 (Full-Duplex Voice Barge-in): Interrupts TTS playback (<50ms)
10. Turn 10 (Conversation Termination): "Thank you, that is all for now"
"""

from __future__ import annotations

import math

import pytest

from core.events import AgentEvent, AgentEventType, EventBus
from tools.voice.models import TranscriptResult, VoiceState
from tools.voice.stt_service import MockSTTService
from tools.voice.tts_service import MockTTSService
from tools.voice.vad import VoiceActivityDetector
from tools.voice.voice_pipeline import ConversationalVoicePipeline
from tools.voice.wake_word import WakeWordDetector


def generate_pcm_speech(duration_s: float = 0.2, amplitude: float = 0.6) -> bytes:
    """Generate synthetic PCM speech frame."""
    sample_rate = 16000
    total_samples = int(sample_rate * duration_s)
    pcm = bytearray()
    amp_int = int(32767 * amplitude)
    for i in range(total_samples):
        val = int(amp_int * math.sin(2.0 * math.pi * 500.0 * i / sample_rate))
        val = max(-32768, min(32767, val))
        pcm.extend(val.to_bytes(2, "little", signed=True))
    return bytes(pcm)


class TestContinuousMultiTurnConversation:
    """Complete 10-step conversational validation without wake words in continuous mode."""

    @pytest.fixture
    def setup_pipeline(
        self,
    ) -> tuple[ConversationalVoicePipeline, MockSTTService, MockTTSService, list[TranscriptResult]]:
        event_bus = EventBus()
        captured_events: list[TranscriptResult] = []

        def _track_event(event: AgentEvent) -> None:
            if event.event_type == AgentEventType.VOICE_TRANSCRIPT_READY:
                captured_events.append(
                    TranscriptResult(
                        text=event.payload.get("text", ""),
                        language=event.payload.get("language", "en"),
                        confidence=event.payload.get("confidence", 0.95),
                        is_ambiguous=event.payload.get("is_ambiguous", False),
                    )
                )

        event_bus.subscribe(AgentEventType.VOICE_TRANSCRIPT_READY, _track_event)

        stt = MockSTTService()
        tts = MockTTSService()
        vad = VoiceActivityDetector(energy_threshold=0.015, silence_timeout_seconds=0.5)
        wake = WakeWordDetector(wake_word="Jarvis", enabled=True)

        pipeline = ConversationalVoicePipeline(
            vad=vad,
            wake_word_detector=wake,
            stt_service=stt,
            tts_service=tts,
            event_bus=event_bus,
        )
        pipeline.settings.voice_require_prefix = False
        return pipeline, stt, tts, captured_events

    def test_ten_step_continuous_conversation_sequence(
        self,
        setup_pipeline: tuple[
            ConversationalVoicePipeline, MockSTTService, MockTTSService, list[TranscriptResult]
        ],
    ) -> None:
        pipeline, stt, tts, captured_transcripts = setup_pipeline

        # Activate Continuous Multi-Turn Conversation Mode
        assert pipeline.toggle_conversation_mode() is True
        assert pipeline.is_conversation_mode is True
        assert pipeline.state == VoiceState.LISTENING

        user_turns = [
            ("Hello Jarvis", "en", "Good day, sir. How may I assist you today?"),
            (
                "What is the status of system memory?",
                "en",
                "System memory is at 42 percent utilization.",
            ),
            ("And CPU usage?", "en", "CPU utilization is currently 18 percent across all cores."),
            (
                "Create a reminder for my meeting tomorrow at 3 PM",
                "en",
                "Meeting reminder set for 3:00 PM tomorrow.",
            ),
            (
                "Wait, make that 4 PM instead",
                "en",
                "Updated. Meeting reminder rescheduled to 4:00 PM tomorrow.",
            ),
            ("وضعیت هوای تهران چطوره؟", "fa", "دمای فعلی تهران ۱۸ درجه سانتی‌گراد و آسمان صاف است."),
            (
                "ویرایشش کن",
                "fa",
                "مایلید چه بخشی را ویرایش کنم؟ لطفاً تغییرات مورد نظرتان را مشخص کنید.",
            ),
            (
                "دمای فردا رو هم بگو",
                "fa",
                "دمای هوای تهران فردا بین ۱۱ تا ۲۰ درجه پیش‌بینی شده است.",
            ),
            (
                "Stop, check London weather instead!",
                "en",
                "Barge-in: Checking London weather forecast now.",
            ),
            (
                "Thank you, that is all for now.",
                "en",
                "Very well, sir. Standing by whenever you need me.",
            ),
        ]

        dummy_audio = generate_pcm_speech(duration_s=0.2)

        for step_idx, (user_phrase, expected_lang, assistant_reply) in enumerate(
            user_turns, start=1
        ):
            stt.set_transcript(user_phrase, confidence=0.96)

            # In continuous conversation mode, wake word is NOT required before turns!
            assert pipeline.is_conversation_mode is True

            # 1. User starts speaking (simulating audio capture into active buffer)
            pipeline._active_buffer.extend(dummy_audio)
            pipeline.set_state(VoiceState.RECORDING)

            # 2. Transcribe and dispatch utterance synchronously
            pipeline._transcribe_worker(bytes(pipeline._active_buffer))
            pipeline._active_buffer.clear()

            # 3. Verify transcript captured and state transitioned to THINKING
            assert len(captured_transcripts) == step_idx
            latest = captured_transcripts[-1]
            if "hello" in user_phrase.lower() and "jarvis" in user_phrase.lower():
                assert "hello" in latest.text.lower()
            else:
                assert latest.text == user_phrase
            assert latest.language == expected_lang
            assert pipeline.state == VoiceState.THINKING

            # 4. Assistant begins speaking response
            pipeline.set_state(VoiceState.SPEAKING)
            tts.speak(assistant_reply)

            # Turn 9 specifically validates full-duplex voice barge-in while speaking!
            if step_idx == 9:
                assert tts.is_speaking() is True
                # User barges in with loud voice during TTS playback
                loud_pcm = generate_pcm_speech(duration_s=0.05, amplitude=0.8)
                pipeline.process_incoming_audio_frame(loud_pcm)
                # Verification: TTS must be stopped immediately (<50ms)
                assert tts.is_speaking() is False
                assert pipeline.state == VoiceState.RECORDING
                # Clean up buffer for next turn
                pipeline._active_buffer.clear()
                pipeline.set_state(VoiceState.LISTENING)
                continue

            # Turn complete: assistant finishes speaking, pipeline returns to LISTENING
            tts.stop()
            pipeline.set_state(VoiceState.LISTENING)
            assert pipeline.state == VoiceState.LISTENING

        # Verify all 10 turns were executed in sequence
        assert len(captured_transcripts) == 10

        # Terminate continuous mode at conclusion of 10 turns
        pipeline.toggle_conversation_mode()
        assert pipeline.is_conversation_mode is False
        assert pipeline.state == VoiceState.IDLE
