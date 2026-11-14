"""Typed exception hierarchy for JARVIS Phase 7 Browser Agent subsystem."""

from __future__ import annotations


class BrowserError(Exception):
    """Base exception for all browser automation errors."""


class BrowserNotInitializedError(BrowserError):
    """Raised when a browser operation is attempted before initialization."""


class BrowserNavigationError(BrowserError):
    """Raised when page navigation fails (timeout, network, invalid URL)."""


class BrowserTimeoutError(BrowserError):
    """Raised when a browser operation exceeds the configured timeout."""


class BrowserSecurityError(BrowserError):
    """Raised when a browser operation is blocked by security policy."""


class URLValidationError(BrowserSecurityError):
    """Raised when a URL fails security validation (blocked scheme, private IP, etc.)."""


class BrowserTabLimitError(BrowserError):
    """Raised when the maximum number of open tabs has been reached."""


class BrowserCrashError(BrowserError):
    """Raised when the browser process crashes or becomes unresponsive."""


class BrowserInteractionError(BrowserError):
    """Raised when a DOM interaction (click, fill, scroll) fails."""
