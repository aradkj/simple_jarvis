"""Target identity validation and protected system boundaries for Windows Control."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path
from typing import ClassVar

from infrastructure.logging import get_logger
from tools.windows.exceptions import ProtectedTargetError, TargetValidationError

logger = get_logger("windows.target_validation")


class TargetValidator:
    """Enforces conservative target security rules, anti-tampering, and protected process boundaries."""

    # Security-critical OS, credential, and antimalware processes that must NEVER be terminated or altered
    PROTECTED_PROCESSES: ClassVar[frozenset[str]] = frozenset(
        {
            # Windows Subsystem & Session Core
            "smss.exe",
            "csrss.exe",
            "wininit.exe",
            "winlogon.exe",
            "services.exe",
            "lsass.exe",
            "lsm.exe",
            "dwm.exe",
            "svchost.exe",
            "sihost.exe",
            "fontdrvhost.exe",
            "runtimebroker.exe",
            # Windows Shell Infrastructure
            "shellexperiencehost.exe",
            "startmenuexperiencehost.exe",
            "searchhost.exe",
            "lockapp.exe",
            "logonui.exe",
            # Microsoft Defender & Security Infrastructure
            "msmpeng.exe",
            "nissrv.exe",
            "securityhealthservice.exe",
            "smartscreen.exe",
            "sgrmbroker.exe",
            "mpssvc.exe",
            # JARVIS Process itself
            "python.exe",
            "pythonw.exe",
        }
    )

    # Protected window classes corresponding to desktop shell surfaces and secure dialogs
    PROTECTED_WINDOW_CLASSES: ClassVar[frozenset[str]] = frozenset(
        {
            "Shell_TrayWnd",  # Windows Taskbar
            "Shell_SecondaryTrayWnd",  # Multi-monitor Taskbars
            "Progman",  # Desktop Background Manager
            "WorkerW",  # Desktop Window Worker
            "Windows.UI.Core.CoreWindow",  # UWP Shell Windows (Start Menu, Notifications)
            "LockApp",  # Windows Lock Screen
            "LogonUI",  # Logon Screen
            "Credential Dialog Xaml Host",  # Windows UAC / Credential Prompt
            "NativeHWNDHost",  # System Dialog Host
        }
    )

    # Legitimate root directories for executable discovery
    TRUSTED_EXE_ROOTS: ClassVar[tuple[Path, ...]] = (
        Path(os.environ.get("SYSTEMROOT", r"C:\Windows")),
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"
        if os.environ.get("LOCALAPPDATA")
        else Path(r"C:\Users"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WindowsApps"
        if os.environ.get("LOCALAPPDATA")
        else Path(r"C:\Users"),
    )

    @classmethod
    def get_process_creation_time(cls, pid: int) -> int | None:
        """Query kernel creation time of a process to defeat PID reuse attacks.

        Returns:
            64-bit integer timestamp (FILETIME) or None if inaccessible.
        """
        if pid <= 4:
            return None

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        PROCESS_QUERY_INFORMATION = 0x0400

        kernel32 = ctypes.windll.kernel32
        h_process = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, wintypes.DWORD(pid)
        )
        if not h_process:
            h_process = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, wintypes.DWORD(pid))
        if not h_process:
            return None

        try:
            creation_time = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            if kernel32.GetProcessTimes(
                h_process,
                ctypes.byref(creation_time),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                return (creation_time.dwHighDateTime << 32) | creation_time.dwLowDateTime
            return None
        finally:
            kernel32.CloseHandle(h_process)

    @classmethod
    def is_protected_process(cls, process_name: str) -> bool:
        """Check whether a process name matches a protected system or security binary."""
        base_name = Path(process_name).name.lower().strip()
        return base_name in cls.PROTECTED_PROCESSES

    @classmethod
    def validate_process_target(
        cls,
        pid: int,
        process_name: str,
        expected_creation_time: int | None = None,
    ) -> None:
        """Verify process target is not protected and can be safely managed."""
        if pid <= 4:
            raise ProtectedTargetError(
                f"PID {pid} is a core Windows kernel or idle process and cannot be targeted."
            )

        if cls.is_protected_process(process_name):
            raise ProtectedTargetError(
                f"Process '{process_name}' (PID: {pid}) is a protected Windows system/security component. "
                "Operations against protected targets are strictly blocked."
            )

        if expected_creation_time is not None:
            actual_time = cls.get_process_creation_time(pid)
            if actual_time is not None and actual_time != expected_creation_time:
                raise TargetValidationError(
                    f"Process creation time mismatch for PID {pid} (expected {expected_creation_time}, "
                    f"got {actual_time}). PID was likely reused by a different process."
                )

    @classmethod
    def is_protected_window_class(cls, class_name: str) -> bool:
        """Check whether a Win32 window class represents a protected system surface."""
        return class_name.strip() in cls.PROTECTED_WINDOW_CLASSES

    @classmethod
    def validate_window_handle(
        cls,
        hwnd: int,
        expected_pid: int | None = None,
        class_name: str | None = None,
        expected_creation_time: int | None = None,
    ) -> None:
        """Verify that a Win32 HWND is valid, not destroyed, and not a protected surface."""
        # 1. Check window class first (reject protected shell surfaces immediately)
        if class_name is not None and cls.is_protected_window_class(class_name):
            raise ProtectedTargetError(
                f"Window handle {hwnd} belongs to protected shell class '{class_name}'. "
                "Operations against desktop shell infrastructure are strictly prohibited."
            )

        if not hwnd or hwnd <= 0:
            raise TargetValidationError(f"Invalid window handle integer: {hwnd}")

        user32 = ctypes.windll.user32
        if not user32.IsWindow(wintypes.HWND(hwnd)):
            raise TargetValidationError(
                f"Window handle {hwnd} is stale or does not exist on the desktop."
            )

        # Re-check process ID
        actual_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(actual_pid))
        if expected_pid is not None and actual_pid.value != expected_pid:
            raise TargetValidationError(
                f"Window handle {hwnd} belongs to PID {actual_pid.value}, but expected PID {expected_pid}. "
                "Target process changed or handle was reused."
            )

        if expected_creation_time is not None:
            actual_time = cls.get_process_creation_time(actual_pid.value)
            if actual_time is not None and actual_time != expected_creation_time:
                raise TargetValidationError(
                    f"Process creation time mismatch for PID {actual_pid.value} on window {hwnd} "
                    f"(expected {expected_creation_time}, got {actual_time}). "
                    "PID was likely reused by a different process."
                )

    @classmethod
    def validate_executable_path(cls, path_str: str) -> Path:
        """Verify executable path exists, is a valid .exe, resides in trusted location, and is not a script."""
        if not path_str or not path_str.strip():
            raise TargetValidationError("Executable path cannot be empty.")

        path = Path(path_str).resolve()
        if not path.is_file():
            raise TargetValidationError(f"Executable file does not exist at '{path}'.")

        if path.suffix.lower() != ".exe":
            raise TargetValidationError(
                f"Target '{path.name}' has invalid extension '{path.suffix}'. "
                "Only native Windows executables (.exe) are permitted."
            )

        # Verify neither executable nor any ancestor directory is a reparse point / junction
        current = path
        FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
        while True:
            try:
                stat_info = os.lstat(str(current))
                if hasattr(stat_info, "st_file_attributes") and (
                    stat_info.st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT
                ):
                    raise TargetValidationError(
                        f"Path component '{current}' is a reparse point or junction. Disallowed for security."
                    )
            except OSError as exc:
                raise TargetValidationError(
                    f"Failed to inspect attributes for '{current}': {exc}"
                ) from exc
            parent = current.parent
            if parent == current:
                break
            current = parent

        # Check protected process name
        if cls.is_protected_process(path.name):
            raise ProtectedTargetError(
                f"Binary '{path.name}' is on the protected system process list and cannot be launched by the agent."
            )

        return path
