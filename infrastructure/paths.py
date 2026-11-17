"""Path management and Windows Native Known Folder utilities for JARVIS."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("infrastructure.paths")


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


def _resolve_windows_known_folder(
    guid_str: str, registry_value_names: list[str], fallback_subfolder: str
) -> Path:
    """Resolve a Windows Known Folder using SHGetKnownFolderPath, Registry, or Home fallback.

    Handles OneDrive redirection, custom profiles, localized paths, and spaces.
    """
    if sys.platform == "win32":
        # 1. Primary: Windows Known Folder API (SHGetKnownFolderPath)
        try:
            import ctypes
            import uuid
            from ctypes import wintypes

            folderid = uuid.UUID(guid_str).bytes_le

            class _GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_byte * 8),
                ]

            guid = _GUID.from_buffer_copy(folderid)
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
        except Exception as kf_err:
            logger.debug(f"SHGetKnownFolderPath notice for {guid_str}: {kf_err}")

        # 2. Secondary fallback: Windows Shell Folders Registry
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            for reg_name in registry_value_names:
                try:
                    val, _ = winreg.QueryValueEx(key, reg_name)
                    expanded = os.path.expandvars(str(val))
                    p = Path(expanded).resolve()
                    if p.exists() and p.is_dir():
                        return p
                except (FileNotFoundError, OSError):
                    continue
        except Exception as reg_err:
            logger.debug(f"User Shell Folders registry notice: {reg_err}")

    # 3. Third check: User home directory fallback
    fallback = (Path.home() / fallback_subfolder).resolve()
    if fallback.exists() and fallback.is_dir():
        return fallback

    # If folder does not exist yet on disk, create or return fallback under user home
    return fallback


def get_desktop_dir() -> Path:
    """Return the resolved path to the user's Desktop directory."""
    return _resolve_windows_known_folder(
        guid_str="{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
        registry_value_names=["Desktop"],
        fallback_subfolder="Desktop",
    )


def get_documents_dir() -> Path:
    """Return the resolved path to the user's Documents directory."""
    return _resolve_windows_known_folder(
        guid_str="{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
        registry_value_names=["Personal", "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}"],
        fallback_subfolder="Documents",
    )


def get_downloads_dir() -> Path:
    """Return the resolved path to the user's Downloads directory."""
    return _resolve_windows_known_folder(
        guid_str="{374DE290-123F-4565-9164-39C4925E467B}",
        registry_value_names=["{374DE290-123F-4565-9164-39C4925E467B}"],
        fallback_subfolder="Downloads",
    )


def get_pictures_dir() -> Path:
    """Return the resolved path to the user's Pictures directory."""
    return _resolve_windows_known_folder(
        guid_str="{33E28130-463A-4E3B-9636-F883BC1C5FEA}",
        registry_value_names=["My Pictures"],
        fallback_subfolder="Pictures",
    )


def get_videos_dir() -> Path:
    """Return the resolved path to the user's Videos directory."""
    return _resolve_windows_known_folder(
        guid_str="{18989B1D-99B5-455B-841C-AB7C74E4DDFC}",
        registry_value_names=["My Video"],
        fallback_subfolder="Videos",
    )


def get_music_dir() -> Path:
    """Return the resolved path to the user's Music directory."""
    return _resolve_windows_known_folder(
        guid_str="{4BD8D570-509A-4F3F-A765-C1632CD7C9E0}",
        registry_value_names=["My Music"],
        fallback_subfolder="Music",
    )


def get_home_dir() -> Path:
    """Return the user profile / home directory."""
    return Path.home().resolve()


def resolve_destination_directory(destination_name: str) -> Path:
    """Resolve a natural language or path destination to an actual verified Windows Path.

    Supports both English and Persian destination terms:
    - Desktop: "desktop", "دسکتاپ", "میزکار"
    - Documents: "documents", "docs", "اسناد", "مستندات", "داکیومنت‌ها"
    - Downloads: "downloads", "دانلودها", "بارگیری‌ها"
    - Pictures: "pictures", "photos", "تصاویر", "عکس‌ها"
    - Videos: "videos", "فیلم‌ها", "ویدیوها"
    - Music: "music", "موسیقی", "آهنگ‌ها"
    - Home: "home", "خانه", "کاربر"
    """
    dest = (destination_name or "").strip().lower()

    if any(k in dest for k in ("desktop", "دسکتاپ", "میزکار")):
        return get_desktop_dir()
    if any(k in dest for k in ("document", "docs", "اسناد", "مستندات", "داکیومنت")):
        return get_documents_dir()
    if any(k in dest for k in ("download", "دانلود", "بارگیری")):
        return get_downloads_dir()
    if any(k in dest for k in ("picture", "photo", "image", "تصاویر", "عکس")):
        return get_pictures_dir()
    if any(k in dest for k in ("video", "movie", "فیلم", "ویدیو")):
        return get_videos_dir()
    if any(k in dest for k in ("music", "song", "audio", "موسیقی", "آهنگ")):
        return get_music_dir()
    if any(k in dest for k in ("home", "user", "خانه", "کاربر")):
        return get_home_dir()

    # If it's already a valid path on disk
    try:
        candidate = Path(destination_name).resolve()
        if candidate.exists() and candidate.is_dir():
            return candidate
    except Exception:
        pass

    # Default to desktop if user specified desktop or default fallback
    return get_desktop_dir()
