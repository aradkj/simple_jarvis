"""Unit tests for Phase 10 ElevenLabs Neural Voice Integration, Streaming, and Language Policy."""

from __future__ import annotations

import io
import json
import wave
from unittest.mock import MagicMock, patch

from pydantic import SecretStr

from config import Settings
from core.execution_context import CancellationToken
from core.personality import JarvisPersonalityEngine, ResponseLanguagePolicy
from infrastructure.credential_store import CredentialStore
from tools.voice.elevenlabs_provider import (
    DEFAULT_BRITISH_VOICE_ID,
    ElevenLabsTTSProvider,
    ElevenLabsTTSService,
    SentenceStreamingBuffer,
)
from tools.voice.models import TTSRequest
from tools.voice.tts_service import BaseTTSService, create_tts_service


class TestSentenceStreamingBuffer:
    """Verifies incremental text buffer segmentation for smooth TTS streaming."""

    def test_sentence_streaming_buffer_basic(self) -> None:
        buffer = SentenceStreamingBuffer()
        # Add chunk without sentence terminator
        res1 = buffer.add_chunk("Good day, sir")
        assert res1 == []

        # Add punctuation and whitespace
        res2 = buffer.add_chunk(". The system is operational! Are we ready?")
        assert len(res2) == 2
        assert res2[0] == "Good day, sir."
        assert res2[1] == "The system is operational!"

        # Flush final question
        flushed = buffer.flush()
        assert flushed == ["Are we ready?"]

    def test_sentence_streaming_buffer_persian_punctuation(self) -> None:
        buffer = SentenceStreamingBuffer()
        res = buffer.add_chunk("وضعیت سیستم عالی است. آیا دستور دیگری دارید؟ بله؛ در حال اجراست.")
        assert len(res) == 2
        assert "وضعیت سیستم عالی است." in res[0]
        assert "آیا دستور دیگری دارید؟" in res[1]

        flushed = buffer.flush()
        assert flushed == ["بله؛ در حال اجراست."]

    def test_sentence_streaming_buffer_avoids_abbreviations(self) -> None:
        buffer = SentenceStreamingBuffer()
        # "Dr. Smith" should not break on the dot after Dr
        res1 = buffer.add_chunk("Please contact Dr. Smith regarding the analysis.\n")
        assert len(res1) == 1
        assert res1[0] == "Please contact Dr. Smith regarding the analysis."


class TestElevenLabsTTSProvider:
    """Verifies ElevenLabs API client operations, key management, and audio encoding."""

    def test_provider_key_retrieval_from_settings(self, tmp_path) -> None:
        settings = Settings(
            elevenlabs_api_key=SecretStr("xi_secret_key_12345"),
        )
        provider = ElevenLabsTTSProvider(settings=settings)
        assert provider.get_api_key() == "xi_secret_key_12345"

    def test_provider_key_retrieval_from_credential_store(self, tmp_path) -> None:
        vault_file = tmp_path / "test_cred.enc"
        cred_store = CredentialStore(store_path=vault_file)
        cred_store.store_credential("elevenlabs", "api_key", "dpapi_stored_xi_key")

        settings = Settings(elevenlabs_api_key=SecretStr(""))
        provider = ElevenLabsTTSProvider(settings=settings)
        provider.cred_store = cred_store

        assert provider.get_api_key() == "dpapi_stored_xi_key"

    def test_provider_curated_voices_fallback(self) -> None:
        settings = Settings(elevenlabs_api_key=SecretStr(""))
        provider = ElevenLabsTTSProvider(settings=settings)

        voices = provider.fetch_available_voices(use_cache=False)
        assert len(voices) >= 5
        voice_ids = [v.voice_id for v in voices]
        assert DEFAULT_BRITISH_VOICE_ID in voice_ids
        assert "N2lVS1w4EtoT3dr4eOWO" in voice_ids  # Callum

    def test_provider_voice_discovery_mock(self) -> None:
        settings = Settings(elevenlabs_api_key=SecretStr("mock_valid_key"))
        provider = ElevenLabsTTSProvider(settings=settings)

        mock_payload = json.dumps(
            {
                "voices": [
                    {
                        "voice_id": "test_voice_1",
                        "name": "British Butler",
                        "category": "cloned",
                        "description": "Refined English gentleman",
                        "labels": {"accent": "british", "gender": "male", "age": "middle aged"},
                    }
                ]
            }
        ).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_payload
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            voices = provider.fetch_available_voices(use_cache=False)
            assert len(voices) == 1
            assert voices[0].voice_id == "test_voice_1"
            assert voices[0].name == "British Butler"
            assert voices[0].accent == "british"

    def test_pcm_to_wav_conversion(self) -> None:
        # Create 16000 samples of 16-bit mono silence (1 second of audio = 32000 bytes)
        raw_pcm = b"\x00\x00" * 16000
        wav_bytes = ElevenLabsTTSProvider.pcm_to_wav(raw_pcm, sample_rate=16000, channels=1)

        assert wav_bytes.startswith(b"RIFF")
        assert b"WAVE" in wav_bytes[:16]

        # Verify header structure via standard wave module
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == 16000

    def test_provider_stream_cancellation(self) -> None:
        settings = Settings(elevenlabs_api_key=SecretStr("mock_key"))
        provider = ElevenLabsTTSProvider(settings=settings)

        token = CancellationToken()
        token.cancel()

        # Generator should exit immediately without making network calls
        chunks = list(provider.synthesize_stream("Testing cancellation.", cancellation_token=token))
        assert chunks == []


class TestElevenLabsTTSService:
    """Verifies service consent guards, fallback cascades, and barge-in interruption."""

    def test_cloud_consent_guard_blocks_synthesis(self) -> None:
        settings = Settings(
            voice_cloud_tts_consent=False,
            elevenlabs_api_key=SecretStr("valid_xi_key"),
        )
        mock_fallback = MagicMock(spec=BaseTTSService)
        mock_fallback.speak.return_value = True

        service = ElevenLabsTTSService(fallback_engine=mock_fallback, settings=settings)
        res = service.speak(TTSRequest(text="Hello world"))

        assert res is True
        mock_fallback.speak.assert_called_once()

    def test_missing_api_key_delegates_to_fallback(self) -> None:
        settings = Settings(
            voice_cloud_tts_consent=True,
            elevenlabs_api_key=SecretStr(""),
        )
        mock_fallback = MagicMock(spec=BaseTTSService)
        mock_fallback.speak.return_value = True

        service = ElevenLabsTTSService(fallback_engine=mock_fallback, settings=settings)
        # Ensure provider has no key
        service.provider.get_api_key = lambda: ""  # type: ignore[method-assign]

        res = service.speak(TTSRequest(text="Hello world"))
        assert res is True
        mock_fallback.speak.assert_called_once()

    def test_barge_in_stops_playback_immediately(self) -> None:
        mock_fallback = MagicMock(spec=BaseTTSService)
        mock_fallback.is_speaking.return_value = False
        service = ElevenLabsTTSService(fallback_engine=mock_fallback)
        service._is_speaking = True

        service.stop()

        assert service.is_speaking() is False
        assert service._cancellation_token.is_cancelled() is True
        mock_fallback.stop.assert_called_once()

    def test_preview_voice_phrase(self) -> None:
        settings = Settings(
            voice_cloud_tts_consent=True,
            elevenlabs_api_key=SecretStr(""),
        )
        mock_fallback = MagicMock(spec=BaseTTSService)
        mock_fallback.speak.return_value = True

        service = ElevenLabsTTSService(fallback_engine=mock_fallback, settings=settings)
        service.preview_voice()

        mock_fallback.speak.assert_called_once()
        req: TTSRequest = mock_fallback.speak.call_args[0][0]
        assert "JARVIS voice identity" in req.text

    def test_factory_creates_elevenlabs_service(self) -> None:
        settings = Settings(
            voice_tts_engine="elevenlabs",
            voice_cloud_tts_consent=True,
        )
        with patch("config.get_settings", return_value=settings):
            service = create_tts_service()
            assert isinstance(service, ElevenLabsTTSService)


class TestResponseLanguagePolicy:
    """Verifies consistent response language policy and explicit Persian detection."""

    def test_detect_explicit_persian_request(self) -> None:
        assert (
            JarvisPersonalityEngine.detect_explicit_persian_request("به فارسی بگو وضعیت چطوره")
            is True
        )
        assert JarvisPersonalityEngine.detect_explicit_persian_request("فارسی صحبت کن لطفاً") is True
        assert (
            JarvisPersonalityEngine.detect_explicit_persian_request(
                "Explain this in Persian please"
            )
            is True
        )
        assert (
            JarvisPersonalityEngine.detect_explicit_persian_request("وضعیت سیستم رو بررسی کن")
            is False
        )
        assert (
            JarvisPersonalityEngine.detect_explicit_persian_request("Check CPU utilization")
            is False
        )

    def test_language_policy_system_instructions(self) -> None:
        # Default English policy
        instr_en = JarvisPersonalityEngine.get_system_instructions(
            language_policy=ResponseLanguagePolicy.DEFAULT_ENGLISH
        )
        assert "Default Language Policy: Respond in polished, natural British English" in instr_en

        # Explicit Persian request overrides policy
        instr_fa = JarvisPersonalityEngine.get_system_instructions(
            language_policy=ResponseLanguagePolicy.DEFAULT_ENGLISH,
            explicit_persian=True,
        )
        assert "شما جارویس" in instr_fa

        # Persian policy
        instr_per = JarvisPersonalityEngine.get_system_instructions(
            language_policy=ResponseLanguagePolicy.PERSIAN
        )
        assert "شما جارویس" in instr_per

    def test_resolve_references_detects_explicit_persian(self) -> None:
        prompt = "لطفاً به فارسی بگو وضعیت مصرف حافظه چقدر است؟"
        _, inferred = JarvisPersonalityEngine.resolve_references(
            current_prompt=prompt,
            history=[],
        )
        assert inferred.get("explicit_persian_requested") is True
        assert inferred.get("language_override") == "fa"

    def test_resolve_references_default_without_explicit_persian(self) -> None:
        prompt = "وضعیت حافظه چقدر است؟"
        _, inferred = JarvisPersonalityEngine.resolve_references(
            current_prompt=prompt,
            history=[],
        )
        assert "explicit_persian_requested" not in inferred
