"""Audio hardware device discovery and management for Windows 11.

Enumerates microphones and playback endpoints via QtMultimedia, supporting
device selection, health inspection, and fallback to default devices.
"""

from __future__ import annotations

from infrastructure.logging import get_logger
from tools.voice.models import AudioDeviceInfo

logger = get_logger("voice.device_manager")


class AudioDeviceManager:
    """Manages audio capture and playback device enumeration and selection."""

    def __init__(self) -> None:
        self._input_devices: list[AudioDeviceInfo] = []
        self._output_devices: list[AudioDeviceInfo] = []
        self._selected_input: str | None = None
        self._selected_output: str | None = None
        self.refresh_devices()

    def refresh_devices(self) -> None:
        """Query host system and enumerate available audio endpoints."""
        self._input_devices = []
        self._output_devices = []

        try:
            from PySide6.QtMultimedia import QMediaDevices

            # Enumerate Microphones
            default_in = QMediaDevices.defaultAudioInput()
            default_in_id = default_in.id().data().decode("utf-8", "ignore") if default_in else ""

            for dev in QMediaDevices.audioInputs():
                dev_id = dev.id().data().decode("utf-8", "ignore")
                dev_name = dev.description()
                is_def = dev_id == default_in_id or (
                    not default_in_id and len(self._input_devices) == 0
                )
                rates = dev.supportedSampleFormats()
                sample_rates = [16000, 44100, 48000] if rates else [16000]
                self._input_devices.append(
                    AudioDeviceInfo(
                        id=dev_id or dev_name,
                        name=dev_name,
                        is_default=is_def,
                        is_input=True,
                        sample_rates=sample_rates,
                        channels=dev.maximumChannelCount() or 1,
                    )
                )

            # Enumerate Speakers
            default_out = QMediaDevices.defaultAudioOutput()
            default_out_id = (
                default_out.id().data().decode("utf-8", "ignore") if default_out else ""
            )

            for dev in QMediaDevices.audioOutputs():
                dev_id = dev.id().data().decode("utf-8", "ignore")
                dev_name = dev.description()
                is_def = dev_id == default_out_id or (
                    not default_out_id and len(self._output_devices) == 0
                )
                self._output_devices.append(
                    AudioDeviceInfo(
                        id=dev_id or dev_name,
                        name=dev_name,
                        is_default=is_def,
                        is_input=False,
                        sample_rates=[44100, 48000],
                        channels=dev.maximumChannelCount() or 2,
                    )
                )
        except Exception as exc:
            logger.warning(
                f"QtMultimedia hardware device query failed (headless/mock environment): {exc}"
            )

        # Ensure at least default mock device if no physical device is detected (e.g. headless CI)
        if not self._input_devices:
            self._input_devices.append(
                AudioDeviceInfo(
                    id="default_mic",
                    name="Default Microphone (System)",
                    is_default=True,
                    is_input=True,
                )
            )
        if not self._output_devices:
            self._output_devices.append(
                AudioDeviceInfo(
                    id="default_speaker",
                    name="Default Speakers (System)",
                    is_default=True,
                    is_input=False,
                )
            )

        logger.debug(
            f"Audio devices discovered: {len(self._input_devices)} inputs, {len(self._output_devices)} outputs"
        )

    def list_input_devices(self) -> list[AudioDeviceInfo]:
        """Return all available input devices."""
        return self._input_devices.copy()

    def list_output_devices(self) -> list[AudioDeviceInfo]:
        """Return all available output devices."""
        return self._output_devices.copy()

    def get_selected_input(self) -> AudioDeviceInfo:
        """Return currently selected or default input device."""
        if self._selected_input:
            for d in self._input_devices:
                if d.id == self._selected_input or d.name == self._selected_input:
                    return d
        for d in self._input_devices:
            if d.is_default:
                return d
        return self._input_devices[0]

    def get_selected_output(self) -> AudioDeviceInfo:
        """Return currently selected or default output device."""
        if self._selected_output:
            for d in self._output_devices:
                if d.id == self._selected_output or d.name == self._selected_output:
                    return d
        for d in self._output_devices:
            if d.is_default:
                return d
        return self._output_devices[0]

    def set_input_device(self, device_identifier: str) -> bool:
        """Select input device by ID or name."""
        for d in self._input_devices:
            if d.id == device_identifier or d.name == device_identifier:
                self._selected_input = d.id
                logger.info(f"Selected audio input device: '{d.name}'")
                return True
        logger.warning(f"Audio input device not found: '{device_identifier}'")
        return False

    def set_output_device(self, device_identifier: str) -> bool:
        """Select output device by ID or name."""
        for d in self._output_devices:
            if d.id == device_identifier or d.name == device_identifier:
                self._selected_output = d.id
                logger.info(f"Selected audio output device: '{d.name}'")
                return True
        logger.warning(f"Audio output device not found: '{device_identifier}'")
        return False
