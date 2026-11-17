"""Unit tests for Voice Prefix Enforcement (only process speech starting with 'Jarvis')."""

from unittest.mock import MagicMock

import pytest

from tools.voice.stt_service import TranscriptResult
from tools.voice.voice_pipeline import ConversationalVoicePipeline
from tools.voice.wake_word import WakeWordDetector, check_starts_with_wake_word


class TestWakeWordPrefixDetection:
    """Test prefix pattern matching across English and Persian variations."""

    @pytest.mark.parametrize(
        "utterance,expected_match,expected_stripped",
        [
            ("Jarvis what is the time", True, "what is the time"),
            ("Jarvis, what is the time?", True, "what is the time?"),
            ("Hey Jarvis open visual studio code", True, "open visual studio code"),
            ("Hi Jarvis, can you hear me?", True, "can you hear me?"),
            ("Hello Jarvis how are you", True, "how are you"),
            ("OK Jarvis create a folder on desktop", True, "create a folder on desktop"),
            ("Okay Jarvis, check my calendar", True, "check my calendar"),
            ("jarvis what is the date", True, "what is the date"),
            ("JARVIS reboot system", True, "reboot system"),
            # Persian prefixes
            ("جارویس وضعیت آب و هوا چطوره", True, "وضعیت آب و هوا چطوره"),
            ("جارویس، یک پوشه بساز", True, "یک پوشه بساز"),
            ("هی جارویس پروژه من رو باز کن", True, "پروژه من رو باز کن"),
            ("سلام جارویس چطوری", True, "چطوری"),
            ("سلام، جارویس امروز چه خبر", True, "امروز چه خبر"),
            ("اوکی جارویس فایل رو پیدا کن", True, "فایل رو پیدا کن"),
            # Wake word spoken alone
            ("Jarvis", True, ""),
            ("Hey Jarvis", True, ""),
            ("jarvis,", True, ""),
            ("جارویس", True, ""),
            ("سلام جارویس", True, ""),
            # Non-matching utterances (must NOT match)
            ("What time is it Jarvis?", False, "What time is it Jarvis?"),
            ("I was talking to Jarvis yesterday", False, "I was talking to Jarvis yesterday"),
            ("سلام علی حالت چطوره", False, "سلام علی حالت چطوره"),
            (
                "This is just background conversation about coding",
                False,
                "This is just background conversation about coding",
            ),
            ("can you help me please", False, "can you help me please"),
            ("", False, ""),
            ("   ", False, ""),
        ],
    )
    def test_prefix_detection_and_stripping(
        self, utterance: str, expected_match: bool, expected_stripped: str
    ) -> None:
        is_match, stripped = check_starts_with_wake_word(utterance)
        assert is_match == expected_match
        assert stripped == expected_stripped


class TestVoicePipelinePrefixEnforcement:
    """Test ConversationalVoicePipeline utterance filtering based on prefix policy."""

    @pytest.fixture
    def mock_pipeline(self) -> ConversationalVoicePipeline:
        pipeline = ConversationalVoicePipeline()
        pipeline.settings.voice_require_prefix = True
        pipeline.wake_word_detector = WakeWordDetector()
        pipeline.stt_service = MagicMock()
        pipeline.tts_service = MagicMock()
        pipeline._on_command_callback = MagicMock()
        pipeline.speak = MagicMock()
        return pipeline

    def test_non_prefix_utterance_is_ignored(
        self, mock_pipeline: ConversationalVoicePipeline
    ) -> None:
        """Utterances not starting with 'Jarvis' must be ignored without calling callback or speak."""
        mock_pipeline.stt_service.transcribe.return_value = TranscriptResult(
            text="What is the weather outside?",
            language="en",
            confidence=0.95,
        )

        mock_pipeline._transcribe_worker(b"dummy_audio_bytes", is_ptt=False)

        mock_pipeline._on_command_callback.assert_not_called()
        mock_pipeline.speak.assert_not_called()

    def test_persian_non_prefix_utterance_is_ignored(
        self, mock_pipeline: ConversationalVoicePipeline
    ) -> None:
        """Persian speech not addressing Jarvis must be ignored."""
        mock_pipeline.stt_service.transcribe.return_value = TranscriptResult(
            text="سلام حالت چطوره داداش",
            language="fa",
            confidence=0.95,
        )

        mock_pipeline._transcribe_worker(b"dummy_audio_bytes", is_ptt=False)

        mock_pipeline._on_command_callback.assert_not_called()
        mock_pipeline.speak.assert_not_called()

    def test_prefix_utterance_strips_wake_word_and_dispatches_clean_command(
        self, mock_pipeline: ConversationalVoicePipeline
    ) -> None:
        """Utterance starting with 'Jarvis' must strip prefix and pass clean command to callback."""
        mock_pipeline.stt_service.transcribe.return_value = TranscriptResult(
            text="Jarvis, what time is it?",
            language="en",
            confidence=0.98,
        )

        mock_pipeline._transcribe_worker(b"dummy_audio_bytes", is_ptt=False)

        mock_pipeline._on_command_callback.assert_called_once()
        cmd_text = mock_pipeline._on_command_callback.call_args[0][0]
        assert cmd_text == "what time is it?"

    def test_persian_prefix_utterance_dispatches_clean_command(
        self, mock_pipeline: ConversationalVoicePipeline
    ) -> None:
        """Persian utterance starting with 'جارویس' strips prefix and dispatches clean command."""
        mock_pipeline.stt_service.transcribe.return_value = TranscriptResult(
            text="جارویس وضعیت پروژه رو بگو",
            language="fa",
            confidence=0.98,
        )

        mock_pipeline._transcribe_worker(b"dummy_audio_bytes", is_ptt=False)

        mock_pipeline._on_command_callback.assert_called_once()
        cmd_text = mock_pipeline._on_command_callback.call_args[0][0]
        assert cmd_text == "وضعیت پروژه رو بگو"

    def test_wake_word_spoken_alone_acknowledges_verbally(
        self, mock_pipeline: ConversationalVoicePipeline
    ) -> None:
        """Saying only 'Jarvis' or 'Hey Jarvis' verbally acknowledges readiness without dispatching command."""
        mock_pipeline.stt_service.transcribe.return_value = TranscriptResult(
            text="Hey Jarvis",
            language="en",
            confidence=0.99,
        )

        mock_pipeline._transcribe_worker(b"dummy_audio_bytes", is_ptt=False)

        mock_pipeline._on_command_callback.assert_not_called()
        mock_pipeline.speak.assert_called_once()
        spoken = mock_pipeline.speak.call_args[0][0]
        assert "Yes, sir? I am listening." in spoken

    def test_persian_wake_word_alone_acknowledges_in_persian(
        self, mock_pipeline: ConversationalVoicePipeline
    ) -> None:
        """Saying only 'جارویس' verbally acknowledges in Persian."""
        mock_pipeline.stt_service.transcribe.return_value = TranscriptResult(
            text="سلام جارویس",
            language="fa",
            confidence=0.99,
        )

        mock_pipeline._transcribe_worker(b"dummy_audio_bytes", is_ptt=False)

        mock_pipeline._on_command_callback.assert_not_called()
        mock_pipeline.speak.assert_called_once()
        spoken = mock_pipeline.speak.call_args[0][0]
        assert "بله، در خدمتم." in spoken

    def test_ptt_button_bypasses_prefix_requirement(
        self, mock_pipeline: ConversationalVoicePipeline
    ) -> None:
        """Push-to-Talk (manual microphone click) allows speaking commands directly without saying 'Jarvis'."""
        mock_pipeline.stt_service.transcribe.return_value = TranscriptResult(
            text="Set volume to 50 percent",
            language="en",
            confidence=0.95,
        )

        # is_ptt=True
        mock_pipeline._transcribe_worker(b"dummy_audio_bytes", is_ptt=True)

        mock_pipeline._on_command_callback.assert_called_once()
        cmd_text = mock_pipeline._on_command_callback.call_args[0][0]
        assert cmd_text == "Set volume to 50 percent"
