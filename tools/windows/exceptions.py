"""Typed exception hierarchy for JARVIS Phase 6 Windows Control subsystem."""

from __future__ import annotations


class WindowsControlError(Exception):
    """Base exception for all Windows desktop control errors."""


class TargetValidationError(WindowsControlError):
    """Raised when an operation target (PID, HWND, application) fails validation."""


class ProtectedTargetError(WindowsControlError):
    """Raised when an operation attempts to target a critical OS, security, or system process/window."""


class OperationUnsupportedError(WindowsControlError):
    """Raised when a requested hardware or OS capability is unsupported by the platform/display."""


class ApplicationNotFoundError(WindowsControlError):
    """Raised when a requested application is not found in the allowlist or on disk."""


class WindowNotFoundError(WindowsControlError):
    """Raised when a specified window handle or title cannot be located."""


class AudioEndpointError(WindowsControlError):
    """Raised when Windows Core Audio endpoint is inaccessible or fails to respond."""


class ComApartmentMismatchError(AudioEndpointError):
    """Raised when COM library cannot be initialized due to an incompatible apartment mode (RPC_E_CHANGED_MODE)."""


class DisplayControlError(WindowsControlError):
    """Raised when display brightness control encounters an error or is unsupported."""


class PowerControlError(WindowsControlError):
    """Raised when power state query or power transition fails."""
