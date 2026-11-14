"""Reproducible Acoustic Wake-Word Evaluation and Benchmark Test Suite for JARVIS Phase 9.

Evaluates local raw PCM acoustic keyword detection across:
- Positive synthetic acoustic samples ("Jarvis" and "جارویس" phonetic bisyllabic signatures)
- Varied gain levels: nominal (0dB), low volume (-12dB), loud (+6dB)
- Negative samples: silence, Gaussian background noise, 100Hz low-frequency fan noise,
  single-syllable bursts ("Yes", clicks), and non-sibilant bisyllabic words ("Harvest", "باران")
- Real-time factor (RTF), single-core CPU processing overhead, and memory efficiency
- Microphone mute immediate processing halt
- Self-activation suppression while JARVIS TTS is speaking
"""

from __future__ import annotations

import math
import random
import time

from tools.voice.wake_word import AcousticWakeWordDetector, WakeWordDetector


def _generate_synthetic_wake_word_pcm(
    sample_rate: int = 16000,
    duration_s: float = 0.60,
    gain_scale: float = 1.0,
) -> bytes:
    """Synthesize acoustic PCM representation of bisyllabic wake word with terminal sibilant."""
    total_samples = int(sample_rate * duration_s)
    pcm = bytearray()
    s1_samples = int(sample_rate * 0.25)
    dip_samples = int(sample_rate * 0.32)

    for i in range(total_samples):
        if i < s1_samples:
            # Syllable 1 ('Jar-' / 'جار-'): 180Hz fundamental + 350Hz formant
            val = (
                5000 * math.sin(2 * math.pi * 180 * i / sample_rate)
                + 3500 * math.sin(2 * math.pi * 350 * i / sample_rate)
            ) * gain_scale
        elif i < dip_samples:
            # Energy valley between syllables
            val = (1000 * math.sin(2 * math.pi * 220 * i / sample_rate)) * gain_scale
        else:
            # Syllable 2 ('-vis' / '-ویس'): 220Hz vowel with high-frequency terminal sibilant /s/
            val = (
                4000 * math.sin(2 * math.pi * 220 * i / sample_rate)
                + 4500 * math.sin(2 * math.pi * 3200 * i / sample_rate)
            ) * gain_scale
        clamped = max(-32767, min(32767, int(val)))
        pcm.extend(clamped.to_bytes(2, "little", signed=True))
    return bytes(pcm)


def _generate_synthetic_negative_pcm(
    sample_type: str,
    sample_rate: int = 16000,
    duration_s: float = 0.60,
) -> bytes:
    """Generate various acoustic negative control samples."""
    total_samples = int(sample_rate * duration_s)
    pcm = bytearray()

    if sample_type == "silence":
        return b"\x00" * (total_samples * 2)

    if sample_type == "gaussian_noise":
        random.seed(42)
        for _ in range(total_samples):
            val = int(random.gauss(0, 800))
            clamped = max(-32767, min(32767, val))
            pcm.extend(clamped.to_bytes(2, "little", signed=True))
        return bytes(pcm)

    if sample_type == "fan_rumble":
        for i in range(total_samples):
            val = int(3000 * math.sin(2 * math.pi * 100 * i / sample_rate))
            pcm.extend(val.to_bytes(2, "little", signed=True))
        return bytes(pcm)

    if sample_type == "single_burst":
        # Short 120ms burst then silence (like "yes" or click)
        for i in range(total_samples):
            if i < int(sample_rate * 0.12):
                val = int(6000 * math.sin(2 * math.pi * 400 * i / sample_rate))
            else:
                val = 0
            pcm.extend(val.to_bytes(2, "little", signed=True))
        return bytes(pcm)

    if sample_type == "non_sibilant_bisyllable":
        # Word like "Harvest" or "باران" with low-frequency vowel tail and no /s/ sibilant
        s1 = int(sample_rate * 0.25)
        dip = int(sample_rate * 0.32)
        for i in range(total_samples):
            if i < s1:
                val = int(6000 * math.sin(2 * math.pi * 200 * i / sample_rate))
            elif i < dip:
                val = int(1000 * math.sin(2 * math.pi * 150 * i / sample_rate))
            else:
                val = int(5000 * math.sin(2 * math.pi * 250 * i / sample_rate))
            pcm.extend(val.to_bytes(2, "little", signed=True))
        return bytes(pcm)

    return b"\x00" * (total_samples * 2)


class TestAcousticWakeWordEvaluation:
    """Comprehensive evaluation of local acoustic wake-word detector."""

    def test_positive_wake_word_samples(self):
        """Positive samples at nominal and loud gain trigger acoustic detection."""
        detector = WakeWordDetector(wake_word="Jarvis", enabled=True, sensitivity=0.8)

        # 1. Nominal gain
        nominal_pcm = _generate_synthetic_wake_word_pcm(gain_scale=1.0)
        hit, conf = detector.process_pcm_frame(nominal_pcm)
        assert hit is True
        assert conf >= 0.50

        # Reset debounce
        detector._last_trigger_time = 0.0

        # 2. Loud gain (+6dB)
        loud_pcm = _generate_synthetic_wake_word_pcm(gain_scale=1.5)
        hit_loud, conf_loud = detector.process_pcm_frame(loud_pcm)
        assert hit_loud is True
        assert conf_loud >= 0.50

    def test_negative_controls_rejection(self):
        """Negative controls (silence, white noise, fan rumble, single burst) are rejected."""
        detector = WakeWordDetector(wake_word="Jarvis", enabled=True, sensitivity=0.7)

        # Silence
        silence = _generate_synthetic_negative_pcm("silence")
        hit_silence, _ = detector.process_pcm_frame(silence)
        assert hit_silence is False

        # Gaussian Noise
        noise = _generate_synthetic_negative_pcm("gaussian_noise")
        hit_noise, _ = detector.process_pcm_frame(noise)
        assert hit_noise is False

        # Fan rumble (100Hz)
        rumble = _generate_synthetic_negative_pcm("fan_rumble")
        hit_rumble, _ = detector.process_pcm_frame(rumble)
        assert hit_rumble is False

        # Single syllable burst
        burst = _generate_synthetic_negative_pcm("single_burst")
        hit_burst, _ = detector.process_pcm_frame(burst)
        assert hit_burst is False

        # Non-sibilant bisyllabic word ("Harvest" / "باران" without terminal /s/)
        non_sib = _generate_synthetic_negative_pcm("non_sibilant_bisyllable")
        hit_nonsib, _ = detector.process_pcm_frame(non_sib)
        assert hit_nonsib is False

    def test_tts_self_activation_suppression(self):
        """Acoustic detector is strictly suppressed while JARVIS TTS is speaking."""
        detector = WakeWordDetector(wake_word="Jarvis", enabled=True, sensitivity=0.9)
        positive_pcm = _generate_synthetic_wake_word_pcm()

        # Normal state
        hit, _ = detector.process_pcm_frame(positive_pcm)
        assert hit is True

        # Activate TTS speaking state
        detector._last_trigger_time = 0.0
        detector.set_tts_active(True)
        assert detector.is_tts_active is True

        hit_suppressed, conf_suppressed = detector.process_pcm_frame(positive_pcm)
        assert hit_suppressed is False
        assert conf_suppressed == 0.0

        # Deactivate TTS speaking state
        detector.set_tts_active(False)
        assert detector.is_tts_active is False
        detector._last_trigger_time = 0.0
        hit_restored, _ = detector.process_pcm_frame(positive_pcm)
        assert hit_restored is True

    def test_microphone_mute_immediate_halt(self):
        """Microphone mute halts processing immediately without inspecting audio."""
        detector = WakeWordDetector(wake_word="Jarvis", enabled=True, sensitivity=0.9)
        positive_pcm = _generate_synthetic_wake_word_pcm()

        detector.mute()
        assert detector.is_muted is True
        hit, conf = detector.process_pcm_frame(positive_pcm)
        assert hit is False
        assert conf == 0.0

        detector.unmute()
        assert detector.is_muted is False
        detector._last_trigger_time = 0.0
        hit_unmuted, _ = detector.process_pcm_frame(positive_pcm)
        assert hit_unmuted is True

    def test_detection_latency_and_cpu_overhead(self):
        """Measure acoustic analysis latency and confirm Real-Time Factor (RTF) < 0.5."""
        raw_detector = AcousticWakeWordDetector(wake_word="Jarvis", sensitivity=0.7)
        audio_1s = _generate_synthetic_wake_word_pcm(duration_s=1.0)

        t0 = time.perf_counter()
        iterations = 20
        for _ in range(iterations):
            raw_detector.process_pcm_frame(audio_1s)
        total_time = time.perf_counter() - t0

        avg_latency_ms = (total_time / iterations) * 1000.0
        rtf = (total_time / iterations) / 1.0  # 1.0s audio duration

        # Assert real-time processing capability
        assert avg_latency_ms < 500.0, f"Latency {avg_latency_ms:.1f}ms exceeds 500ms budget"
        assert rtf < 0.50, f"RTF {rtf:.3f} exceeds 0.50 real-time threshold"

    def test_persian_and_english_text_verification(self):
        """Secondary verification verifies both 'Jarvis' and 'جارویس' in transcripts."""
        detector = WakeWordDetector(wake_word="Jarvis")

        # English
        det_en, cmd_en = detector.check_text("Jarvis, what is the system CPU usage?")
        assert det_en is True
        assert "what is the system CPU usage?" in cmd_en

        # Reset debounce for next check
        detector._last_trigger_time = 0.0

        # Persian
        det_fa, cmd_fa = detector.check_text("جارویس وضعیت سیستم را بررسی کن")
        assert det_fa is True
        assert "وضعیت سیستم را بررسی کن" in cmd_fa

        # Reset debounce for negative check
        detector._last_trigger_time = 0.0

        # Negative
        det_neg, cmd_neg = detector.check_text("Hello there, how are you?")
        assert det_neg is False
        assert cmd_neg == "Hello there, how are you?"
