"""Authorized Directory Management, Windows Reparse Point / Junction Defense,
TOCTOU Protection, and Path Traversal Protection for Phase 4.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import msvcrt
import os
import re
import threading
import uuid
from ctypes import wintypes
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from config import get_settings
from infrastructure.logging import get_logger

logger = get_logger("path_security")

# Win32 definitions for reparse points and handle inspection
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
FILE_NAME_NORMALIZED = 0x0
VOLUME_NAME_DOS = 0x0

try:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _GetFileAttributesW = kernel32.GetFileAttributesW
    _GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    _GetFileAttributesW.restype = wintypes.DWORD

    _GetFinalPathNameByHandleW = kernel32.GetFinalPathNameByHandleW
    _GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    _GetFinalPathNameByHandleW.restype = wintypes.DWORD
except Exception as _init_err:
    logger.warning(f"Win32 ctypes initialization warning in path_security: {_init_err}")
    _GetFileAttributesW = None
    _GetFinalPathNameByHandleW = None


def is_reparse_point(path: Path | str) -> bool:
    """Detect if path is a Windows reparse point (symlink, junction, or mount point).

    Checks:
    1. Python os.path.islink (works for symlinks and directory junctions on Windows).
    2. Win32 GetFileAttributesW checking FILE_ATTRIBUTE_REPARSE_POINT (0x400).
    3. os.lstat checking st_file_attributes for FILE_ATTRIBUTE_REPARSE_POINT.
    """
    p_str = str(path)
    if os.path.islink(p_str):
        return True

    if _GetFileAttributesW:
        try:
            attrs = _GetFileAttributesW(p_str)
            if attrs != INVALID_FILE_ATTRIBUTES and (attrs & FILE_ATTRIBUTE_REPARSE_POINT):
                return True
        except Exception:
            pass

    try:
        st = os.lstat(p_str)
        if hasattr(st, "st_file_attributes") and (
            st.st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT
        ):
            return True
    except Exception:
        pass

    return False


def normalize_win32_handle_path(raw_path: str) -> str:
    """Strip Windows extended-length prefix (\\?\\ or \\?\\UNC\\) from handle path."""
    if raw_path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + raw_path[8:]
    if raw_path.startswith("\\\\?\\"):
        return raw_path[4:]
    return raw_path


@dataclass
class AuthorizedDirectory:
    """Explicitly authorized directory entry for read-only inspection."""

    directory_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    path: str = ""
    display_name: str = ""
    read_only: bool = True
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        if not self.display_name and self.path:
            self.display_name = os.path.basename(self.path.rstrip("\\/")) or self.path


class PathSecurityService:
    """Enforces strict path containment, traversal defense, reparse point blocking,
    handle-based TOCTOU protection, and sensitive path denylisting.
    """

    # Comprehensive sensitive file patterns that must NEVER be read (case-insensitive)
    SENSITIVE_FILENAME_PATTERNS = [
        re.compile(r"^\.env(\..+)?$", re.IGNORECASE),
        re.compile(r"^id_(rsa|dsa|ecdsa|ed25519).*$", re.IGNORECASE),
        re.compile(r".*\.(pem|key|pfx|p12|kdbx|keystore|jks|crt|cer|der)$", re.IGNORECASE),
        re.compile(
            r"^(credentials|secrets?|passwords?|tokens?)\.(json|yaml|yml|txt|xml|ini|csv)$",
            re.IGNORECASE,
        ),
        re.compile(r"^(authorized_keys|known_hosts)$", re.IGNORECASE),
        re.compile(r"^ntuser\.dat.*$", re.IGNORECASE),
        re.compile(r"^(sam|system|security|software)$", re.IGNORECASE),
        re.compile(r"^.*(accesskeys|credentials).*\.csv$", re.IGNORECASE),
        re.compile(r"^.*service[_-]?account.*\.json$", re.IGNORECASE),
        re.compile(r"^(master\.key|secret_token|wallet\.dat|keystore)$", re.IGNORECASE),
    ]

    # Explicit sensitive directory sub-paths that cannot be entered
    SENSITIVE_DIRECTORY_PATTERNS = [
        re.compile(r"[\\/]\.ssh([\\/]|$)", re.IGNORECASE),
        re.compile(r"[\\/]\.aws([\\/]|$)", re.IGNORECASE),
        re.compile(r"[\\/]\.azure([\\/]|$)", re.IGNORECASE),
        re.compile(r"[\\/]\.gnupg([\\/]|$)", re.IGNORECASE),
        re.compile(r"[\\/]AppData[\\/]Local[\\/]Google[\\/]Chrome([\\/]|$)", re.IGNORECASE),
        re.compile(r"[\\/]AppData[\\/]Roaming[\\/]Mozilla[\\/]Firefox([\\/]|$)", re.IGNORECASE),
        re.compile(r"[\\/]AppData[\\/]Local[\\/]Microsoft[\\/]Edge([\\/]|$)", re.IGNORECASE),
        re.compile(r"[\\/]Windows[\\/]System32[\\/]config([\\/]|$)", re.IGNORECASE),
        re.compile(r"[\\/]\.config[\\/]gcloud([\\/]|$)", re.IGNORECASE),
    ]

    # Secret patterns for content redaction
    SECRET_REGEX_PATTERNS = [
        (re.compile(r"AIza[0-9A-Za-z-_]{30,40}"), "[REDACTED_API_KEY]"),
        (re.compile(r"sk-[a-zA-Z0-9T3BlbkFJ]{20,}"), "[REDACTED_API_KEY]"),
        (re.compile(r"sk-ant-[a-zA-Z0-9-_]{20,}"), "[REDACTED_API_KEY]"),
        (re.compile(r"ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{40,}"), "[REDACTED_TOKEN]"),
        (
            re.compile(
                r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----[\s\S]*?-----END (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"
            ),
            "[REDACTED_PRIVATE_KEY]",
        ),
        (
            re.compile(
                r"((?:password|secret|passwd|api_key|apikey)\s*[:=]\s*['\"]?)([^\s'\"]+)",
                re.IGNORECASE,
            ),
            r"\1[REDACTED_SECRET]",
        ),
    ]

    # Content markers that reveal private keys or cryptographic material
    PRIVATE_KEY_MARKERS = (
        "-----BEGIN RSA PRIVATE KEY",
        "-----BEGIN PRIVATE KEY",
        "-----BEGIN EC PRIVATE KEY",
        "-----BEGIN DSA PRIVATE KEY",
        "-----BEGIN OPENSSH PRIVATE KEY",
        "-----BEGIN PGP PRIVATE KEY",
        "-----BEGIN ENCRYPTED PRIVATE KEY",
        "-----BEGIN CERTIFICATE",
    )

    def __init__(self, storage_path: Path | None = None) -> None:
        self._lock = threading.RLock()
        settings = get_settings()
        self.storage_path = storage_path or (settings.data_dir / "authorized_directories.json")
        self._directories: dict[str, AuthorizedDirectory] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.storage_path.exists():
                return
            try:
                content = self.storage_path.read_text(encoding="utf-8")
                raw_list = json.loads(content)
                for item in raw_list:
                    entry = AuthorizedDirectory(**item)
                    self._directories[entry.directory_id] = entry
            except Exception as exc:
                logger.error(f"Error loading authorized directories: {exc}")

    def _save(self) -> None:
        with self._lock:
            try:
                self.storage_path.parent.mkdir(parents=True, exist_ok=True)
                raw_list = [asdict(d) for d in self._directories.values()]
                tmp_path = self.storage_path.with_suffix(".tmp")
                tmp_path.write_text(json.dumps(raw_list, indent=2), encoding="utf-8")
                if self.storage_path.exists():
                    self.storage_path.unlink()
                tmp_path.rename(self.storage_path)
            except Exception as exc:
                logger.error(f"Error saving authorized directories: {exc}")

    def add_directory(self, raw_path: str, display_name: str = "") -> AuthorizedDirectory:
        """Authorize a local directory path for read-only inspection."""
        with self._lock:
            resolved = Path(raw_path).resolve()
            if not resolved.exists():
                raise FileNotFoundError(f"Directory does not exist: '{raw_path}'")
            if not resolved.is_dir():
                raise NotADirectoryError(f"Path is not a directory: '{raw_path}'")

            norm_str = str(resolved).rstrip("\\/")

            # Prevent re-adding identical directory
            for existing in self._directories.values():
                if existing.path.lower() == norm_str.lower():
                    existing.enabled = True
                    self._save()
                    return existing

            entry = AuthorizedDirectory(
                path=norm_str,
                display_name=display_name or resolved.name or norm_str,
                read_only=True,
                enabled=True,
            )
            self._directories[entry.directory_id] = entry
            self._save()
            logger.info(f"Authorized directory added: '{norm_str}' (ID: {entry.directory_id})")
            return entry

    def revoke_directory(self, directory_id: str) -> bool:
        """Revoke authorization for a directory by ID immediately."""
        with self._lock:
            if directory_id in self._directories:
                removed = self._directories.pop(directory_id)
                self._save()
                logger.info(f"Authorized directory revoked: '{removed.path}' (ID: {directory_id})")
                return True
            return False

    def clear_all(self) -> None:
        """Clear all authorized directories immediately."""
        with self._lock:
            self._directories.clear()
            self._save()

    def list_authorized_directories(self) -> list[AuthorizedDirectory]:
        """Return all active authorized directories."""
        with self._lock:
            return [d for d in self._directories.values() if d.enabled]

    def is_path_sensitive(self, path: Path | str) -> bool:
        """Check if path matches sensitive file or directory denylists."""
        p = Path(path)
        target_str = str(p)

        # Check sensitive directory patterns
        for pattern in self.SENSITIVE_DIRECTORY_PATTERNS:
            if pattern.search(target_str):
                return True

        # Check sensitive file name patterns
        filename = p.name
        return any(pattern.match(filename) for pattern in self.SENSITIVE_FILENAME_PATTERNS)

    def contains_private_key_markers(self, text: str) -> bool:
        """Check if file text contains unencrypted private key markers."""
        return any(marker in text for marker in self.PRIVATE_KEY_MARKERS)

    def validate_and_resolve_path(self, requested_path: str) -> Path:
        """Strictly validate that requested_path resides within an authorized directory.

        Protects against:
        - Reparse points, junctions, and symbolic links
        - Path traversal ('..')
        - Absolute drive switching
        - Symlink/junction escape outside authorized boundary
        - UNC paths and alternate data streams (':$DATA')
        - Sensitive files (.env, keys, credentials)
        """
        # 1. Reject Alternate Data Streams and null bytes
        if ":" in Path(requested_path).name or "\x00" in requested_path:
            raise PermissionError(
                "Access denied: Invalid path syntax or Alternate Data Stream detected."
            )

        # 2. Reject UNC / network share paths
        if requested_path.startswith(r"\\") or requested_path.startswith("//"):
            raise PermissionError("Access denied: Network shares and UNC paths are prohibited.")

        # 3. Canonicalize and resolve real path
        try:
            target_path = Path(requested_path).resolve()
        except Exception as exc:
            raise PermissionError(f"Access denied: Malformed target path: {exc}") from exc

        # 4. Enforce containment within at least one active authorized directory
        active_dirs = self.list_authorized_directories()
        if not active_dirs:
            raise PermissionError(
                "Access denied: No directories are authorized for file access. "
                "Please authorize the target directory in Settings or via User Confirmation."
            )

        authorized_root: Path | None = None
        for auth_dir in active_dirs:
            root_path = Path(auth_dir.path).resolve()
            try:
                target_path.relative_to(root_path)
                authorized_root = root_path
                break
            except ValueError:
                continue

        if not authorized_root:
            raise PermissionError(
                f"Access denied: Path '{requested_path}' is outside all authorized directories."
            )

        # 5. Strictly inspect path components for reparse points (symlinks/junctions)
        # Check both requested path components and canonical target path components
        check_paths = [Path(requested_path), target_path]
        for cp in check_paths:
            curr = cp
            while curr != curr.parent:
                if curr.exists() and is_reparse_point(curr):
                    raise PermissionError(
                        "Access denied: Reparse points, directory junctions, and symbolic links are prohibited."
                    )
                if authorized_root and curr == authorized_root:
                    break
                curr = curr.parent

        # 6. Check sensitive directory patterns
        target_str = str(target_path)
        for pattern in self.SENSITIVE_DIRECTORY_PATTERNS:
            if pattern.search(target_str):
                raise PermissionError(
                    "Access denied: Target directory path is classified as sensitive and cannot be accessed."
                )

        # 7. Check sensitive file patterns (case-insensitive)
        filename = target_path.name
        for pattern in self.SENSITIVE_FILENAME_PATTERNS:
            if pattern.match(filename):
                raise PermissionError(
                    f"Access denied: File '{filename}' matches protected secret/credential denylist."
                )

        return target_path

    def safe_open_for_reading(
        self, requested_path: str, max_size_bytes: int
    ) -> tuple[int, Path, int]:
        """Safely open a file descriptor for reading with Win32 handle-based verification to prevent TOCTOU.

        Guarantees:
        - Bounded initial validation of path.
        - Direct kernel handle verification via GetFinalPathNameByHandleW.
        - Handle must not be a reparse point (junction/symlink).
        - Handle canonical path must still reside inside authorized directory.
        - Handle canonical path must not match sensitive denylist.
        - Bounded file size verification on the open descriptor.

        Returns:
            (file_descriptor, canonical_path, file_size_bytes)
        """
        # Step 1: Validate path
        target_path = self.validate_and_resolve_path(requested_path)

        if not target_path.exists():
            raise FileNotFoundError(f"File not found: '{requested_path}'")
        if target_path.is_dir():
            raise IsADirectoryError(f"Path is a directory, not a file: '{requested_path}'")

        # Step 2: Open file descriptor
        fd = os.open(str(target_path), os.O_RDONLY | getattr(os, "O_BINARY", 0))

        try:
            # Step 3: Check handle-level reparse point / symlink status
            st = os.fstat(fd)
            if hasattr(st, "st_file_attributes") and (
                st.st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT
            ):
                raise PermissionError(
                    "Access denied: Open file handle is a reparse point or junction."
                )

            # Step 4: Check file size on the open handle (avoids TOCTOU file growth)
            if st.st_size > max_size_bytes:
                raise PermissionError(
                    f"Access denied: File size ({st.st_size} bytes) exceeds maximum configured limit ({max_size_bytes} bytes)."
                )

            # Step 5: Win32 GetFinalPathNameByHandleW kernel verification
            canonical_handle_path = target_path
            if _GetFinalPathNameByHandleW:
                try:
                    os_handle = msvcrt.get_osfhandle(fd)
                    buf = ctypes.create_unicode_buffer(2048)
                    ret = _GetFinalPathNameByHandleW(
                        os_handle, buf, 2048, FILE_NAME_NORMALIZED | VOLUME_NAME_DOS
                    )
                    if ret > 0:
                        raw_norm = normalize_win32_handle_path(buf.value)
                        canonical_handle_path = Path(raw_norm).resolve()
                except Exception as handle_err:
                    logger.debug(f"Handle path normalization note: {handle_err}")

            # Step 6: Verify the open handle's true path is within authorized directories
            active_dirs = self.list_authorized_directories()
            is_contained = False
            for auth_dir in active_dirs:
                try:
                    canonical_handle_path.relative_to(Path(auth_dir.path).resolve())
                    is_contained = True
                    break
                except ValueError:
                    continue

            if not is_contained:
                raise PermissionError(
                    "Access denied: Final handle target path is outside authorized directories."
                )

            # Step 7: Verify open handle path does not match sensitive denylist
            if self.is_path_sensitive(canonical_handle_path):
                raise PermissionError(
                    "Access denied: Final handle target path matches protected credential denylist."
                )

            return fd, canonical_handle_path, st.st_size

        except Exception:
            os.close(fd)
            raise

    @classmethod
    def redact_secrets(cls, text: str) -> str:
        """Scan text and redact patterns resembling API keys, private keys, and passwords."""
        redacted = text
        for pattern, replacement in cls.SECRET_REGEX_PATTERNS:
            redacted = pattern.sub(replacement, redacted)
        return redacted

    @classmethod
    def compute_content_fingerprint(cls, text: str) -> str:
        """Compute SHA-256 fingerprint for content tracking and authorization binding."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


# Global singleton security service
_security_service: PathSecurityService | None = None
_service_lock = threading.Lock()


def get_path_security_service() -> PathSecurityService:
    global _security_service
    with _service_lock:
        if _security_service is None:
            _security_service = PathSecurityService()
        return _security_service
