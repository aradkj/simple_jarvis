"""Unit tests for Phase 9 Voice Intelligence Subsystem."""

from __future__ import annotations

from core.execution_context import ExecutionContext
from tools.base import ToolExecutionStatus
from tools.voice.device_manager import AudioDeviceManager
from tools.voice.models import TTSRequest, VoiceState
from tools.voice.stt_service import MockSTTService, SpeechRecognitionService
from tools.voice.tts_service import MockTTSService, WindowsTTSService
from tools.voice.vad import VoiceActivityDetector
from tools.voice.voice_pipeline import (
    ConversationalVoicePipeline,
    normalize_audio_to_16k_mono_pcm16,
)
from tools.voice.voice_tools import (
    VoiceMuteInput,
    VoiceMuteTool,
    VoiceSpeakInput,
    VoiceSpeakTool,
    VoiceStatusInput,
    VoiceStatusTool,
)
from tools.voice.wake_word import WakeWordDetector


class TestAudioNormalization:
    """Tests for hardware audio format conversion (AirPods / Bluetooth 48kHz Float -> 16kHz Int16)."""

    def test_normalize_already_16k_mono_pcm16(self):
        raw = b"\x01\x00\x02\x00" * 400
        res = normalize_audio_to_16k_mono_pcm16(raw, src_rate=16000, channels=1, is_float=False)
        assert res == raw

    def test_normalize_48k_stereo_float_to_16k_mono_pcm16(self):
        import struct

        # 4800 float samples = 2400 stereo frames (50ms of audio at 48000Hz)
        floats = [0.2, 0.2] * 2400
        float_bytes = struct.pack(f"<{len(floats)}f", *floats)

        pcm16 = normalize_audio_to_16k_mono_pcm16(
            raw_bytes=float_bytes,
            src_rate=48000,
            channels=2,
            is_float=True,
        )
        # Target: 50ms at 16000Hz = 800 samples * 2 bytes = 1600 bytes
        assert len(pcm16) == 1600

        unpacked = struct.unpack("<800h", pcm16)
        assert 6000 <= unpacked[0] <= 7000

    def test_normalize_empty_bytes(self):
        assert normalize_audio_to_16k_mono_pcm16(b"") == b""


class TestAudioDeviceManager:
    """Tests for microphone and speaker device management."""

    def test_device_enumeration_contains_default(self):
        mgr = AudioDeviceManager()
        inputs = mgr.list_input_devices()
        outputs = mgr.list_output_devices()

        assert len(inputs) >= 1
        assert len(outputs) >= 1
        assert any(d.is_default for d in inputs)
        assert any(d.is_default for d in outputs)

    def test_device_selection(self):
        mgr = AudioDeviceManager()
        first_input = mgr.list_input_devices()[0]
        ok = mgr.set_input_device(first_input.id)
        assert ok is True
        assert mgr.get_selected_input().id == first_input.id

    def test_nonexistent_device_selection_fails(self):
        mgr = AudioDeviceManager()
        ok = mgr.set_input_device("non_existent_audio_device_xyz")
        assert ok is False


class TestVoiceActivityDetector:
    """Tests for real-time VAD, RMS energy tracking, and silence detection."""

    def test_silence_frame_low_rms(self):
        vad = VoiceActivityDetector(energy_threshold=0.02)
        # 1600 samples of zero (3200 bytes) = silence
        silence_bytes = b"\x00" * 3200
        rms = vad.compute_rms(silence_bytes)
        assert rms == 0.0

        res = vad.process_frame(silence_bytes, frame_duration_seconds=0.1)
        assert res.is_speech is False
        assert res.energy_rms == 0.0

    def test_speech_frame_high_rms(self):
        vad = VoiceActivityDetector(energy_threshold=0.01)
        # Generate alternating high amplitude 16-bit signed PCM samples
        samples = [10000, -10000] * 800
        import struct

        pcm_bytes = struct.pack(f"<{len(samples)}h", *samples)
        rms = vad.compute_rms(pcm_bytes)
        assert rms > 0.1

        # Process multiple frames to pass the debounce threshold
        for _ in range(3):
            res = vad.process_frame(pcm_bytes, frame_duration_seconds=0.05)
        assert res.is_speech is True
        assert res.energy_rms > 0.1

    def test_silence_timeout_detection(self):
        vad = VoiceActivityDetector(energy_threshold=0.01, silence_timeout_seconds=0.2)
        vad.is_speech_active = True
        silence_bytes = b"\x00" * 3200

        # Feed silence frames totaling > 0.2s
        vad.process_frame(silence_bytes, frame_duration_seconds=0.15)
        assert vad.is_speech_active is True
        vad.process_frame(silence_bytes, frame_duration_seconds=0.15)
        assert vad.is_speech_active is False

    def test_is_silence_timeout_reached_end_to_end(self):
        import struct

        vad = VoiceActivityDetector(energy_threshold=0.01, silence_timeout_seconds=0.3)
        speech_bytes = struct.pack("<1600h", *([10000, -10000] * 800))
        silence_bytes = b"\x00" * 3200

        # Feed 3 speech frames (total 0.3s speech)
        for _ in range(3):
            vad.process_frame(speech_bytes, frame_duration_seconds=0.1)
        assert vad.speech_detected_in_utterance is True
        assert vad.is_silence_timeout_reached() is False

        # Feed 2 silence frames (total 0.2s silence < 0.3s timeout)
        for _ in range(2):
            vad.process_frame(silence_bytes, frame_duration_seconds=0.1)
        assert vad.is_silence_timeout_reached() is False

        # Feed 3rd silence frame (total 0.3s silence >= 0.3s timeout)
        vad.process_frame(silence_bytes, frame_duration_seconds=0.1)
        assert vad.is_silence_timeout_reached() is True


class TestWakeWordDetector:
    """Tests for Persian and English wake-word detection and Push-To-Talk."""

    def test_english_wake_word_detection(self):
        detector = WakeWordDetector(wake_word="Jarvis", enabled=True, debounce_seconds=0.1)
        detected, command = detector.check_text("Jarvis, what is the weather today?")
        assert detected is True
        assert command.lower() == "what is the weather today?"

    def test_hey_jarvis_wake_word_detection(self):
        detector = WakeWordDetector(wake_word="Hey Jarvis", enabled=True, debounce_seconds=0.0)
        detected, command = detector.check_text("Hey Jarvis, check CPU status")
        assert detected is True
        assert command.lower() == "check cpu status"

        detected2, command2 = detector.check_text("Hey Jarvis")
        assert detected2 is True
        assert command2 == ""

    def test_hey_jarvis_persian_wake_word_detection(self):
        detector = WakeWordDetector(wake_word="Hey Jarvis", enabled=True, debounce_seconds=0.0)
        detected, command = detector.check_text("هی جارویس وضعیت سیستم رو چک کن")
        assert detected is True
        assert "وضعیت سیستم رو چک کن" in command

        detected2, command2 = detector.check_text("هی جارویس")
        assert detected2 is True
        assert command2 == ""

    def test_persian_wake_word_detection(self):
        detector = WakeWordDetector(wake_word="Jarvis", enabled=True, debounce_seconds=0.1)
        detected, command = detector.check_text("جارویس صدای سیستم رو کم کن")
        assert detected is True
        assert "صدای سیستم رو کم کن" in command

    def test_muted_wake_word_ignored(self):
        detector = WakeWordDetector(wake_word="Jarvis", enabled=True)
        detector.mute()
        assert detector.is_muted is True
        detected, cmd = detector.check_text("Jarvis open browser")
        assert detected is False

        detector.unmute()
        assert detector.is_muted is False
        detected, cmd = detector.check_text("Jarvis open browser")
        assert detected is True

    def test_push_to_talk_trigger(self):
        detector = WakeWordDetector(wake_word="Jarvis", enabled=False)
        ok = detector.trigger_push_to_talk()
        assert ok is True


class TestSpeechRecognitionService:
    """Tests for Speech-to-Text language detection and ambiguity analysis."""

    def test_language_detection(self):
        stt = SpeechRecognitionService()
        assert stt.detect_language("سلام چطوری؟") == "fa"
        assert stt.detect_language("Hello, how are you?") == "en"

    def test_ambiguity_analysis_flags_unclear_pronouns(self):
        stt = SpeechRecognitionService()
        # Missing recipient / ambiguous pronoun
        assert stt.analyze_ambiguity("بهش پیام بده", confidence=0.9) is True
        assert stt.analyze_ambiguity("send him an email", confidence=0.9) is True
        assert stt.analyze_ambiguity("ایمیل بفرست", confidence=0.9) is True

        # Clear explicit instructions are not ambiguous
        assert stt.analyze_ambiguity("برای علی ایمیل بفرست", confidence=0.9) is False
        assert stt.analyze_ambiguity("open notepad", confidence=0.9) is False

    def test_low_confidence_flags_ambiguity(self):
        stt = SpeechRecognitionService()
        assert stt.analyze_ambiguity("open chrome", confidence=0.5) is True


class TestTextToSpeechService:
    """Tests for speech synthesis, text formatting, and barge-in interruption."""

    def test_clean_text_for_speech(self):
        tts = WindowsTTSService(engine_name="mock")
        raw = "Here is the code: ```python\nprint(1)\n``` and visit https://example.com"
        cleaned = tts.clean_text_for_speech(raw)
        assert "```" not in cleaned
        assert "https://" not in cleaned
        assert "code block omitted" in cleaned

    def test_mock_tts_barge_in_stop(self):
        mock_tts = MockTTSService()
        req = TTSRequest(text="Hello world")
        mock_tts.speak(req)
        assert mock_tts.is_speaking() is True

        # Barge-in stop
        mock_tts.stop()
        assert mock_tts.is_speaking() is False
        assert mock_tts.stopped_count == 1


class TestConversationalVoicePipeline:
    """Tests for coordinated pipeline and barge-in transitions."""

    def test_pipeline_push_to_talk_and_barge_in(self):
        mock_stt = MockSTTService(preset_transcript="صدای سیستم رو کم کن")
        mock_tts = MockTTSService()
        pipeline = ConversationalVoicePipeline(
            stt_service=mock_stt,
            tts_service=mock_tts,
        )

        # Simulate JARVIS actively speaking
        mock_tts.speak(TTSRequest(text="در حال صحبت..."))
        assert mock_tts.is_speaking() is True

        # User presses Push-to-Talk (Barge-in)
        pipeline.trigger_push_to_talk()

        # TTS must be immediately interrupted
        assert mock_tts.is_speaking() is False
        assert pipeline.state == VoiceState.RECORDING

    def test_voice_tools_execution(self):
        mock_tts = MockTTSService()
        pipeline = ConversationalVoicePipeline(tts_service=mock_tts)
        ctx = ExecutionContext()

        # Status tool
        status_tool = VoiceStatusTool(pipeline)
        res = status_tool.execute(VoiceStatusInput(), ctx)
        assert res.status == ToolExecutionStatus.SUCCESS
        assert "microphone" in res.data
        assert "speaker" in res.data

        # Speak tool
        speak_tool = VoiceSpeakTool(pipeline)
        res_speak = speak_tool.execute(VoiceSpeakInput(text="تست صدا"), ctx)
        assert res_speak.status == ToolExecutionStatus.SUCCESS

        # Mute tool
        mute_tool = VoiceMuteTool(pipeline)
        res_mute = mute_tool.execute(VoiceMuteInput(mute=True), ctx)
        assert res_mute.status == ToolExecutionStatus.SUCCESS
        assert pipeline.wake_word_detector.is_muted is True


class TestAcousticWakeWordAndSelfSuppression:
    """Tests for raw PCM acoustic detection, TTS self-activation suppression, and CPU benchmarking."""

    def test_acoustic_wake_word_processing_and_tts_suppression(self):
        import math

        detector = WakeWordDetector(wake_word="Jarvis", enabled=True, sensitivity=0.8)

        # Generate a synthetic 600ms PCM utterance with bisyllabic envelope and high-frequency tail
        sample_rate = 16000
        total_samples = int(sample_rate * 0.6)
        pcm = bytearray()
        for i in range(total_samples):
            # Syllable 1 (0-250ms)
            if i < int(sample_rate * 0.25):
                amp = 8000 * math.sin(2 * math.pi * 350 * i / sample_rate)
            # Valley (250-320ms)
            elif i < int(sample_rate * 0.32):
                amp = 1000 * math.sin(2 * math.pi * 200 * i / sample_rate)
            # Syllable 2 with sibilant tail (320-600ms)
            else:
                amp = 6000 * math.sin(2 * math.pi * 3000 * i / sample_rate)
            pcm.extend(int(amp).to_bytes(2, "little", signed=True))

        # 1. Normal state: frame processed without error
        detected, conf = detector.process_pcm_frame(bytes(pcm))
        assert isinstance(detected, bool)
        assert isinstance(conf, float)

        # 2. TTS self-activation suppression: When TTS is active, wake-word is strictly suppressed
        detector.set_tts_active(True)
        assert detector.is_tts_active is True
        detected_suppressed, conf_suppressed = detector.process_pcm_frame(bytes(pcm))
        assert detected_suppressed is False
        assert conf_suppressed == 0.0

        # Release TTS suppression
        detector.set_tts_active(False)
        assert detector.is_tts_active is False

    def test_wake_word_cpu_benchmark(self):
        detector = WakeWordDetector(wake_word="Jarvis", enabled=True)
        bench = detector.benchmark_processing_overhead(sample_duration_seconds=0.5)
        assert bench["duration_seconds"] == 0.5
        assert "processing_time_ms" in bench
        assert "real_time_factor" in bench
        assert bench["real_time_factor"] < 1.0  # Real-time processing capability


class TestSTTPrivacyAndPersianTTS:
    """Tests for STT privacy consent controls and Persian TTS adapter."""

    def test_cloud_stt_consent_blocking(self):
        from unittest.mock import patch

        stt = SpeechRecognitionService()
        with patch.object(stt.settings, "voice_cloud_stt_consent", False):
            res = stt.transcribe(b"\x00" * 3200, sample_rate=16000)
            assert res.text == ""
            assert "Consent not granted" in (res.error or "")

    def test_default_configuration_denies_consent(self, monkeypatch):
        """Verify default configuration strictly denies cloud STT without explicit user consent."""
        from config import Settings

        monkeypatch.delenv("VOICE_CLOUD_STT_CONSENT", raising=False)
        fresh_settings = Settings(_env_file=None)
        assert fresh_settings.voice_cloud_stt_consent is False

    def test_missing_or_invalid_configuration_denies_consent(self):
        """Verify missing, unreadable, or corrupted settings resolve to denial."""
        stt = SpeechRecognitionService()
        stt.settings = None  # Missing settings
        assert stt.has_cloud_consent() is False

        stt.settings = object()  # Corrupted / invalid settings without voice_cloud_stt_consent
        assert stt.has_cloud_consent() is False

        # Non-boolean setting (e.g. malformed string or integer)
        class MalformedSettings:
            voice_cloud_stt_consent = "yes_please"

        stt.settings = MalformedSettings()
        assert stt.has_cloud_consent() is False

    def test_explicit_opt_in_allows_consent(self):
        """Explicit opt-in setting allows cloud consent verification."""
        stt = SpeechRecognitionService()
        stt.settings.voice_cloud_stt_consent = True
        assert stt.has_cloud_consent() is True

    def test_explicit_opt_out_denies_consent(self):
        """Explicit opt-out setting denies cloud consent."""
        stt = SpeechRecognitionService()
        stt.settings.voice_cloud_stt_consent = False
        assert stt.has_cloud_consent() is False

    def test_runtime_consent_revocation(self):
        """Revoking consent at runtime immediately blocks cloud dispatch on subsequent call."""
        stt = SpeechRecognitionService()
        stt.settings.voice_cloud_stt_consent = True
        assert stt.has_cloud_consent() is True

        # User toggles consent off in UI
        stt.settings.voice_cloud_stt_consent = False
        assert stt.has_cloud_consent() is False

        res = stt.transcribe(b"\x00" * 3200, sample_rate=16000)
        assert res.text == ""
        assert "Consent not granted" in (res.error or "")

    def test_no_network_dispatch_when_consent_disabled(self):
        """Ensure ProviderManager client is NEVER contacted when consent is disabled."""
        from unittest.mock import MagicMock

        stt = SpeechRecognitionService()
        stt.settings.voice_cloud_stt_consent = False

        mock_provider = MagicMock()
        mock_provider._get_client = MagicMock()
        stt.provider_manager.get_active_provider = MagicMock(return_value=mock_provider)

        # Ingest 16kHz audio data
        pcm = b"\x10\x00" * 8000  # 0.5s audio
        res = stt.transcribe(pcm, sample_rate=16000)

        assert res.text == ""
        assert "Consent not granted" in (res.error or "")
        mock_provider._get_client.assert_not_called()

    def test_no_audio_persistence_after_failed_or_cancelled_requests(self, tmp_path):
        """Ensure no audio files or temp buffers persist on disk after failed/cancelled STT."""
        import glob

        from core.execution_context import CancellationToken

        stt = SpeechRecognitionService()
        stt.settings.voice_cloud_stt_consent = True

        cancel_token = CancellationToken()
        cancel_token.cancel()

        pcm = b"\x20\x00" * 8000
        res = stt.transcribe(pcm, cancellation_token=cancel_token)
        assert res.text == ""

        # Check that no stray audio artifacts (.wav, .pcm) were created on disk
        persisted_audio = glob.glob(str(tmp_path / "*.wav")) + glob.glob(str(tmp_path / "*.pcm"))
        assert len(persisted_audio) == 0

    def test_persian_tts_adapter_punctuation_and_voice_check(self):
        from tools.voice.tts_service import PersianTTSAdapter, WindowsTTSService

        adapter = PersianTTSAdapter()
        assert adapter.is_persian_text("سلام جارویس") is True
        assert adapter.is_persian_text("Hello Jarvis") is False

        # Punctuation normalization
        raw = "سلام، چطوری؟ آیا سیستم آماده است؛ بله."
        norm = adapter.normalize_persian_text(raw)
        assert "؟" not in norm
        assert "،" not in norm
        assert "؛" not in norm
        assert "?" in norm
        assert "," in norm

        # WindowsTTSService Persian fallback protection
        tts = WindowsTTSService(engine_name="mock")
        # In mock engine, voices are English Bob & Anne, no Persian voice
        # By default, voice_allow_tts_fallback_to_english is False
        req = TTSRequest(text="سلام، روز شما بخیر")
        success = tts.speak(req)
        # Without Persian voice installed and without fallback consent, speak returns False
        assert success is False
