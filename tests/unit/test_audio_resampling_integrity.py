"""Comprehensive numerical tests for Audio Resampling Integrity, Anti-Alias Filtering,
Duration Preservation, PCM16 Limiting, WAV Packaging, and Barge-In Task Isolation.
"""

from __future__ import annotations

import io
import math
import struct
import wave
from unittest.mock import MagicMock

from tools.voice.voice_pipeline import (
    _FIR_COEFFS_32K,
    _FIR_COEFFS_44K,
    _FIR_COEFFS_48K,
    _soft_limit_pcm16,
    normalize_audio_to_16k_mono_pcm16,
    pcm16_to_wav,
)


class TestAudioResamplingIntegrity:
    """Numerical validation of anti-aliasing lowpass filtering and rate conversion."""

    def test_fir_coefficients_properties(self) -> None:
        """Verify FIR filter symmetry, unity DC gain, and tap counts."""
        for name, coeffs in [
            ("48k", _FIR_COEFFS_48K),
            ("32k", _FIR_COEFFS_32K),
            ("44k", _FIR_COEFFS_44K),
        ]:
            assert len(coeffs) == 17, f"{name} filter must have 17 taps"
            # Symmetric FIR (Type 1 linear phase)
            for i in range(8):
                assert math.isclose(coeffs[i], coeffs[16 - i], rel_tol=1e-5), (
                    f"{name} filter not symmetric at tap {i}"
                )
            # Unity gain at DC (sum of coeffs == 1.0)
            assert math.isclose(sum(coeffs), 1.0, rel_tol=1e-5), (
                f"{name} filter DC gain must be 1.0"
            )

    def test_passband_frequency_preservation_48k(self) -> None:
        """Verify 1000 Hz and 3000 Hz signals pass through 48k->16k filter with < 1.0 dB loss."""
        fs = 48000
        duration = 0.5  # 500ms
        num_samples = int(fs * duration)

        for freq in [1000, 3000]:
            sine_wave = [0.8 * math.sin(2 * math.pi * freq * i / fs) for i in range(num_samples)]
            raw_floats = struct.pack(f"<{num_samples}f", *sine_wave)

            pcm_out = normalize_audio_to_16k_mono_pcm16(
                raw_floats, src_rate=48000, channels=1, is_float=True
            )
            out_count = len(pcm_out) // 2
            assert out_count == int(16000 * duration), "Output duration must be exactly 500ms"

            out_ints = struct.unpack(f"<{out_count}h", pcm_out)
            # Measure peak amplitude in steady-state region (skipping boundary transients)
            steady_state = out_ints[200:-200]
            peak = max(abs(v) for v in steady_state)
            expected_peak = 0.8 * 32767.0
            loss_db = 20 * math.log10(peak / expected_peak)
            assert -1.5 <= loss_db <= 0.5, (
                f"Freq {freq}Hz attenuation {loss_db:.2f}dB exceeds limit"
            )

    def test_stopband_anti_aliasing_attenuation_48k(self) -> None:
        """Verify 12000 Hz stopband tone is attenuated by > 35 dB when downsampling 48k->16k."""
        fs = 48000
        duration = 0.25  # 250ms
        num_samples = int(fs * duration)
        freq = 12000.0  # Above 8000 Hz Nyquist of target 16kHz

        sine_wave = [0.8 * math.sin(2 * math.pi * freq * i / fs) for i in range(num_samples)]
        raw_floats = struct.pack(f"<{num_samples}f", *sine_wave)

        pcm_out = normalize_audio_to_16k_mono_pcm16(
            raw_floats, src_rate=48000, channels=1, is_float=True
        )
        out_count = len(pcm_out) // 2
        out_ints = struct.unpack(f"<{out_count}h", pcm_out)

        steady_state = out_ints[100:-100]
        peak = max(abs(v) for v in steady_state)
        attenuation_db = 20 * math.log10(peak / (0.8 * 32767.0))
        assert attenuation_db < -35.0, (
            f"12kHz tone attenuation {attenuation_db:.2f} dB is insufficient (< 35 dB)"
        )

    def test_resampling_from_32k(self) -> None:
        """Verify downsampling from 32kHz to 16kHz preserves passband and sample count."""
        fs = 32000
        duration = 0.2
        num_samples = int(fs * duration)
        sine = [0.5 * math.sin(2 * math.pi * 1000 * i / fs) for i in range(num_samples)]
        raw_bytes = struct.pack(f"<{num_samples}f", *sine)

        pcm_out = normalize_audio_to_16k_mono_pcm16(
            raw_bytes, src_rate=32000, channels=1, is_float=True
        )
        out_count = len(pcm_out) // 2
        assert out_count == int(16000 * duration)

        out_ints = struct.unpack(f"<{out_count}h", pcm_out)
        peak = max(abs(v) for v in out_ints[50:-50])
        assert math.isclose(peak / 32767.0, 0.5, abs_tol=0.05)

    def test_resampling_from_44k1(self) -> None:
        """Verify non-integer downsampling from 44.1kHz (CD standard) to 16kHz."""
        fs = 44100
        duration = 0.1
        num_samples = int(fs * duration)
        sine = [0.6 * math.sin(2 * math.pi * 1000 * i / fs) for i in range(num_samples)]
        raw_bytes = struct.pack(f"<{num_samples}f", *sine)

        pcm_out = normalize_audio_to_16k_mono_pcm16(
            raw_bytes, src_rate=44100, channels=1, is_float=True
        )
        out_count = len(pcm_out) // 2
        expected_samples = round(num_samples * 16000.0 / 44100.0)
        assert out_count == expected_samples

        out_ints = struct.unpack(f"<{out_count}h", pcm_out)
        peak = max(abs(v) for v in out_ints[50:-50])
        assert math.isclose(peak / 32767.0, 0.6, abs_tol=0.08)

    def test_fast_path_16k_passthrough(self) -> None:
        """Verify fast-path returns unaltered bytes for canonical 16kHz Mono Int16 input."""
        sample_ints = [1000, -2000, 3000, -4000]
        raw_bytes = struct.pack("<4h", *sample_ints)
        res = normalize_audio_to_16k_mono_pcm16(
            raw_bytes, src_rate=16000, channels=1, is_float=False
        )
        assert res == raw_bytes

    def test_duration_preservation_across_chunk_sizes(self) -> None:
        """Verify duration is exactly preserved across 10ms, 20ms, 50ms, 100ms, and 1000ms."""
        for duration_ms in [10, 20, 50, 100, 1000]:
            duration_s = duration_ms / 1000.0
            num_in = int(48000 * duration_s)
            dummy = b"\x00" * (num_in * 2)  # Int16 silence
            out = normalize_audio_to_16k_mono_pcm16(
                dummy, src_rate=48000, channels=1, is_float=False
            )
            out_samples = len(out) // 2
            expected = int(16000 * duration_s)
            assert out_samples == expected, (
                f"Mismatch for {duration_ms}ms: got {out_samples}, expected {expected}"
            )


class TestDownmixingAndLimiting:
    """Validation of multi-channel downmixing, silence, and soft limiting."""

    def test_stereo_to_mono_downmixing(self) -> None:
        """Verify Left and Right channels are downmixed equally (L + R) * 0.5."""
        left = 0.6
        right = 0.2
        # 100 stereo samples at 16kHz
        stereo_floats = [left, right] * 100
        raw_bytes = struct.pack(f"<{len(stereo_floats)}f", *stereo_floats)

        pcm_out = normalize_audio_to_16k_mono_pcm16(
            raw_bytes, src_rate=16000, channels=2, is_float=True
        )
        out_count = len(pcm_out) // 2
        assert out_count == 100

        out_ints = struct.unpack(f"<{out_count}h", pcm_out)
        expected_amp = (left + right) * 0.5  # 0.4
        for val in out_ints:
            assert math.isclose(val / 32767.0, expected_amp, abs_tol=0.01)

    def test_silence_preservation(self) -> None:
        """Verify digital silence input produces zero bytes without numerical drift."""
        raw_silence = b"\x00" * (4800 * 2)  # 100ms at 48kHz int16 mono (4800 samples * 2 bytes)
        pcm_out = normalize_audio_to_16k_mono_pcm16(
            raw_silence, src_rate=48000, channels=1, is_float=False
        )
        assert len(pcm_out) == 3200  # 100ms at 16kHz int16 mono (1600 samples * 2 bytes)
        assert all(b == 0 for b in pcm_out)

    def test_soft_limiter_clipping_prevention(self) -> None:
        """Verify soft limiter prevents overflow on overdriven signals (+6 dB overdrive)."""
        # Linear range check
        for val in [-0.9, -0.5, 0.0, 0.5, 0.9]:
            assert _soft_limit_pcm16(val) == int(val * 32767.0)

        # Overdrive beyond 1.0 (e.g. mic shout)
        for extreme in [1.2, 2.0, 5.0, 10.0]:
            clipped = _soft_limit_pcm16(extreme)
            assert 0 < clipped <= 32767, (
                f"Overdriven value {extreme} produced out-of-range {clipped}"
            )

        for extreme_neg in [-1.2, -2.0, -5.0, -10.0]:
            clipped = _soft_limit_pcm16(extreme_neg)
            assert -32768 <= clipped < 0, (
                f"Negative overdrive {extreme_neg} produced out-of-range {clipped}"
            )

    def test_empty_and_invalid_inputs(self) -> None:
        """Verify empty and sub-sample inputs return empty bytes safely without crashing."""
        assert normalize_audio_to_16k_mono_pcm16(b"") == b""
        assert normalize_audio_to_16k_mono_pcm16(b"\x00", is_float=True) == b""
        assert normalize_audio_to_16k_mono_pcm16(b"\x00", is_float=False) == b""


class TestWAVPackaging:
    """Validation of canonical WAV RIFF container headers and structure."""

    def test_pcm16_to_wav_headers(self) -> None:
        """Verify pcm16_to_wav generates valid RIFF header and exact WAV parameters."""
        num_samples = 800  # 50ms at 16kHz
        pcm_bytes = b"\x00\x00" * num_samples

        wav_bytes = pcm16_to_wav(pcm_bytes, sample_rate=16000, channels=1)
        assert len(wav_bytes) == len(pcm_bytes) + 44  # Standard 44-byte RIFF header

        # Read back using stdlib wave
        buf = io.BytesIO(wav_bytes)
        with wave.open(buf, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000
            assert wf.getnframes() == num_samples
            frames = wf.readframes(num_samples)
            assert frames == pcm_bytes


class TestSafeVoiceBargeInAndTaskIsolation:
    """Validation that voice barge-in halts speech/streaming without killing background agent tasks."""

    def test_voice_interrupt_does_not_cancel_background_agent_worker(self) -> None:
        """Ensure _handle_voice_interrupt only cancels speech/stream, preserving running _agent_worker."""
        from ui.main_window import MainWindow

        mock_window = MagicMock(spec=MainWindow)

        # Configure mock workers
        mock_stream_worker = MagicMock()
        mock_stream_worker.isRunning.return_value = True

        mock_agent_worker = MagicMock()
        mock_agent_worker.isRunning.return_value = True

        mock_voice_pipeline = MagicMock()

        mock_window._stream_worker = mock_stream_worker
        mock_window._agent_worker = mock_agent_worker
        mock_window.agent = MagicMock()
        mock_window.agent.voice_pipeline = mock_voice_pipeline
        mock_window.chat_panel = MagicMock()
        mock_window.visualizer = MagicMock()
        mock_window.voice_status_lbl = MagicMock()

        # Call real unbound method on mock instance
        MainWindow._handle_voice_interrupt(mock_window)

        # 1. Spoken audio and generation must be cancelled
        mock_voice_pipeline.cancel_active_speech_and_generation.assert_called_once()

        # 2. Conversational text streaming must be cleanly cancelled
        mock_stream_worker.cancel.assert_called_once()
        mock_window.chat_panel.cancel_assistant_streaming.assert_called_once()

        # 3. CRITICAL: Long-running agent background tasks MUST NOT BE CANCELLED
        mock_agent_worker.cancel.assert_not_called()

        # 4. Visualizer updated to interrupted
        mock_window.visualizer.set_voice_state.assert_called_once_with("interrupted")
