"""Path management utilities for JARVIS."""

from pathlib import Path


def get_project_root() -> Path:
    """Return the absolute path to the project root directory."""
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """Return the path to the persistent data directory, ensuring it exists."""
    data_dir = get_project_root() / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_logs_dir() -> Path:
    """Return the path to the log directory, ensuring it exists."""
    logs_dir = get_project_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    return logs_dir


def get_docs_dir() -> Path:
    """Return the path to the documentation directory."""
    return get_project_root() / "docs"


def ensure_directory(path: Path) -> Path:
    """Ensure a directory exists and return its resolved path."""
    resolved = path.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def get_desktop_dir() -> Path:
    """Return the resolved path to the user's Desktop directory.

    Resolves dynamically via Windows Known Folder API (SHGetKnownFolderPath)
    or Windows Shell Registry (handling OneDrive redirection, custom shell paths,
    spaces, and non-ASCII usernames).
    Fails safely with FileNotFoundError if the path cannot be reliably resolved,
    avoiding silent guessing or assuming unintended directories.
    """
    import sys

    if sys.platform == "win32":
        # 1. Primary: Windows Known Folder API (SHGetKnownFolderPath)
        # FOLDERID_Desktop = {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            folderid_desktop = uuid.UUID("{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}").bytes_le

            class _GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_byte * 8),
                ]

            guid = _GUID.from_buffer_copy(folderid_desktop)
            path_ptr = ctypes.c_wchar_p()

            res = ctypes.windll.shell32.SHGetKnownFolderPath(
                ctypes.byref(guid),
                0,
                None,
                ctypes.byref(path_ptr),
            )
            if res == 0 and path_ptr.value:
                resolved_str = path_ptr.value
                ctypes.windll.ole32.CoTaskMemFree(path_ptr)
                p = Path(resolved_str).resolve()
                if p.exists() and p.is_dir():
                    return p
        except Exception:
            pass

        # 2. Secondary fallback: Windows Shell Folders Registry
        try:
            import os
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            val, _ = winreg.QueryValueEx(key, "Desktop")
            expanded = os.path.expandvars(str(val))
            p = Path(expanded).resolve()
            if p.exists() and p.is_dir():
                return p
        except Exception:
            pass

        # 3. Third check: Path.home() / "Desktop" if and only if it actually exists on disk
        fallback = (Path.home() / "Desktop").resolve()
        if fallback.exists() and fallback.is_dir():
            return fallback

        # Fail safe: Do not assume or guess an arbitrary path
        raise FileNotFoundError(
            "Could not reliably resolve Windows Desktop path via Known Folder API or Registry."
        )

    # Non-Windows platforms (e.g. testing / cross-platform environments)
    fallback = (Path.home() / "Desktop").resolve()
    if fallback.exists() and fallback.is_dir():
        return fallback
    raise FileNotFoundError("Desktop directory not found on non-Windows host.")
