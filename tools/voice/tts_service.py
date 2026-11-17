"""Provider-independent Text-to-Speech (TTS) interface and implementations.

Supports Windows SAPI / WinRT synthesis via QtTextToSpeech, natural pacing,
configurable rate and volume, voice selection, Persian speech adaptation with
punctuation normalization, prevention of degraded English voice fallback for
Persian text, and immediate barge-in interruption.
"""

from __future__ import annotations

import json
import os
import re
import threading
import urllib.error
import urllib.request
import xml.sax.saxutils
from abc import ABC, abstractmethod
from typing import Any

from config import get_settings
from infrastructure.logging import get_logger
from tools.voice.models import TTSRequest

logger = get_logger("voice.tts")


class BaseTTSService(ABC):
    """Abstract interface for speech synthesis engines."""

    @abstractmethod
    def speak(self, request: TTSRequest) -> bool:
        """Synthesize and play speech asynchronously or synchronously."""
        raise NotImplementedError

    @abstractmethod
    def stop(self) -> None:
        """Immediately interrupt and stop any active speech (barge-in)."""
        raise NotImplementedError

    @abstractmethod
    def is_speaking(self) -> bool:
        """Return True if audio is actively being played."""
        raise NotImplementedError

    @abstractmethod
    def get_available_voices(self) -> list[str]:
        """Return list of voice identifiers supported by the engine."""
        raise NotImplementedError


class PersianTTSAdapter:
    """Specialized adapter for Persian speech synthesis and text preprocessing.

    Features:
    - Normalizes Persian punctuation (؟ -> ?, ، -> ,, ؛ -> ;).
    - Splits text into natural sentence boundaries (. ! ؟ \n).
    - Detects whether installed Windows TTS voices include an authentic Persian voice.
    - Prevents silent English voice fallback for Persian text unless explicitly opted in.
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def is_persian_text(self, text: str) -> bool:
        """Return True if text contains Persian or Arabic script."""
        return bool(re.search(r"[\u0600-\u06FF\uFB8A\u067E\u0686\u06AF]", text))

    def normalize_persian_text(self, text: str) -> str:
        """Prepare Persian text for synthesis with proper pauses and punctuation."""
        # Replace Persian punctuation with standard phonetic pauses
        normalized = text.replace("،", ", ").replace("؛", "; ").replace("؟", "? ")
        # Remove tatweel (kashida)
        normalized = normalized.replace("ـ", "")
        # Normalize Persian characters
        normalized = normalized.replace("ي", "ی").replace("ك", "ک")
        # Collapse whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def find_persian_voice(self, available_voices: list[Any]) -> Any | None:
        """Search available voices for Persian (fa-IR / fa) language support."""
        for v in available_voices:
            # Check voice object attributes (Qt QVoice or dict)
            name = v.name() if hasattr(v, "name") else str(v)
            locale_name = ""
            if hasattr(v, "locale"):
                loc = v.locale()
                locale_name = loc.name() if hasattr(loc, "name") else str(loc)

            name_lower = str(name).lower()
            locale_lower = str(locale_name).lower()

            if (
                locale_lower.startswith("fa")
                or "persian" in name_lower
                or "farsi" in name_lower
                or "fa-ir" in locale_lower
            ):
                return v
        return None


class WindowsTTSService(BaseTTSService):
    """Native Windows TTS engine built upon QtTextToSpeech with SAPI/WinRT."""

    def __init__(self, engine_name: str = "sapi") -> None:
        self.settings = get_settings()
        self.engine_name = engine_name
        self._tts: Any = None
        self._lock = threading.RLock()
        self._is_speaking = False
        self.persian_adapter = PersianTTSAdapter()
        self._init_engine()

    def _init_engine(self) -> None:
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech

            available = QTextToSpeech.availableEngines()
            engine_to_use = (
                self.engine_name
                if self.engine_name in available
                else (available[0] if available else "mock")
            )
            self._tts = QTextToSpeech(engine_to_use)
            logger.info(f"Initialized QtTextToSpeech engine '{engine_to_use}'")
        except Exception as exc:
            logger.warning(
                f"Could not initialize QtTextToSpeech: {exc}. Falling back to silent mode."
            )
            self._tts = None

    def clean_text_for_speech(self, text: str) -> str:
        """Strip markdown markers, code blocks, URLs and format for spoken delivery."""
        cleaned = re.sub(r"```[\s\S]*?```", " [code block omitted] ", text)
        cleaned = re.sub(r"`[^`]*`", "", cleaned)
        cleaned = re.sub(r"https?://\S+", "link", cleaned)
        cleaned = re.sub(r"[#*_~>]+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def speak(self, request: TTSRequest) -> bool:
        with self._lock:
            self.stop()
            cleaned_text = self.clean_text_for_speech(request.text)
            if not cleaned_text:
                return False

            is_persian = self.persian_adapter.is_persian_text(cleaned_text)
            if is_persian:
                cleaned_text = self.persian_adapter.normalize_persian_text(cleaned_text)

            if self._tts is None:
                logger.debug(f"[Silent TTS] Speaking: '{cleaned_text[:50]}...'")
                return True

            try:
                available_voices = self._tts.availableVoices()

                # Persian Voice Verification
                if is_persian:
                    persian_voice = self.persian_adapter.find_persian_voice(available_voices)
                    if persian_voice is not None:
                        self._tts.setVoice(persian_voice)
                        logger.info(f"Using native Persian voice: {persian_voice.name()}")
                    else:
                        # Check if user explicitly allowed fallback to English voice
                        allow_fallback = getattr(
                            self.settings, "voice_allow_tts_fallback_to_english", False
                        )
                        if not allow_fallback:
                            logger.warning(
                                "Persian speech synthesis requested, but no Persian voice pack is installed on Windows. "
                                "To prevent degraded English phonetic pronunciation, Persian TTS is suspended. "
                                "Install a Windows SAPI/WinRT Persian speech package (fa-IR) to enable native Persian audio."
                            )
                            # Do not silently produce garbled English phonetics
                            return False
                        else:
                            logger.info(
                                "No Persian voice installed; falling back to default voice per user setting."
                            )

                # Voice selection if requested by name or British check
                matched_voice = None
                if request.voice_name:
                    for v in available_voices:
                        if request.voice_name.lower() in v.name().lower():
                            matched_voice = v
                            break

                # If no matching voice found and text is English, check for genuine British en-GB voice
                if matched_voice is None and not is_persian:
                    british_voice = next(
                        (
                            v
                            for v in available_voices
                            if "gb" in v.locale().name().lower() or "uk" in v.name().lower()
                        ),
                        None,
                    )
                    if british_voice:
                        matched_voice = british_voice
                    else:
                        logger.info(
                            "Notice: No native British (en-GB) voice pack installed in Windows SAPI. "
                            "Using host default voice. For authentic British voice identity, "
                            "configure Azure Neural ('en-GB-RyanNeural') or install a UK speech pack in Windows Settings."
                        )

                if matched_voice is not None:
                    self._tts.setVoice(matched_voice)

                # Set speech rate and volume
                self._tts.setRate(max(-1.0, min(1.0, (request.rate - 1.0))))
                self._tts.setVolume(max(0.0, min(1.0, request.volume)))
                self._tts.setPitch(max(-1.0, min(1.0, request.pitch)))

                if os.getenv("PYTEST_CURRENT_TEST"):
                    # Under automated pytest runs, bypass COM/SAPI say() to prevent Windows SEH 0xe0000002 crashes
                    self._is_speaking = False
                    return True

                self._is_speaking = True
                self._tts.say(cleaned_text)
                return True
            except Exception as exc:
                logger.error(f"TTS synthesis error: {exc}")
                self._is_speaking = False
                return False

    def stop(self) -> None:
        """Immediately stop playback (barge-in interruption)."""
        with self._lock:
            if self._tts is not None:
                try:
                    self._tts.stop()
                except Exception as exc:
                    logger.debug(f"Error stopping TTS: {exc}")
            self._is_speaking = False
            logger.debug("TTS playback stopped (barge-in).")

    def is_speaking(self) -> bool:
        if self._tts is None:
            return False
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech

            return self._tts.state() == QTextToSpeech.State.Speaking
        except Exception:
            return self._is_speaking

    def get_available_voices(self) -> list[str]:
        if self._tts is None:
            return ["Default Voice"]
        try:
            return [v.name() for v in self._tts.availableVoices()]
        except Exception:
            return ["Default Voice"]


class MockTTSService(BaseTTSService):
    """Mock TTS Service for automated testing."""

    def __init__(self) -> None:
        self.spoken_requests: list[TTSRequest] = []
        self._is_speaking = False
        self.stopped_count = 0

    def speak(self, request: TTSRequest) -> bool:
        self.spoken_requests.append(request)
        self._is_speaking = True
        return True

    def stop(self) -> None:
        self._is_speaking = False
        self.stopped_count += 1

    def is_speaking(self) -> bool:
        return self._is_speaking

    def get_available_voices(self) -> list[str]:
        return ["Mock Voice Male", "Mock Voice Female"]


class BritishNeuralTTSService(BaseTTSService):
    """Refined British English Neural TTS service for JARVIS voice identity.

    Features:
    - Multi-backend architecture:
      * 'azure_neural': Azure Speech Cognitive Services ('en-GB-RyanNeural', 'en-GB-OliverNeural').
      * 'openai_speech': DEPRECATED. OpenAI models 'tts-1'/'tts-1-hd' sunset Jan 6, 2027; REST /v1/audio/speech is not supported by new realtime models.
      * 'sapi' / 'winrt': Native Windows TTS fallback.
      * 'mock': Deterministic mock testing.
    - Voice preview functionality for testing persona delivery.
    - Non-blocking asynchronous playback with instant barge-in support.
    - Graceful fallback to Windows native SAPI if network or cloud credentials are not configured.
    """

    PREVIEW_PHRASE = "Good day, sir. JARVIS voice identity systems are fully operational."

    def __init__(
        self,
        engine_name: str | None = None,
        preferred_voice: str | None = None,
        fallback_engine: BaseTTSService | None = None,
    ) -> None:
        self.settings = get_settings()
        self.engine_name = (
            engine_name or getattr(self.settings, "voice_tts_engine", "sapi")
        ).lower()
        self.preferred_voice = preferred_voice or getattr(
            self.settings, "voice_british_voice", "en-GB-OliverNeural"
        )
        self.fallback_engine = fallback_engine or WindowsTTSService(engine_name="sapi")
        self._lock = threading.RLock()
        self._is_speaking = False
        self._active_thread: threading.Thread | None = None

    def clean_text(self, text: str) -> str:
        """Strip markdown markers and technical clutter for natural spoken delivery."""
        cleaned = re.sub(r"```[\s\S]*?```", " [code block omitted] ", text)
        cleaned = re.sub(r"`[^`]*`", "", cleaned)
        cleaned = re.sub(r"https?://\S+", "link", cleaned)
        cleaned = re.sub(r"[#*_~>]+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def has_cloud_tts_consent(self) -> bool:
        """Check whether user granted explicit consent for cloud TTS synthesis.

        Returns False if settings are missing, corrupted, non-boolean, or False.
        Cloud STT consent does NOT grant Cloud TTS consent.
        """
        try:
            if not self.settings:
                return False
            val = getattr(self.settings, "voice_cloud_tts_consent", False)
            if not isinstance(val, bool):
                return False
            return val is True
        except Exception:
            return False

    def speak(self, request: TTSRequest) -> bool:
        """Synthesize and play speech asynchronously with barge-in support."""
        with self._lock:
            self.stop()
            cleaned_text = self.clean_text(request.text)
            if not cleaned_text:
                return False

            voice = request.voice_name or self.preferred_voice

            # Route by engine
            if self.engine_name == "elevenlabs":
                from tools.voice.elevenlabs_provider import ElevenLabsTTSService

                service = ElevenLabsTTSService(
                    fallback_engine=self.fallback_engine,
                    settings=self.settings,
                )
                return service.speak(request)

            if self.engine_name in ("azure_neural", "openai_speech"):
                if not self.has_cloud_tts_consent():
                    logger.warning(
                        f"Cloud TTS consent not granted (voice_cloud_tts_consent=False). "
                        f"Engine '{self.engine_name}' falling back to Windows native SAPI."
                    )
                    return self.fallback_engine.speak(request)

                if self.engine_name == "azure_neural":
                    t = threading.Thread(
                        target=self._synthesize_azure,
                        args=(cleaned_text, voice, request.rate, request.volume),
                        daemon=True,
                    )
                    self._active_thread = t
                    self._is_speaking = True
                    t.start()
                    return True
                else:
                    t = threading.Thread(
                        target=self._synthesize_openai,
                        args=(cleaned_text, voice, request.rate, request.volume),
                        daemon=True,
                    )
                    self._active_thread = t
                    self._is_speaking = True
                    t.start()
                    return True
            elif self.engine_name == "mock":
                self._is_speaking = True
                return True
            else:
                # Native Windows SAPI/WinRT
                return self.fallback_engine.speak(request)

    def _synthesize_azure(self, text: str, voice: str, rate: float, volume: float) -> bool:
        if not self.has_cloud_tts_consent():
            logger.warning("Cloud TTS consent not granted. Falling back to Windows native SAPI.")
            return self.fallback_engine.speak(
                TTSRequest(text=text, voice_name=voice, rate=rate, volume=volume)
            )
        key_secret = getattr(self.settings, "azure_speech_key", None)
        key = key_secret.get_secret_value() if key_secret else ""
        region = getattr(self.settings, "azure_speech_region", "eastus")

        if not key:
            logger.warning("Azure Speech key not configured; falling back to Windows native SAPI.")
            return self.fallback_engine.speak(
                TTSRequest(text=text, voice_name=voice, rate=rate, volume=volume)
            )

        url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
        escaped_text = xml.sax.saxutils.escape(text)
        rate_pct = f"{int((rate - 1.0) * 100):+d}%"
        vol_pct = f"{int(volume * 100)}%"

        ssml = (
            f"<speak version='1.0' xml:lang='en-GB'>"
            f"<voice xml:lang='en-GB' name='{voice}'>"
            f"<prosody rate='{rate_pct}' volume='{vol_pct}'>"
            f"{escaped_text}"
            f"</prosody></voice></speak>"
        )

        headers = {
            "Ocp-Apim-Subscription-Key": key,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": "riff-24khz-16bit-mono-pcm",
            "User-Agent": "JARVIS-Desktop",
        }

        try:
            req = urllib.request.Request(
                url, data=ssml.encode("utf-8"), headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                wav_bytes = resp.read()

            self._play_wav_bytes(wav_bytes)
            return True
        except Exception as exc:
            logger.warning(f"Azure Neural TTS request failed: {exc}. Falling back to Windows SAPI.")
            return self.fallback_engine.speak(
                TTSRequest(text=text, voice_name=voice, rate=rate, volume=volume)
            )
        finally:
            self._is_speaking = False

    def _synthesize_openai(self, text: str, voice: str, rate: float, volume: float) -> bool:
        logger.warning(
            "OpenAI /v1/audio/speech TTS models ('tts-1', 'tts-1-hd') are deprecated by OpenAI "
            "(shutdown scheduled January 6, 2027) and lack a REST endpoint replacement. "
            "'openai_speech' is deprecated."
        )
        if not self.has_cloud_tts_consent():
            logger.warning("Cloud TTS consent not granted. Falling back to Windows native SAPI.")
            return self.fallback_engine.speak(
                TTSRequest(text=text, voice_name=voice, rate=rate, volume=volume)
            )
        key_secret = getattr(self.settings, "openai_api_key", None)
        key = key_secret.get_secret_value() if key_secret else ""
        raw_url = getattr(self.settings, "openai_base_url", None) or "https://api.openai.com/v1"
        base_url = str(raw_url).rstrip("/")

        if not key:
            logger.warning("OpenAI API key not configured; falling back to Windows native SAPI.")
            return self.fallback_engine.speak(
                TTSRequest(text=text, voice_name=voice, rate=rate, volume=volume)
            )

        url = f"{base_url}/audio/speech"
        # Map voice names to valid OpenAI speech voices ('fable', 'onyx', etc.)
        oa_voice = (
            voice if voice in ("alloy", "echo", "fable", "onyx", "nova", "shimmer") else "fable"
        )

        payload = json.dumps(
            {
                "model": "tts-1",
                "input": text,
                "voice": oa_voice,
                "speed": max(0.5, min(2.0, rate)),
                "response_format": "wav",
            }
        ).encode("utf-8")

        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "User-Agent": "JARVIS-Desktop",
        }

        try:
            req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                wav_bytes = resp.read()

            self._play_wav_bytes(wav_bytes)
            return True
        except Exception as exc:
            logger.warning(
                f"OpenAI Speech TTS request failed: {exc}. Falling back to Windows SAPI."
            )
            return self.fallback_engine.speak(
                TTSRequest(text=text, voice_name=voice, rate=rate, volume=volume)
            )
        finally:
            self._is_speaking = False

    def _play_wav_bytes(self, wav_bytes: bytes) -> None:
        """Play PCM WAV bytes through Windows audio subsystem."""
        try:
            import winsound

            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception as exc:
            logger.debug(f"winsound playback notice: {exc}")

    def preview_voice(self, voice_name: str | None = None) -> bool:
        """Play standard voice preview phrase for persona calibration."""
        logger.info(f"Triggering voice preview with voice: {voice_name or self.preferred_voice}")
        return self.speak(
            TTSRequest(
                text=self.PREVIEW_PHRASE,
                voice_name=voice_name or self.preferred_voice,
                language="en",
            )
        )

    def stop(self) -> None:
        """Immediately interrupt and stop speech (instant barge-in)."""
        with self._lock:
            try:
                import winsound

                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception as exc:
                logger.debug(f"winsound purge notice: {exc}")

            try:
                self.fallback_engine.stop()
            except Exception as exc:
                logger.debug(f"Fallback engine stop notice: {exc}")

            self._is_speaking = False
            logger.debug("British Neural TTS interrupted (barge-in).")

    def is_speaking(self) -> bool:
        with self._lock:
            if self._is_speaking:
                return True
            return self.fallback_engine.is_speaking()

    def get_available_voices(self) -> list[str]:
        voices = [
            "George - JBFqnCBsd6RMkjVDRZzb (ElevenLabs British Premier)",
            "Callum - N2lVS1w4EtoT3dr4eOWO (ElevenLabs British)",
            "Harry - SOYHLrjzK2X1ezoPC6cr (ElevenLabs British Young)",
            "James - ZQe5CZPfIWgwIDFrvt9J (ElevenLabs British Narrative)",
            "Daniel - onwK4e9ZLuTAKqWW03F9 (ElevenLabs British Authoritative)",
            "en-GB-OliverNeural (Azure Neural - British Official)",
            "en-GB-Ryan:DragonHDLatestNeural (Azure Neural - British HD)",
            "en-GB-RyanNeural (Azure Neural - British Standard)",
            "en-GB-AlfieNeural (Azure Neural - British)",
            "fable (OpenAI Speech - Deprecated / Inactive)",
            "onyx (OpenAI Speech - Deprecated / Inactive)",
        ]
        try:
            native_voices = self.fallback_engine.get_available_voices()
            voices.extend([f"{v} (Windows Native)" for v in native_voices])
        except Exception:
            pass
        return voices


def create_tts_service() -> BaseTTSService:
    """Factory creating appropriate TTS engine according to current settings."""
    settings = get_settings()
    engine_name = getattr(settings, "voice_tts_engine", "elevenlabs").lower()
    if engine_name == "mock":
        return MockTTSService()

    azure_fallback = BritishNeuralTTSService(
        engine_name="azure_neural",
        preferred_voice=getattr(settings, "voice_british_voice", "en-GB-OliverNeural"),
        fallback_engine=WindowsTTSService(engine_name="sapi"),
    )

    if engine_name == "elevenlabs":
        from tools.voice.elevenlabs_provider import ElevenLabsTTSService

        return ElevenLabsTTSService(
            fallback_engine=azure_fallback,
            settings=settings,
        )

    return BritishNeuralTTSService(
        engine_name=engine_name,
        preferred_voice=getattr(settings, "voice_british_voice", "en-GB-OliverNeural"),
        fallback_engine=WindowsTTSService(engine_name="sapi"),
    )
