"""Pydantic and dataclass models for JARVIS Phase 6 Windows Control subsystem."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class WindowState(StrEnum):
    """Visual state of a desktop window."""

    NORMAL = "normal"
    MINIMIZED = "minimized"
    MAXIMIZED = "maximized"
    HIDDEN = "hidden"


class WindowInfo(BaseModel):
    """Detailed information about an open top-level desktop window."""

    hwnd: int = Field(description="Win32 Window Handle integer")
    title: str = Field(description="Window text/title")
    class_name: str = Field(description="Win32 Window Class Name")
    pid: int = Field(description="Process ID owning the window")
    process_name: str = Field(description="Executable process name")
    state: WindowState = Field(
        default=WindowState.NORMAL, description="Current window placement state"
    )
    is_visible: bool = Field(default=True, description="Whether window is visible")
    rect: tuple[int, int, int, int] | None = Field(
        default=None, description="Window bounds (left, top, right, bottom)"
    )
    creation_time: int | None = Field(
        default=None, description="Process creation timestamp to defeat PID reuse"
    )


class AppInfo(BaseModel):
    """Metadata for an application resolved from the allowlist or catalog."""

    app_id: str = Field(description="Normalized application identifier (e.g. 'notepad')")
    display_name: str = Field(description="Human-friendly application name")
    executable_path: str = Field(description="Resolved canonical filesystem path to executable")
    is_installed: bool = Field(description="Whether executable exists on disk")
    is_running: bool = Field(
        default=False, description="Whether one or more process instances are running"
    )
    running_pids: list[int] = Field(default_factory=list, description="List of running process IDs")


class ProcessMetadata(BaseModel):
    """Process execution metadata for a running Windows task."""

    pid: int = Field(description="Process Identifier")
    name: str = Field(description="Executable image name")
    executable_path: str | None = Field(default=None, description="Full image path if accessible")
    window_count: int = Field(default=0, description="Number of top-level windows owned")
    is_elevated: bool | None = Field(
        default=None, description="Whether process runs with elevated privileges"
    )


class AudioState(BaseModel):
    """Current output audio endpoint status and operation verification."""

    volume_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Master output volume percentage (0.0 - 100.0)",
    )
    is_muted: bool = Field(default=False, description="Whether master output is currently muted")
    device_name: str = Field(
        default="Default Multimedia Output", description="Audio output device name"
    )
    supported: bool = Field(
        default=True, description="Whether Windows Core Audio endpoint is available"
    )
    success: bool = Field(
        default=True, description="Whether the audio operation succeeded and was verified"
    )
    operation: str = Field(
        default="get_status",
        description="Operation type: 'mute', 'unmute', 'set_volume', 'get_status'",
    )
    requested_value: Any = Field(default=None, description="Requested target value")
    actual_value: Any = Field(default=None, description="Actual observed state after operation")
    verified: bool = Field(
        default=True,
        description="Whether read-back state strictly matched requested state",
    )
    error_code: str | None = Field(default=None, description="Structured error code if failed")
    error_message: str | None = Field(
        default=None, description="Human-readable error explanation if failed"
    )


class AudioOperationResult(AudioState):
    """Structured result of a Windows audio operation with verification."""

    pass


class BrightnessState(BaseModel):
    """Physical monitor brightness status."""

    supported: bool = Field(
        description="Whether physical display brightness adjustment is supported"
    )
    brightness_percent: int | None = Field(
        default=None, ge=0, le=100, description="Current brightness percentage (0 - 100)"
    )
    min_brightness: int | None = Field(
        default=None, description="Minimum supported brightness level"
    )
    max_brightness: int | None = Field(
        default=None, description="Maximum supported brightness level"
    )
    monitor_description: str | None = Field(
        default=None, description="Monitor description from display driver"
    )
    error_reason: str | None = Field(
        default=None, description="Reason if brightness is unsupported on current hardware"
    )


class PowerState(BaseModel):
    """System battery and AC power status."""

    ac_line_status: str = Field(description="AC power state: 'online', 'offline', or 'unknown'")
    battery_percent: int = Field(ge=0, le=100, description="Battery percentage remaining (0-100)")
    battery_status: str = Field(
        description="Battery state: 'charging', 'discharging', 'no_battery', 'critical', or 'unknown'"
    )
    battery_life_time_seconds: int | None = Field(
        default=None, description="Estimated remaining battery life in seconds, or None"
    )
