"""Real Windows Core Audio integration test with independent read-back and guaranteed rollback."""

from __future__ import annotations

import contextlib
import os

import pytest

from tools.windows.windows_service import WindowsControlService


@pytest.mark.skipif(os.name != "nt", reason="Windows-specific native tests")
def test_real_windows_audio_full_verification_and_restoration() -> None:
    """Execute real Mute, Unmute, and Volume on default playback endpoint with independent read-back."""
    svc = WindowsControlService()

    # 1. Read and save original state
    try:
        initial_status = svc.get_audio_status()
        if not initial_status.supported:
            pytest.skip("Windows Core Audio default playback endpoint is not available.")
    except Exception as exc:
        pytest.skip(f"Windows Core Audio default playback endpoint is not available: {exc}")

    orig_volume = initial_status.volume_percent
    orig_muted = initial_status.is_muted

    try:
        # 2. Execute Mute & Independently Verify
        mute_res = svc.set_mute(True)
        assert mute_res.success is True
        assert mute_res.verified is True
        assert mute_res.is_muted is True

        read_back_muted = svc.get_audio_status()
        assert read_back_muted.is_muted is True, (
            "Independent read-back verification failed for Mute=True"
        )

        # 3. Execute Unmute & Independently Verify
        unmute_res = svc.set_mute(False)
        assert unmute_res.success is True
        assert unmute_res.verified is True
        assert unmute_res.is_muted is False

        read_back_unmuted = svc.get_audio_status()
        assert read_back_unmuted.is_muted is False, (
            "Independent read-back verification failed for Mute=False"
        )

        # 4. Change Volume to safe test value (adjust by ±2.0%)
        delta = 2.0 if orig_volume <= 90.0 else -2.0
        test_vol = max(0.0, min(100.0, orig_volume + delta))

        vol_res = svc.set_volume(test_vol)
        assert vol_res.success is True
        assert vol_res.verified is True
        assert abs(vol_res.volume_percent - test_vol) <= 2.0

        read_back_vol = svc.get_audio_status()
        assert abs(read_back_vol.volume_percent - test_vol) <= 2.0, (
            "Independent read-back verification failed for Volume"
        )

    finally:
        # 5. Guaranteed restoration in finally block
        with contextlib.suppress(Exception):
            svc.set_volume(orig_volume)
            svc.set_mute(orig_muted)

    # 6. Verify original state restored
    restored = svc.get_audio_status()
    assert abs(restored.volume_percent - orig_volume) <= 2.0
    assert restored.is_muted == orig_muted
