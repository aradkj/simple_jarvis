"""Verification tests for Wake Word detection, Speaker Echo Suppression,
and Full-Sentence Conversational Voice Speech.
"""

from __future__ import annotations

from tools.voice.models import TTSRequest, VoiceState
from tools.voice.tts_service import MockTTSService
from tools.voice.voice_pipeline import ConversationalVoicePipeline, clean_text_for_speech
from tools.voice.wake_word import WakeWordDetector


class TestWakeWordAndEchoRemediation:
    """Validate fixes for wake word triggers, echo suppression, and full speech responses."""

    def test_wake_word_text_variations_and_punctuation(self) -> None:
        """Verify that wake word is recognized with various punctuation without getting blocked."""
        ww = WakeWordDetector(wake_word="Hey Jarvis", enabled=True)

        # Wake word alone with punctuation
        for phrase in [
            "Hey Jarvis",
            "Hey, Jarvis.",
            "hey jarvis!",
            "هی جارویس",
            "سلام جارویس.",
            "Hello Jarvis!",
        ]:
            detected, cmd = ww.check_text(phrase)
            assert detected is True, f"Failed on '{phrase}'"
            assert cmd == "", (
                f"Expected empty command for wake-word alone on '{phrase}', got '{cmd}'"
            )

        # Wake word with command, preserving trailing question mark
        detected, cmd = ww.check_text("Hey Jarvis, what is my CPU temperature?")
        assert detected is True
        assert cmd == "what is my CPU temperature?"

        # Persian wake word with command
        detected, cmd = ww.check_text("سلام جارویس وضعیت پردازنده چطوره؟")
        assert detected is True
        assert cmd == "وضعیت پردازنده چطوره؟"

    def test_speaker_echo_does_not_abort_tts(self) -> None:
        """Verify that speaker audio leakage (RMS ~0.06) does NOT trigger false barge-in."""
        mock_tts = MockTTSService()
        pipeline = ConversationalVoicePipeline(tts_service=mock_tts)

        mock_tts.speak(
            TTSRequest(text="JARVIS is speaking a complete, uncut response to the user.")
        )
        assert mock_tts.is_speaking() is True
        pipeline.set_state(VoiceState.SPEAKING)

        # Simulate frames of loud laptop speaker echo (RMS ~0.06 to 0.30)
        # 16-bit PCM samples with amplitude 2000 and 8000 (RMS up to ~0.25)
        for amp in (2000, 8000, 10000):
            echo_frame = amp.to_bytes(2, "little", signed=True) * 800
            for _ in range(5):
                pipeline.process_incoming_audio_frame(echo_frame)
                # TTS must remain speaking without interruption!
                assert mock_tts.is_speaking() is True

    def test_loud_user_voice_does_trigger_barge_in(self) -> None:
        """Verify that loud user interruption (amplitude 0.7, RMS > 0.20) halts TTS cleanly."""
        mock_tts = MockTTSService()
        pipeline = ConversationalVoicePipeline(tts_service=mock_tts)

        mock_tts.speak(TTSRequest(text="JARVIS is speaking..."))
        pipeline.set_state(VoiceState.SPEAKING)
        assert mock_tts.is_speaking() is True

        # Loud user voice (amplitude ~23000, RMS ~ 0.70)
        loud_frame = (23000).to_bytes(2, "little", signed=True) * 800
        pipeline.process_incoming_audio_frame(loud_frame)

        # Must halt speech immediately (<50ms)
        assert mock_tts.is_speaking() is False
        assert pipeline.state == VoiceState.RECORDING

    def test_wake_word_acknowledgment_does_not_record_own_voice(self) -> None:
        """Verify that acknowledging 'Yes, sir?' does not start recording speaker playback."""
        mock_tts = MockTTSService()
        pipeline = ConversationalVoicePipeline(tts_service=mock_tts)

        pipeline._handle_wake_word_acknowledgment("en")
        # While acknowledging, recording must be False
        assert pipeline._is_recording is False
        assert pipeline._is_wake_acknowledging is True
        assert mock_tts.is_speaking() is True

    def test_clean_text_for_speech_persian_and_english(self) -> None:
        """Verify that clean_text_for_speech strips formatting while preserving full sentences."""
        markdown_fa = """### وضعیت سیستم
حافظه رم در حال حاضر **۴۲ درصد** استفاده می‌شود.
```python
print("debug")
```
برای مشاهده جزئیات به لینک https://system.local مراجعه فرمایید."""

        cleaned_fa = clean_text_for_speech(markdown_fa)
        assert "وضعیت سیستم" in cleaned_fa
        assert "حافظه رم در حال حاضر ۴۲ درصد استفاده می‌شود." in cleaned_fa
        assert "print" not in cleaned_fa
        assert "https://" not in cleaned_fa
        assert "###" not in cleaned_fa

        markdown_en = """**Certainly, sir.**
The test suite has completed:
- `main.py` verified
- *789* tests passed."""

        cleaned_en = clean_text_for_speech(markdown_en)
        assert "Certainly, sir." in cleaned_en
        assert "The test suite has completed:" in cleaned_en
        assert "main.py verified" in cleaned_en
        assert "789 tests passed." in cleaned_en
        assert "**" not in cleaned_en
        assert "`" not in cleaned_en
