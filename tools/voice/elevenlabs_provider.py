"""ElevenLabs Neural Text-to-Speech (TTS) Provider for JARVIS Voice Identity.

Provides high-fidelity British English neural speech synthesis using the official
ElevenLabs REST API with sentence-aware incremental streaming, dynamic voice
discovery, DPAPI secret management, and real-time barge-in interruption.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import wave
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from config import get_settings
from core.execution_context import CancellationToken
from infrastructure.credential_store import get_credential_store
from infrastructure.logging import get_logger, register_sensitive_token
from tools.voice.models import TTSRequest
from tools.voice.tts_service import BaseTTSService, WindowsTTSService

logger = get_logger("voice.elevenlabs")

# Curated British Male Voices in the ElevenLabs official library
CURATED_BRITISH_VOICES = {
    "JBFqnCBsd6RMkjVDRZzb": {
        "name": "George",
        "category": "premade",
        "description": "British, middle-aged male voice. Warm, captivating, articulate, and calm butler/assistant persona.",
        "accent": "British",
        "gender": "male",
        "age": "middle aged",
        "labels": {
            "accent": "british",
            "gender": "male",
            "age": "middle aged",
            "use_case": "assistant",
        },
    },
    "N2lVS1w4EtoT3dr4eOWO": {
        "name": "Callum",
        "category": "premade",
        "description": "British, middle-aged male voice. Intense, articulate, and composed.",
        "accent": "British",
        "gender": "male",
        "age": "middle aged",
        "labels": {
            "accent": "british",
            "gender": "male",
            "age": "middle aged",
            "use_case": "characters",
        },
    },
    "SOYHLrjzK2X1ezoPC6cr": {
        "name": "Harry",
        "category": "premade",
        "description": "British, young male voice. Natural, conversational, and energetic.",
        "accent": "British",
        "gender": "male",
        "age": "young",
        "labels": {
            "accent": "british",
            "gender": "male",
            "age": "young",
            "use_case": "conversational",
        },
    },
    "ZQe5CZPfIWgwIDFrvt9J": {
        "name": "James",
        "category": "premade",
        "description": "British, middle-aged male voice. Calm, sophisticated, narrative.",
        "accent": "British",
        "gender": "male",
        "age": "middle aged",
        "labels": {
            "accent": "british",
            "gender": "male",
            "age": "middle aged",
            "use_case": "narrative",
        },
    },
    "onwK4e9ZLuTAKqWW03F9": {
        "name": "Daniel",
        "category": "premade",
        "description": "British, mature male voice. Authoritative, deep, news broadcast style.",
        "accent": "British",
        "gender": "male",
        "age": "middle aged",
        "labels": {"accent": "british", "gender": "male", "age": "middle aged", "use_case": "news"},
    },
}

DEFAULT_BRITISH_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George


@dataclass
class ElevenLabsVoiceMetadata:
    """Metadata for an ElevenLabs voice."""

    voice_id: str
    name: str
    category: str = "premade"
    description: str = ""
    accent: str = "British"
    gender: str = "male"
    age: str = "middle aged"
    preview_url: str | None = None
    labels: dict[str, str] = field(default_factory=dict)


class SentenceStreamingBuffer:
    """Buffers streaming LLM tokens and yields complete sentences on safe boundaries.

    Handles English and Persian punctuation while preventing splits on common abbreviations.
    """

    KNOWN_ABBREVIATIONS = frozenset(
        {"mr", "mrs", "ms", "dr", "prof", "sr", "jr", "vs", "etc", "eg", "ie"}
    )
    BOUNDARY_PATTERN = re.compile(r"([.!?\n؟])(?:\s+)", re.UNICODE)

    def __init__(self) -> None:
        self._buffer: str = ""
        self._lock = threading.Lock()

    def add_chunk(self, chunk: str) -> list[str]:
        """Add text chunk and return any complete sentences found."""
        with self._lock:
            self._buffer += chunk
            sentences: list[str] = []

            while True:
                match = self.BOUNDARY_PATTERN.search(self._buffer)
                if not match:
                    break

                split_pos = match.end()
                candidate = self._buffer[: match.start() + 1].strip()

                # Guard against false-splits on common abbreviations (e.g. Dr., Mr.)
                if match.group(1) == ".":
                    last_word = candidate.rsplit(None, 1)[-1].rstrip(".!?\n؟").lower()
                    if last_word in self.KNOWN_ABBREVIATIONS:
                        next_match = self.BOUNDARY_PATTERN.search(self._buffer, split_pos)
                        if not next_match:
                            break
                        split_pos = next_match.end()
                        candidate = self._buffer[: next_match.start() + 1].strip()

                sentences.append(candidate)
                self._buffer = self._buffer[split_pos:].lstrip()

            return sentences

    def flush(self) -> list[str]:
        """Flush and return any residual buffered text."""
        with self._lock:
            residual = self._buffer.strip()
            self._buffer = ""
            return [residual] if residual else []


class ElevenLabsTTSProvider:
    """Direct client for ElevenLabs TTS and voice catalog APIs."""

    BASE_URL = "https://api.elevenlabs.io/v1"

    def __init__(self, settings: Any = None) -> None:
        self.settings = settings or get_settings()
        self.cred_store = get_credential_store()
        self._cached_voices: list[ElevenLabsVoiceMetadata] | None = None

    def get_api_key(self) -> str:
        """Retrieve ElevenLabs API key from settings, DPAPI credential store, or environment."""
        # 1. Check settings
        if self.settings:
            sec = getattr(self.settings, "elevenlabs_api_key", None)
            if sec and hasattr(sec, "get_secret_value"):
                val = sec.get_secret_value().strip()
                if val:
                    register_sensitive_token(val)
                    return val

        # 2. Check DPAPI credential vault
        stored = self.cred_store.get_credential("elevenlabs", "api_key")
        if stored and stored.strip():
            register_sensitive_token(stored.strip())
            return stored.strip()

        # 3. Check environment
        env_val = os.environ.get("ELEVENLABS_API_KEY", "").strip()
        if env_val:
            register_sensitive_token(env_val)
            return env_val

        return ""

    def fetch_available_voices(self, use_cache: bool = True) -> list[ElevenLabsVoiceMetadata]:
        """Query ElevenLabs /v1/voices endpoint for all available voices."""
        if use_cache and self._cached_voices is not None:
            return self._cached_voices

        api_key = self.get_api_key()
        if not api_key:
            logger.info("No ElevenLabs API key configured. Returning curated British catalog.")
            return self._build_curated_catalog()

        url = f"{self.BASE_URL}/voices"
        headers = {
            "xi-api-key": api_key,
            "Accept": "application/json",
            "User-Agent": "JARVIS-Desktop/10.0",
        }

        try:
            req = urllib.request.Request(url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            voices_list: list[ElevenLabsVoiceMetadata] = []
            for v in data.get("voices", []):
                labels = v.get("labels", {}) or {}
                meta = ElevenLabsVoiceMetadata(
                    voice_id=v.get("voice_id", ""),
                    name=v.get("name", "Unknown"),
                    category=v.get("category", "premade"),
                    description=v.get("description", "") or labels.get("description", ""),
                    accent=labels.get("accent", ""),
                    gender=labels.get("gender", ""),
                    age=labels.get("age", ""),
                    preview_url=v.get("preview_url"),
                    labels=labels,
                )
                voices_list.append(meta)

            if voices_list:
                self._cached_voices = voices_list
                return voices_list

        except urllib.error.HTTPError as http_err:
            logger.warning(
                f"ElevenLabs voice discovery returned HTTP {http_err.code}: {http_err.reason}. "
                f"Falling back to curated catalog."
            )
        except Exception as exc:
            logger.warning(
                f"ElevenLabs voice discovery failed ({exc}). Falling back to curated catalog."
            )

        return self._build_curated_catalog()

    def _build_curated_catalog(self) -> list[ElevenLabsVoiceMetadata]:
        """Return fallback catalog of known official British ElevenLabs voices."""
        catalog = []
        for vid, info in CURATED_BRITISH_VOICES.items():
            catalog.append(
                ElevenLabsVoiceMetadata(
                    voice_id=vid,
                    name=info["name"],
                    category=info["category"],
                    description=info["description"],
                    accent=info["accent"],
                    gender=info["gender"],
                    age=info["age"],
                    labels=info["labels"],
                )
            )
        return catalog

    def synthesize_stream(
        self,
        text: str,
        voice_id: str | None = None,
        cancellation_token: CancellationToken | None = None,
        output_format: str | None = None,
    ) -> Iterator[bytes]:
        """Stream synthesized audio chunks directly from ElevenLabs /stream endpoint."""
        if cancellation_token and cancellation_token.is_cancelled():
            return

        api_key = self.get_api_key()
        if not api_key:
            raise ValueError("ElevenLabs API key is missing.")

        target_voice = voice_id or getattr(
            self.settings, "elevenlabs_voice_id", DEFAULT_BRITISH_VOICE_ID
        )
        fmt = output_format or getattr(self.settings, "elevenlabs_output_format", "pcm_16000")
        model_id = getattr(self.settings, "elevenlabs_model_id", "eleven_multilingual_v2")
        stability = float(getattr(self.settings, "elevenlabs_stability", 0.75))
        similarity = float(getattr(self.settings, "elevenlabs_similarity_boost", 0.85))
        style = float(getattr(self.settings, "elevenlabs_style", 0.15))
        speaker_boost = bool(getattr(self.settings, "elevenlabs_use_speaker_boost", True))

        url = f"{self.BASE_URL}/text-to-speech/{target_voice}/stream?output_format={fmt}"
        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
            "User-Agent": "JARVIS-Desktop/10.0",
        }
        payload = json.dumps(
            {
                "text": text,
                "model_id": model_id,
                "voice_settings": {
                    "stability": stability,
                    "similarity_boost": similarity,
                    "style": style,
                    "use_speaker_boost": speaker_boost,
                },
            }
        ).encode("utf-8")

        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=15.0) as resp:
            chunk_size = 4096
            while True:
                if cancellation_token and cancellation_token.is_cancelled():
                    logger.debug("ElevenLabs streaming aborted via cancellation token.")
                    break
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    def synthesize(
        self,
        text: str,
        voice_id: str | None = None,
        cancellation_token: CancellationToken | None = None,
        output_format: str | None = None,
    ) -> bytes | None:
        """Synthesize entire text and return complete audio bytes."""
        chunks = []
        for chk in self.synthesize_stream(
            text=text,
            voice_id=voice_id,
            cancellation_token=cancellation_token,
            output_format=output_format,
        ):
            chunks.append(chk)
        if not chunks:
            return None
        return b"".join(chunks)

    @classmethod
    def pcm_to_wav(cls, pcm_bytes: bytes, sample_rate: int = 16000, channels: int = 1) -> bytes:
        """Package raw 16-bit PCM frames into standard WAV format with RIFF header."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(2)  # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_bytes)
        return buf.getvalue()


class ElevenLabsTTSService(BaseTTSService):
    """Production ElevenLabs TTS service with multi-tier fallback and immediate barge-in."""

    PREVIEW_PHRASE = "Good day, sir. JARVIS voice identity systems are fully operational."

    def __init__(
        self,
        fallback_engine: BaseTTSService | None = None,
        settings: Any = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.provider = ElevenLabsTTSProvider(settings=self.settings)
        self.fallback_engine = fallback_engine or WindowsTTSService(engine_name="sapi")
        self._lock = threading.RLock()
        self._is_speaking = False
        self._active_thread: threading.Thread | None = None
        self._cancellation_token = CancellationToken()
        self._current_temp_file: str | None = None

    def has_cloud_tts_consent(self) -> bool:
        """Verify explicit user consent for cloud speech synthesis."""
        try:
            if not self.settings:
                return False
            val = getattr(self.settings, "voice_cloud_tts_consent", False)
            return isinstance(val, bool) and val is True
        except Exception:
            return False

    def clean_text(self, text: str) -> str:
        """Strip markdown syntax, code blocks, links, and technical clutter."""
        cleaned = re.sub(r"```[\s\S]*?```", " [code omitted] ", text)
        cleaned = re.sub(r"`[^`]*`", "", cleaned)
        cleaned = re.sub(r"https?://\S+", "link", cleaned)
        cleaned = re.sub(r"[#*_~>]+", "", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def speak(self, request: TTSRequest) -> bool:
        """Synthesize and play speech asynchronously with immediate barge-in support."""
        with self._lock:
            self.stop()
            cleaned_text = self.clean_text(request.text)
            if not cleaned_text:
                return False

            # Tier 1 Consent Check
            if not self.has_cloud_tts_consent():
                logger.warning(
                    "Cloud TTS consent not granted (voice_cloud_tts_consent=False). "
                    "ElevenLabs falling back to offline speech."
                )
                return self.fallback_engine.speak(request)

            # Tier 1 Key Check
            api_key = self.provider.get_api_key()
            if not api_key:
                logger.warning("ElevenLabs API key not configured; falling back to offline speech.")
                return self.fallback_engine.speak(request)

            # Launch background worker
            self._cancellation_token = CancellationToken()
            self._is_speaking = True
            t = threading.Thread(
                target=self._synthesize_and_play_worker,
                args=(cleaned_text, request, self._cancellation_token),
                daemon=True,
            )
            self._active_thread = t
            t.start()
            return True

    def _synthesize_and_play_worker(
        self,
        text: str,
        request: TTSRequest,
        token: CancellationToken,
    ) -> None:
        """Worker thread synthesizing via ElevenLabs and playing audio chunks."""
        try:
            voice_id = request.voice_name or getattr(
                self.settings, "elevenlabs_voice_id", DEFAULT_BRITISH_VOICE_ID
            )
            # Prefer pcm_16000 for instant, lowest-latency in-memory playback
            configured_fmt = getattr(self.settings, "elevenlabs_output_format", "pcm_16000")
            req_fmt = "pcm_16000" if "pcm" in configured_fmt.lower() else configured_fmt

            raw_audio = self.provider.synthesize(
                text=text,
                voice_id=voice_id,
                cancellation_token=token,
                output_format=req_fmt,
            )

            if token.is_cancelled() or not raw_audio:
                return

            if "pcm" in req_fmt:
                # Convert PCM to WAV and play in-memory
                wav_bytes = self.provider.pcm_to_wav(raw_audio, sample_rate=16000)
                self._play_wav_bytes(wav_bytes)
            else:
                # Play MP3 format
                self._play_mp3_bytes(raw_audio, token)

        except urllib.error.HTTPError as http_err:
            logger.warning(
                f"ElevenLabs TTS HTTP {http_err.code} ({http_err.reason}). "
                f"Falling back to secondary provider."
            )
            if not token.is_cancelled():
                self.fallback_engine.speak(request)
        except Exception as exc:
            logger.warning(
                f"ElevenLabs TTS synthesis failed: {exc}. Falling back to secondary provider."
            )
            if not token.is_cancelled():
                self.fallback_engine.speak(request)
        finally:
            with self._lock:
                self._is_speaking = False

    def _play_wav_bytes(self, wav_bytes: bytes) -> None:
        """Play PCM WAV bytes through Windows audio subsystem."""
        try:
            import winsound

            winsound.PlaySound(wav_bytes, winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception as exc:
            logger.debug(f"winsound playback error: {exc}")

    def _play_mp3_bytes(self, mp3_bytes: bytes, token: CancellationToken) -> None:
        """Play MP3 audio using Windows MCI subsystem."""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(mp3_bytes)
            tmp.flush()
            tmp_path = tmp.name

        try:
            with self._lock:
                self._current_temp_file = tmp_path

            import ctypes

            winmm = ctypes.windll.winmm
            alias = f"jarvis_tts_{int(time.time() * 1000)}"
            winmm.mciSendStringW(f'open "{tmp_path}" type mpegvideo alias {alias}', None, 0, 0)
            winmm.mciSendStringW(f"play {alias}", None, 0, 0)

            # Wait while playing or until cancelled
            while self._is_speaking and not token.is_cancelled():
                buf = ctypes.create_unicode_buffer(128)
                winmm.mciSendStringW(f"status {alias} mode", buf, 128, 0)
                if buf.value != "playing":
                    break
                time.sleep(0.05)

            winmm.mciSendStringW(f"stop {alias}", None, 0, 0)
            winmm.mciSendStringW(f"close {alias}", None, 0, 0)
        except Exception as exc:
            logger.debug(f"MCI MP3 playback error: {exc}")
        finally:
            with self._lock:
                if self._current_temp_file:
                    with contextlib.suppress(Exception):
                        os.unlink(self._current_temp_file)
                    self._current_temp_file = None

    def preview_voice(self, voice_id: str | None = None) -> bool:
        """Play standard voice preview phrase for persona verification."""
        target_voice = voice_id or getattr(
            self.settings, "elevenlabs_voice_id", DEFAULT_BRITISH_VOICE_ID
        )
        logger.info(f"Triggering ElevenLabs preview for voice: {target_voice}")
        return self.speak(
            TTSRequest(
                text=self.PREVIEW_PHRASE,
                voice_name=target_voice,
                language="en",
            )
        )

    def stop(self) -> None:
        """Immediately interrupt and stop speech (instant barge-in <50ms)."""
        with self._lock:
            self._cancellation_token.cancel()
            self._is_speaking = False

            # Instant purge of Windows audio sound buffer
            with contextlib.suppress(Exception):
                import winsound

                winsound.PlaySound(None, winsound.SND_PURGE)

            # Close all active MCI channels
            with contextlib.suppress(Exception):
                import ctypes

                ctypes.windll.winmm.mciSendStringW("close all", None, 0, 0)

            # Stop fallback engine
            with contextlib.suppress(Exception):
                self.fallback_engine.stop()

            # Cleanup temp files
            if self._current_temp_file:
                with contextlib.suppress(Exception):
                    os.unlink(self._current_temp_file)
                self._current_temp_file = None

            logger.debug("ElevenLabs TTS interrupted immediately (barge-in).")

    def is_speaking(self) -> bool:
        """Return True if speech synthesis or playback is actively occurring."""
        with self._lock:
            if self._is_speaking:
                return True
            return self.fallback_engine.is_speaking()

    def get_available_voices(self) -> list[str]:
        """Return list of voice identifiers and descriptions."""
        voices: list[str] = []
        try:
            cloud_voices = self.provider.fetch_available_voices()
            for v in cloud_voices:
                voices.append(f"{v.name} ({v.voice_id}) - {v.accent} {v.gender}")
        except Exception:
            for vid, info in CURATED_BRITISH_VOICES.items():
                voices.append(f"{info['name']} ({vid}) - {info['accent']} {info['gender']}")

        try:
            native = self.fallback_engine.get_available_voices()
            for nv in native:
                voices.append(f"{nv} (Windows Native)")
        except Exception:
            pass

        return voices
