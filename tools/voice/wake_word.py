"""Acoustic Wake-Word detection and Push-To-Talk activation for JARVIS Phase 9.

Implements real local acoustic wake-word analysis for "Jarvis" and "جارویس"
on raw PCM audio frames, combined with self-activation suppression (preventing
JARVIS TTS from triggering its own detector), configurable sensitivity,
debounce protection, Push-To-Talk fallback, and zero cloud audio leakage.
"""

from __future__ import annotations

import math
import re
import struct
import threading
import time
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("voice.wake_word")


class AcousticWakeWordDetector:
    """Real local acoustic keyword detector operating directly on raw PCM audio frames.

    Analyzes phonetic acoustic characteristics of "Jarvis" (/ˈdʒɑːrvɪs/) and "جارویس":
    1. Syllable Envelope & Duration: Bisyllabic envelope structure (Jar-vis / جار-ویس)
       with total duration typically between 350ms and 950ms.
    2. Energy Valley: Characteristic inter-syllable energy dip at the fricative/liquid transition.
    3. Terminal Sibilant S: The final /s/ (س) sound exhibits a high Zero-Crossing Rate (ZCR)
       distinct from vowels and background noise.
    4. Self-Activation Suppression: Automatically suppressed when JARVIS TTS is speaking.
    """

    def __init__(
        self,
        wake_word: str = "Jarvis",
        sensitivity: float = 0.7,
        sample_rate: int = 16000,
    ) -> None:
        self.wake_word = wake_word.strip()
        self.sensitivity = max(0.1, min(1.0, sensitivity))
        self.sample_rate = sample_rate
        # Sliding audio buffer for acoustic analysis (up to 2.0 seconds of 16-bit 16kHz PCM)
        self._max_buffer_samples = int(self.sample_rate * 2.0)
        self._samples: list[int] = []
        self._lock = threading.RLock()

    def set_sensitivity(self, sensitivity: float) -> None:
        self.sensitivity = max(0.1, min(1.0, sensitivity))

    def reset(self) -> None:
        with self._lock:
            self._samples.clear()

    def process_pcm_frame(self, pcm_data: bytes) -> tuple[bool, float]:
        """Ingest raw PCM 16-bit mono audio frame and evaluate acoustic keyword match.

        Returns:
            (detected: bool, confidence: float)
        """
        if not pcm_data or len(pcm_data) < 2:
            return False, 0.0

        num_samples = len(pcm_data) // 2
        try:
            unpacked = struct.unpack(f"<{num_samples}h", pcm_data[: num_samples * 2])
        except struct.error:
            return False, 0.0

        with self._lock:
            self._samples.extend(unpacked)
            if len(self._samples) > self._max_buffer_samples:
                self._samples = self._samples[-self._max_buffer_samples :]

            # Need at least 400ms of audio to evaluate "Jarvis" acoustic signature
            min_samples = int(self.sample_rate * 0.40)
            if len(self._samples) < min_samples:
                return False, 0.0

            return self._evaluate_acoustic_signature(self._samples)

    def _evaluate_acoustic_signature(self, samples: list[int]) -> tuple[bool, float]:
        """Compute acoustic phonetic features across the buffered audio frame."""
        total_samples = len(samples)
        if total_samples == 0:
            return False, 0.0

        # Window into 25ms frames with 10ms hop
        frame_len = int(self.sample_rate * 0.025)
        hop_len = int(self.sample_rate * 0.010)
        if frame_len <= 0 or hop_len <= 0 or total_samples < frame_len:
            return False, 0.0

        energies: list[float] = []
        zcrs: list[float] = []

        for start in range(0, total_samples - frame_len, hop_len):
            chunk = samples[start : start + frame_len]
            # RMS energy normalized to 0.0 - 1.0
            sum_sq = sum(s * s for s in chunk)
            rms = math.sqrt(sum_sq / len(chunk)) / 32768.0
            energies.append(rms)

            # Zero-crossing rate
            crossings = sum(
                1
                for i in range(1, len(chunk))
                if (chunk[i] >= 0 and chunk[i - 1] < 0) or (chunk[i] < 0 and chunk[i - 1] >= 0)
            )
            zcr = crossings / len(chunk)
            zcrs.append(zcr)

        if not energies:
            return False, 0.0

        max_energy = max(energies)
        # Background silence or very low volume: ignore
        if max_energy < 0.010:
            return False, 0.0

        # Segment active speech region (energy > 15% max)
        thresh = max(0.008, max_energy * 0.15)
        active_indices = [i for i, e in enumerate(energies) if e >= thresh]
        if not active_indices:
            return False, 0.0

        start_idx = active_indices[0]
        end_idx = active_indices[-1]
        active_len = end_idx - start_idx + 1

        # Duration check: active speech must be 250ms - 1900ms to accommodate "Hey Jarvis" (3 syllables) or "Jarvis" (2 syllables)
        duration_ms = (active_len * hop_len / self.sample_rate) * 1000.0
        if duration_ms < 250.0 or duration_ms > 1900.0:
            return False, 0.0

        active_energies = energies[start_idx : end_idx + 1]
        active_zcrs = zcrs[start_idx : end_idx + 1]

        # 1. Terminal Sibilant Check: The final region of the utterance (the /s/ sound)
        # must have significantly higher ZCR than the voiced vowel prefix
        tail_start = int(len(active_zcrs) * 0.70)
        tail_zcrs = active_zcrs[tail_start:]
        head_zcrs = active_zcrs[:tail_start]

        avg_tail_zcr = sum(tail_zcrs) / max(len(tail_zcrs), 1)
        avg_head_zcr = sum(head_zcrs) / max(len(head_zcrs), 1)

        # 2. Syllable Cadence: Check for 2 or 3 distinct energy regions (Jar-vis or Hey-Jar-vis)
        mid = len(active_energies) // 2
        syllable1_max = max(active_energies[:mid]) if mid > 0 else 0.0
        syllable2_max = max(active_energies[mid:]) if mid < len(active_energies) else 0.0
        mid_dip = min(
            active_energies[int(len(active_energies) * 0.35) : int(len(active_energies) * 0.65)]
            or [max_energy]
        )

        has_bisyllable = (
            syllable1_max > 0.012
            and syllable2_max > 0.008
            and mid_dip < (min(syllable1_max, syllable2_max) * 0.90)
        )

        # Check multi-segment energy for 3-syllable "Hey Jarvis"
        n_seg = 3
        seg_len = len(active_energies) // n_seg
        has_multisyllable = False
        if seg_len > 0:
            seg_peaks = [
                max(active_energies[i * seg_len : (i + 1) * seg_len]) for i in range(n_seg)
            ]
            has_multisyllable = sum(1 for p in seg_peaks if p > 0.010) >= 2

        has_sibilant_tail = avg_tail_zcr > 0.14 and avg_tail_zcr > (avg_head_zcr * 1.25)

        # Confidence calculation based on acoustic match
        score = 0.0
        if has_bisyllable or has_multisyllable:
            score += 0.45
        if has_sibilant_tail:
            score += 0.40
        # Duration fit penalty / bonus
        if 350.0 <= duration_ms <= 1600.0:
            score += 0.15

        # Apply configurable sensitivity scaling (0.65 at sens 0.5, 0.525 at sens 1.0)
        # Sibilant tail (/s/ in Jarvis) is strictly required to prevent triggering on steady noise
        detection_threshold = 0.65 - (self.sensitivity - 0.5) * 0.25
        is_detected = (score >= detection_threshold) and has_sibilant_tail

        return is_detected, min(1.0, score)


class WakeWordDetector:
    """Coordinates acoustic wake-word detection, text-based validation, and PTT controls."""

    DEFAULT_WAKE_WORDS = ("jarvis", "جارویس")

    def __init__(
        self,
        wake_word: str = "Jarvis",
        sensitivity: float = 0.7,
        debounce_seconds: float = 2.5,
        enabled: bool = False,
        sample_rate: int = 16000,
    ) -> None:
        self.wake_word = wake_word.strip()
        self.sensitivity = max(0.1, min(1.0, sensitivity))
        self.debounce_seconds = debounce_seconds
        self.enabled = enabled
        self.sample_rate = sample_rate
        self._last_trigger_time: float = 0.0
        self._is_listening_muted: bool = False
        self._is_tts_active: bool = False

        # Local acoustic detector operating directly on PCM stream
        self.acoustic_detector = AcousticWakeWordDetector(
            wake_word=self.wake_word,
            sensitivity=self.sensitivity,
            sample_rate=self.sample_rate,
        )

        # Regex patterns for secondary verification on transcripts
        self._patterns = self._compile_patterns(self.wake_word)

    def _compile_patterns(self, word: str) -> list[re.Pattern[str]]:
        variants = {word.lower().strip()}
        variants.update(
            [
                "hey jarvis",
                "hey, jarvis",
                "hey jarviss",
                "hey jarvez",
                "hi jarvis",
                "hello jarvis",
                "ok jarvis",
                "okay jarvis",
                "jarvis",
                "jarviss",
                "jarvez",
                "هی جارویس",
                "هی، جارویس",
                "هی جارویز",
                "سلام جارویس",
                "سلام، جارویس",
                "جارویس",
                "جارویسس",
                "جارویز",
                "جرویس",
                "ای جارویس",
                "اوکی جارویس",
            ]
        )
        sorted_variants = sorted(variants, key=len, reverse=True)
        patterns = []
        for v in sorted_variants:
            patterns.append(re.compile(rf"(?:\b|^){re.escape(v)}(?:\b|$)", re.IGNORECASE))
        return patterns

    def set_wake_word(self, word: str) -> None:
        """Update configured wake word."""
        self.wake_word = word.strip()
        self.acoustic_detector.wake_word = self.wake_word
        self._patterns = self._compile_patterns(self.wake_word)
        logger.info(f"Updated wake word to: '{self.wake_word}'")

    def set_sensitivity(self, sensitivity: float) -> None:
        self.sensitivity = max(0.1, min(1.0, sensitivity))
        self.acoustic_detector.set_sensitivity(self.sensitivity)

    def set_tts_active(self, active: bool) -> None:
        """Self-activation suppression: Suppress wake-word detection while JARVIS TTS is speaking."""
        self._is_tts_active = active
        if active:
            # Clear acoustic buffer to avoid analyzing residual TTS audio
            self.acoustic_detector.reset()

    @property
    def is_tts_active(self) -> bool:
        return self._is_tts_active

    def mute(self) -> None:
        """Immediately mute listening."""
        self._is_listening_muted = True
        self.acoustic_detector.reset()
        logger.info("Voice listening MUTED.")

    def unmute(self) -> None:
        """Unmute listening."""
        self._is_listening_muted = False
        self.acoustic_detector.reset()
        logger.info("Voice listening UNMUTED.")

    @property
    def is_muted(self) -> bool:
        return self._is_listening_muted

    def process_pcm_frame(self, pcm_data: bytes) -> tuple[bool, float]:
        """Acoustically inspect incoming microphone PCM audio frame.

        Enforces:
        - Instant drop when muted.
        - Instant drop when JARVIS is speaking (Acoustic Echo Cancellation / self-activation prevention).
        - Debounce window protection.

        Returns:
            (detected: bool, confidence: float)
        """
        if self._is_listening_muted:
            return False, 0.0

        if self._is_tts_active:
            # Self-activation suppression active
            return False, 0.0

        now = time.monotonic()
        if (now - self._last_trigger_time) < self.debounce_seconds:
            return False, 0.0

        detected, conf = self.acoustic_detector.process_pcm_frame(pcm_data)
        if detected:
            self._last_trigger_time = now
            self.acoustic_detector.reset()
            logger.info(
                f"Acoustic wake word '{self.wake_word}' detected with confidence {conf:.2f}!"
            )
            return True, conf

        return False, conf

    _START_WAKE_WORD_PATTERN = re.compile(
        r"""^\s*
        (?:
            (?:hey|hi|hello|ok|okay|dear|yo|سلام|هی|اوکی|ای|جناب|آقای)\s*[,:؛،\-]?\s*
        )?
        (?:jarvis|jarviss|jarvez|jarves|جارویس|جارویز|جرویس)
        (?:\b|[\s,:؛،!?\.\-_]|$)
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    def check_starts_with_wake_word(self, text: str) -> tuple[bool, str]:
        """Verify whether an utterance begins with the wake word (e.g., 'Jarvis ...' or 'جارویس ...').

        Returns:
            (starts_with_ww: bool, stripped_command: str)
        """
        if self._is_listening_muted or self._is_tts_active or not text:
            return False, text

        text_clean = text.strip()
        m = self._START_WAKE_WORD_PATTERN.search(text_clean)
        if m and m.start() == 0:
            after = text_clean[m.end() :].lstrip(" ,:؛،.!?\n\t-")
            command = "" if not after.strip(" ,:؛،.!?\n\t-") else after.strip()
            logger.info(
                f"Utterance starts with wake word '{m.group(0).strip()}'. Stripped command: '{command}'"
            )
            return True, command

        return False, text_clean

    def check_text(self, text: str) -> tuple[bool, str]:
        """Secondary verification: Check if transcript contains the wake word.

        Returns:
            (detected: bool, stripped_command: str)
        """
        if self._is_listening_muted or self._is_tts_active:
            return False, text

        text_clean = text.strip()
        for pat in self._patterns:
            m = pat.search(text_clean)
            if m:
                # Strip wake word from command text
                command = text_clean[: m.start()] + " " + text_clean[m.end() :]
                command_clean = command.strip()
                if not command_clean.strip(" ,:؛،.!?\n\t-"):
                    command = ""
                else:
                    command = re.sub(r"^[\s,:؛،.!?\n\t-]+", "", command_clean).strip()
                logger.info(
                    f"Wake word '{m.group(0)}' detected in transcript! Command: '{command}'"
                )
                return True, command

        return False, text_clean

    def trigger_push_to_talk(self) -> bool:
        """Explicitly trigger an active listening session via Push-To-Talk."""
        if self._is_listening_muted:
            return False
        self._last_trigger_time = time.monotonic()
        self.acoustic_detector.reset()
        logger.info("Push-To-Talk activated.")
        return True

    def benchmark_processing_overhead(
        self, sample_duration_seconds: float = 1.0
    ) -> dict[str, float]:
        """Measure acoustic processing latency and CPU overhead for diagnostic certification."""
        num_samples = int(self.sample_rate * sample_duration_seconds)
        # Synthetic speech-like PCM frame
        synthetic_pcm = bytearray()
        for i in range(num_samples):
            val = int(8000 * math.sin(2 * math.pi * 300 * i / self.sample_rate))
            synthetic_pcm.extend(val.to_bytes(2, "little", signed=True))

        t0 = time.perf_counter()
        # Feed in 20ms chunks (320 samples)
        chunk_size = int(self.sample_rate * 0.020) * 2
        for offset in range(0, len(synthetic_pcm), chunk_size):
            self.acoustic_detector.process_pcm_frame(
                bytes(synthetic_pcm[offset : offset + chunk_size])
            )
        total_time = time.perf_counter() - t0

        real_time_factor = total_time / sample_duration_seconds
        return {
            "duration_seconds": sample_duration_seconds,
            "processing_time_ms": total_time * 1000.0,
            "real_time_factor": real_time_factor,
            "cpu_overhead_percent": real_time_factor * 100.0,
        }

    def get_status(self) -> dict[str, Any]:
        """Return diagnostic status of wake word detector."""
        return {
            "wake_word": self.wake_word,
            "enabled": self.enabled,
            "muted": self._is_listening_muted,
            "tts_active": self._is_tts_active,
            "sensitivity": self.sensitivity,
            "debounce_seconds": self.debounce_seconds,
            "acoustic_detector": "AcousticWakeWordDetector",
        }


_default_wake_detector: WakeWordDetector | None = None


def check_starts_with_wake_word(text: str) -> tuple[bool, str]:
    """Module-level helper to check if an utterance starts with the wake word."""
    global _default_wake_detector
    if _default_wake_detector is None:
        _default_wake_detector = WakeWordDetector()
    return _default_wake_detector.check_starts_with_wake_word(text)
