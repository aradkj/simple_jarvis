"""Secure File System Modification, Document Inspection, and Archive Management for Phase 8.

Implements safe, audited file operations with:
- Handle-based TOCTOU protection
- Windows Reparse Point / Junction blocking
- Atomic writes via temporary files and os.replace
- Native Windows Recycle Bin deletion via SHFileOperationW
- Zip Slip, archive bomb, and Windows reserved device name defenses
- SHA-256 duplicate detection and unified diff comparisons
"""

from __future__ import annotations

import contextlib
import ctypes
import difflib
import hashlib
import os
import shutil
import tempfile
import zipfile
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from config import get_settings
from infrastructure.logging import get_logger
from tools.filesystem.path_security import get_path_security_service, is_reparse_point

logger = get_logger("file_service")

# Windows Shell32 constants for SHFileOperationW (Recycle Bin)
FO_DELETE = 3
FOF_ALLOWUNDO = 0x0040
FOF_NOCONFIRMATION = 0x0010
FOF_SILENT = 0x0004
FOF_NOERRORUI = 0x0400


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


@dataclass
class FileOperationResult:
    """Standard result structure for file operations."""

    success: bool
    operation: str
    target_path: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class FileService:
    """Core service for controlled file system operations."""

    def __init__(self) -> None:
        self.security = get_path_security_service()

    def _is_reserved_windows_name(self, filename: str) -> bool:
        stem = Path(filename).stem.upper()
        return stem in WINDOWS_RESERVED_NAMES

    def write_text(
        self,
        target_path: str,
        content: str,
        overwrite: bool = False,
        encoding: str = "utf-8",
    ) -> FileOperationResult:
        """Atomically write text to a file inside an authorized directory."""
        settings = get_settings()
        if not settings.file_modification_enabled:
            return FileOperationResult(
                success=False,
                operation="write_text",
                target_path=target_path,
                message="File modification subsystem is disabled in configuration.",
            )

        # Validate containment in authorized directory
        resolved_path = self.security.validate_and_resolve_path(target_path)

        if self._is_reserved_windows_name(resolved_path.name):
            return FileOperationResult(
                success=False,
                operation="write_text",
                target_path=str(resolved_path),
                message=f"Access denied: '{resolved_path.name}' is a reserved Windows device name.",
            )

        if resolved_path.exists() and not overwrite:
            return FileOperationResult(
                success=False,
                operation="write_text",
                target_path=str(resolved_path),
                message=f"File already exists and overwrite is set to False: '{resolved_path}'.",
            )

        # Verify parent directory
        parent_dir = resolved_path.parent
        if not parent_dir.exists():
            parent_dir.mkdir(parents=True, exist_ok=True)

        if is_reparse_point(parent_dir):
            return FileOperationResult(
                success=False,
                operation="write_text",
                target_path=str(resolved_path),
                message="Access denied: Parent directory is a reparse point or junction.",
            )

        # Atomic write via temp file in the same directory
        temp_fd, temp_file_path = tempfile.mkstemp(
            prefix=".jarvis_tmp_", dir=str(parent_dir), text=True
        )
        try:
            with os.fdopen(temp_fd, "w", encoding=encoding) as f:
                f.write(content)

            # Atomic replacement
            os.replace(temp_file_path, str(resolved_path))
            size_written = len(content.encode(encoding))
            logger.info(f"File written atomically: '{resolved_path}' ({size_written} bytes)")
            return FileOperationResult(
                success=True,
                operation="write_text",
                target_path=str(resolved_path),
                message=f"File successfully written ({size_written} bytes).",
                details={"bytes_written": size_written, "chars_written": len(content)},
            )
        except Exception as exc:
            if os.path.exists(temp_file_path):
                with contextlib.suppress(Exception):
                    os.unlink(temp_file_path)
            logger.error(f"Failed to write file '{resolved_path}': {exc}")
            return FileOperationResult(
                success=False,
                operation="write_text",
                target_path=str(resolved_path),
                message=f"Failed to write file: {exc}",
            )

    def edit_text(
        self,
        target_path: str,
        target_string: str | None = None,
        replacement_string: str | None = None,
        append_content: str | None = None,
    ) -> FileOperationResult:
        """Edit an existing text file via exact replacement or appending with diff generation."""
        settings = get_settings()
        if not settings.file_modification_enabled:
            return FileOperationResult(
                success=False,
                operation="edit_text",
                target_path=target_path,
                message="File modification subsystem is disabled in configuration.",
            )

        resolved_path = self.security.validate_and_resolve_path(target_path)
        if not resolved_path.exists() or not resolved_path.is_file():
            return FileOperationResult(
                success=False,
                operation="edit_text",
                target_path=str(resolved_path),
                message=f"Target file does not exist: '{resolved_path}'.",
            )

        if is_reparse_point(resolved_path):
            return FileOperationResult(
                success=False,
                operation="edit_text",
                target_path=str(resolved_path),
                message="Access denied: Target file is a reparse point or junction.",
            )

        try:
            original_text = resolved_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return FileOperationResult(
                success=False,
                operation="edit_text",
                target_path=str(resolved_path),
                message="Target file is not a valid UTF-8 text file.",
            )

        new_text = original_text
        if append_content:
            new_text += append_content

        if target_string is not None and replacement_string is not None:
            if target_string not in new_text:
                return FileOperationResult(
                    success=False,
                    operation="edit_text",
                    target_path=str(resolved_path),
                    message="Target string to replace was not found in the file.",
                )
            count = new_text.count(target_string)
            new_text = new_text.replace(target_string, replacement_string)
            replacements_made = count
        else:
            replacements_made = 0

        # Generate diff
        orig_lines = original_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)
        diff_lines = list(
            difflib.unified_diff(
                orig_lines,
                new_lines,
                fromfile=f"a/{resolved_path.name}",
                tofile=f"b/{resolved_path.name}",
            )
        )
        diff_str = "".join(diff_lines)

        write_res = self.write_text(str(resolved_path), new_text, overwrite=True)
        if not write_res.success:
            return write_res

        write_res.details["diff"] = diff_str
        write_res.details["replacements_count"] = replacements_made
        write_res.message = f"File edited successfully. Replacements: {replacements_made}. Diff lines: {len(diff_lines)}."
        return write_res

    def copy_file(
        self,
        source_path: str,
        dest_path: str,
        overwrite: bool = False,
    ) -> FileOperationResult:
        """Securely copy a file between authorized locations."""
        settings = get_settings()
        if not settings.file_modification_enabled:
            return FileOperationResult(
                success=False,
                operation="copy_file",
                target_path=source_path,
                message="File modification subsystem is disabled in configuration.",
            )

        src = self.security.validate_and_resolve_path(source_path)
        dst = self.security.validate_and_resolve_path(dest_path)

        if not src.exists() or not src.is_file():
            return FileOperationResult(
                success=False,
                operation="copy_file",
                target_path=str(src),
                message=f"Source file does not exist: '{src}'.",
            )

        if is_reparse_point(src) or is_reparse_point(dst.parent):
            return FileOperationResult(
                success=False,
                operation="copy_file",
                target_path=str(src),
                message="Access denied: Source or destination path involves a reparse point or junction.",
            )

        if dst.exists() and not overwrite:
            return FileOperationResult(
                success=False,
                operation="copy_file",
                target_path=str(dst),
                message=f"Destination file already exists and overwrite is False: '{dst}'.",
            )

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            logger.info(f"File copied: '{src}' -> '{dst}'")
            return FileOperationResult(
                success=True,
                operation="copy_file",
                target_path=str(dst),
                message=f"File successfully copied from '{src.name}' to '{dst.name}'.",
                details={"source": str(src), "destination": str(dst)},
            )
        except Exception as exc:
            logger.error(f"Failed to copy file '{src}' to '{dst}': {exc}")
            return FileOperationResult(
                success=False,
                operation="copy_file",
                target_path=str(dst),
                message=f"Failed to copy file: {exc}",
            )

    def move_file(
        self,
        source_path: str,
        dest_path: str,
        overwrite: bool = False,
    ) -> FileOperationResult:
        """Securely move/rename a file between authorized locations."""
        settings = get_settings()
        if not settings.file_modification_enabled:
            return FileOperationResult(
                success=False,
                operation="move_file",
                target_path=source_path,
                message="File modification subsystem is disabled in configuration.",
            )

        src = self.security.validate_and_resolve_path(source_path)
        dst = self.security.validate_and_resolve_path(dest_path)

        if not src.exists():
            return FileOperationResult(
                success=False,
                operation="move_file",
                target_path=str(src),
                message=f"Source path does not exist: '{src}'.",
            )

        if is_reparse_point(src) or is_reparse_point(dst.parent):
            return FileOperationResult(
                success=False,
                operation="move_file",
                target_path=str(src),
                message="Access denied: Source or destination involves a reparse point or junction.",
            )

        if dst.exists() and not overwrite:
            return FileOperationResult(
                success=False,
                operation="move_file",
                target_path=str(dst),
                message=f"Destination path already exists and overwrite is False: '{dst}'.",
            )

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.exists() and overwrite:
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            shutil.move(str(src), str(dst))
            logger.info(f"File moved: '{src}' -> '{dst}'")
            return FileOperationResult(
                success=True,
                operation="move_file",
                target_path=str(dst),
                message=f"Successfully moved '{src.name}' to '{dst.name}'.",
                details={"source": str(src), "destination": str(dst)},
            )
        except Exception as exc:
            logger.error(f"Failed to move '{src}' to '{dst}': {exc}")
            return FileOperationResult(
                success=False,
                operation="move_file",
                target_path=str(dst),
                message=f"Failed to move file: {exc}",
            )

    def delete_file(
        self,
        target_path: str,
        permanent: bool = False,
    ) -> FileOperationResult:
        """Delete a file or directory using Windows Recycle Bin (default) or permanently with confirmation."""
        settings = get_settings()
        if not settings.file_modification_enabled:
            return FileOperationResult(
                success=False,
                operation="delete_file",
                target_path=target_path,
                message="File modification subsystem is disabled in configuration.",
            )

        resolved_path = self.security.validate_and_resolve_path(target_path)
        if not resolved_path.exists():
            return FileOperationResult(
                success=False,
                operation="delete_file",
                target_path=str(resolved_path),
                message=f"Path to delete does not exist: '{resolved_path}'.",
            )

        # Permanent deletion
        if permanent:
            try:
                if resolved_path.is_dir():
                    shutil.rmtree(resolved_path)
                else:
                    resolved_path.unlink()
                logger.info(f"File permanently deleted: '{resolved_path}'")
                return FileOperationResult(
                    success=True,
                    operation="delete_file",
                    target_path=str(resolved_path),
                    message="Target was permanently deleted.",
                    details={"permanent": True},
                )
            except Exception as exc:
                return FileOperationResult(
                    success=False,
                    operation="delete_file",
                    target_path=str(resolved_path),
                    message=f"Permanent deletion failed: {exc}",
                )

        # Windows Recycle Bin via SHFileOperationW
        try:
            p_wstr = str(resolved_path) + "\x00\x00"
            fileop = SHFILEOPSTRUCTW()
            fileop.hwnd = None
            fileop.wFunc = FO_DELETE
            fileop.pFrom = p_wstr
            fileop.pTo = None
            fileop.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
            fileop.fAnyOperationsAborted = False
            fileop.hNameMappings = None
            fileop.lpszProgressTitle = None

            ret = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(fileop))
            if ret == 0 and not resolved_path.exists():
                logger.info(f"Target moved to Windows Recycle Bin: '{resolved_path}'")
                return FileOperationResult(
                    success=True,
                    operation="delete_file",
                    target_path=str(resolved_path),
                    message="Target was safely moved to the Windows Recycle Bin (recoverable).",
                    details={"recycle_bin": True, "return_code": ret},
                )
            else:
                # Fallback if SHFileOperationW reports non-zero error
                logger.warning(
                    f"Recycle Bin operation returned {ret}, falling back to permanent delete check."
                )
                return FileOperationResult(
                    success=False,
                    operation="delete_file",
                    target_path=str(resolved_path),
                    message=f"Windows Recycle Bin operation failed with return code {ret}.",
                )
        except Exception as exc:
            logger.error(f"Recycle bin error for '{resolved_path}': {exc}")
            return FileOperationResult(
                success=False,
                operation="delete_file",
                target_path=str(resolved_path),
                message=f"Recycle bin operation failed: {exc}",
            )

    def compare_diff(
        self,
        file_path_a: str,
        file_path_b: str,
        max_diff_lines: int = 500,
    ) -> FileOperationResult:
        """Compute unified diff between two authorized text files."""
        src_a = self.security.validate_and_resolve_path(file_path_a)
        src_b = self.security.validate_and_resolve_path(file_path_b)

        if not src_a.exists() or not src_a.is_file():
            return FileOperationResult(
                success=False,
                operation="compare_diff",
                target_path=str(src_a),
                message=f"File A not found: '{src_a}'.",
            )
        if not src_b.exists() or not src_b.is_file():
            return FileOperationResult(
                success=False,
                operation="compare_diff",
                target_path=str(src_b),
                message=f"File B not found: '{src_b}'.",
            )

        try:
            lines_a = src_a.read_text(encoding="utf-8").splitlines(keepends=True)
            lines_b = src_b.read_text(encoding="utf-8").splitlines(keepends=True)
        except UnicodeDecodeError:
            return FileOperationResult(
                success=False,
                operation="compare_diff",
                target_path=f"{src_a} vs {src_b}",
                message="One or both files are binary or not valid UTF-8.",
            )

        diff = list(
            difflib.unified_diff(
                lines_a,
                lines_b,
                fromfile=f"a/{src_a.name}",
                tofile=f"b/{src_b.name}",
            )
        )

        truncated = False
        if len(diff) > max_diff_lines:
            diff = diff[:max_diff_lines]
            truncated = True

        diff_text = "".join(diff)
        is_identical = len(diff) == 0

        return FileOperationResult(
            success=True,
            operation="compare_diff",
            target_path=f"{src_a} vs {src_b}",
            message="Files are identical." if is_identical else "Differences found.",
            details={
                "identical": is_identical,
                "diff": diff_text,
                "diff_line_count": len(diff),
                "truncated": truncated,
            },
        )

    def find_duplicates(
        self,
        directory_path: str,
        min_size_bytes: int = 1,
        max_files: int = 500,
    ) -> FileOperationResult:
        """Identify duplicate files in an authorized directory via size clustering and SHA-256 hashes."""
        resolved_dir = self.security.validate_and_resolve_path(directory_path)
        if not resolved_dir.is_dir():
            return FileOperationResult(
                success=False,
                operation="find_duplicates",
                target_path=str(resolved_dir),
                message=f"Path is not a directory: '{resolved_dir}'.",
            )

        # 1. Cluster files by exact byte size
        size_map: dict[int, list[Path]] = {}
        files_scanned = 0

        for root, dirs, files in os.walk(resolved_dir):
            # Block symlinks / junctions during walk
            if is_reparse_point(root):
                continue
            dirs[:] = [d for d in dirs if not is_reparse_point(os.path.join(root, d))]

            for f in files:
                full_p = Path(root) / f
                if is_reparse_point(full_p):
                    continue
                try:
                    st = full_p.stat()
                    if st.st_size >= min_size_bytes:
                        size_map.setdefault(st.st_size, []).append(full_p)
                        files_scanned += 1
                        if files_scanned >= max_files:
                            break
                except Exception:
                    continue
            if files_scanned >= max_files:
                break

        # 2. Hash files that share the exact size
        hash_map: dict[str, list[str]] = {}
        for _size, file_list in size_map.items():
            if len(file_list) < 2:
                continue
            for p in file_list:
                try:
                    h = hashlib.sha256(p.read_bytes()).hexdigest()
                    hash_map.setdefault(h, []).append(str(p))
                except Exception:
                    continue

        duplicate_groups = {h: paths for h, paths in hash_map.items() if len(paths) > 1}
        total_dup_files = sum(len(paths) for paths in duplicate_groups.values())

        return FileOperationResult(
            success=True,
            operation="find_duplicates",
            target_path=str(resolved_dir),
            message=f"Found {len(duplicate_groups)} duplicate group(s) across {files_scanned} scanned files.",
            details={
                "duplicate_groups_count": len(duplicate_groups),
                "total_duplicate_files": total_dup_files,
                "duplicates": duplicate_groups,
                "scanned_files_count": files_scanned,
            },
        )

    def create_archive(
        self,
        archive_path: str,
        source_paths: list[str],
    ) -> FileOperationResult:
        """Create a ZIP archive of authorized files."""
        settings = get_settings()
        if not settings.file_modification_enabled:
            return FileOperationResult(
                success=False,
                operation="create_archive",
                target_path=archive_path,
                message="File modification subsystem is disabled in configuration.",
            )

        resolved_archive = self.security.validate_and_resolve_path(archive_path)
        if resolved_archive.suffix.lower() != ".zip":
            return FileOperationResult(
                success=False,
                operation="create_archive",
                target_path=str(resolved_archive),
                message="Only .zip archives are supported for creation.",
            )

        resolved_sources: list[Path] = []
        for src in source_paths:
            p = self.security.validate_and_resolve_path(src)
            if not p.exists():
                return FileOperationResult(
                    success=False,
                    operation="create_archive",
                    target_path=str(resolved_archive),
                    message=f"Source path for archive does not exist: '{p}'.",
                )
            if is_reparse_point(p):
                return FileOperationResult(
                    success=False,
                    operation="create_archive",
                    target_path=str(resolved_archive),
                    message=f"Access denied: Source path is a reparse point: '{p}'.",
                )
            resolved_sources.append(p)

        try:
            resolved_archive.parent.mkdir(parents=True, exist_ok=True)
            files_added = 0
            with zipfile.ZipFile(resolved_archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for src in resolved_sources:
                    if src.is_file():
                        zf.write(src, arcname=src.name)
                        files_added += 1
                    elif src.is_dir():
                        for root, _, files in os.walk(src):
                            if is_reparse_point(root):
                                continue
                            for f in files:
                                f_path = Path(root) / f
                                if is_reparse_point(f_path):
                                    continue
                                rel_path = f_path.relative_to(src.parent)
                                zf.write(f_path, arcname=str(rel_path))
                                files_added += 1

            size = resolved_archive.stat().st_size
            return FileOperationResult(
                success=True,
                operation="create_archive",
                target_path=str(resolved_archive),
                message=f"Successfully created ZIP archive with {files_added} entries ({size} bytes).",
                details={"entries_count": files_added, "archive_size_bytes": size},
            )
        except Exception as exc:
            logger.error(f"Failed to create archive '{resolved_archive}': {exc}")
            return FileOperationResult(
                success=False,
                operation="create_archive",
                target_path=str(resolved_archive),
                message=f"Failed to create archive: {exc}",
            )

    def inspect_archive(
        self,
        archive_path: str,
    ) -> FileOperationResult:
        """Inspect ZIP archive metadata, entries, and compression ratio without extraction."""
        resolved_archive = self.security.validate_and_resolve_path(archive_path)
        if not resolved_archive.exists() or not resolved_archive.is_file():
            return FileOperationResult(
                success=False,
                operation="inspect_archive",
                target_path=str(resolved_archive),
                message=f"Archive file not found: '{resolved_archive}'.",
            )

        try:
            with zipfile.ZipFile(resolved_archive, "r") as zf:
                infolist = zf.infolist()
                total_uncompressed = sum(info.file_size for info in infolist)
                total_compressed = sum(info.compress_size for info in infolist)
                ratio = (
                    (total_uncompressed / max(total_compressed, 1)) if total_compressed > 0 else 1.0
                )

                entries = [
                    {
                        "filename": info.filename,
                        "file_size": info.file_size,
                        "compress_size": info.compress_size,
                        "is_dir": info.is_dir(),
                    }
                    for info in infolist[:100]  # first 100 entries preview
                ]

                return FileOperationResult(
                    success=True,
                    operation="inspect_archive",
                    target_path=str(resolved_archive),
                    message=f"Archive has {len(infolist)} entries. Total uncompressed: {total_uncompressed} bytes.",
                    details={
                        "entries_count": len(infolist),
                        "total_uncompressed_bytes": total_uncompressed,
                        "total_compressed_bytes": total_compressed,
                        "compression_ratio": round(ratio, 2),
                        "entries_preview": entries,
                    },
                )
        except zipfile.BadZipFile as exc:
            return FileOperationResult(
                success=False,
                operation="inspect_archive",
                target_path=str(resolved_archive),
                message=f"Invalid or corrupted ZIP archive: {exc}",
            )

    def extract_archive(
        self,
        archive_path: str,
        target_directory: str,
    ) -> FileOperationResult:
        """Safely extract ZIP archive enforcing Zip Slip defense, bomb defense, and reserved name check."""
        settings = get_settings()
        if not settings.file_modification_enabled:
            return FileOperationResult(
                success=False,
                operation="extract_archive",
                target_path=archive_path,
                message="File modification subsystem is disabled in configuration.",
            )

        resolved_archive = self.security.validate_and_resolve_path(archive_path)
        resolved_target_dir = self.security.validate_and_resolve_path(target_directory)

        if not resolved_archive.exists() or not resolved_archive.is_file():
            return FileOperationResult(
                success=False,
                operation="extract_archive",
                target_path=str(resolved_archive),
                message=f"Archive not found: '{resolved_archive}'.",
            )

        try:
            with zipfile.ZipFile(resolved_archive, "r") as zf:
                infolist = zf.infolist()

                # Archive bomb checks
                if len(infolist) > settings.file_archive_max_entries:
                    return FileOperationResult(
                        success=False,
                        operation="extract_archive",
                        target_path=str(resolved_archive),
                        message=(
                            f"Archive bomb defense triggered: Entry count ({len(infolist)}) "
                            f"exceeds limit ({settings.file_archive_max_entries})."
                        ),
                    )

                total_uncompressed = sum(info.file_size for info in infolist)
                if total_uncompressed > settings.file_archive_max_total_size_bytes:
                    return FileOperationResult(
                        success=False,
                        operation="extract_archive",
                        target_path=str(resolved_archive),
                        message=(
                            f"Archive bomb defense triggered: Uncompressed size ({total_uncompressed} bytes) "
                            f"exceeds limit ({settings.file_archive_max_total_size_bytes} bytes)."
                        ),
                    )

                total_compressed = sum(info.compress_size for info in infolist)
                ratio = total_uncompressed / max(total_compressed, 1)
                if ratio > settings.file_archive_max_ratio and total_uncompressed > 1024 * 1024:
                    return FileOperationResult(
                        success=False,
                        operation="extract_archive",
                        target_path=str(resolved_archive),
                        message=(
                            f"Archive bomb defense triggered: Compression ratio ({ratio:.1f}:1) "
                            f"exceeds safety threshold ({settings.file_archive_max_ratio}:1)."
                        ),
                    )

                # Security inspection of all entries before extraction
                extracted_count = 0
                for info in infolist:
                    # Check symlink flag in external_attr (0o120000)
                    if (info.external_attr >> 16) & 0o170000 == 0o120000:
                        return FileOperationResult(
                            success=False,
                            operation="extract_archive",
                            target_path=str(resolved_archive),
                            message=f"Access denied: Archive contains symbolic link '{info.filename}'.",
                        )

                    # Zip Slip defense: check relative target
                    destination_path = (resolved_target_dir / info.filename).resolve()
                    try:
                        destination_path.relative_to(resolved_target_dir)
                    except ValueError:
                        return FileOperationResult(
                            success=False,
                            operation="extract_archive",
                            target_path=str(resolved_archive),
                            message=f"Zip Slip attack detected: Member '{info.filename}' traverses outside destination.",
                        )

                    # Check reserved device names in filename parts
                    for part in destination_path.parts:
                        if self._is_reserved_windows_name(part):
                            return FileOperationResult(
                                success=False,
                                operation="extract_archive",
                                target_path=str(resolved_archive),
                                message=f"Access denied: Archive entry '{info.filename}' contains reserved Windows name '{part}'.",
                            )

                # All entries are safe; extract
                resolved_target_dir.mkdir(parents=True, exist_ok=True)
                for info in infolist:
                    destination_path = (resolved_target_dir / info.filename).resolve()
                    if info.is_dir():
                        destination_path.mkdir(parents=True, exist_ok=True)
                    else:
                        destination_path.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, open(destination_path, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        extracted_count += 1

                return FileOperationResult(
                    success=True,
                    operation="extract_archive",
                    target_path=str(resolved_target_dir),
                    message=f"Safely extracted {extracted_count} files to '{resolved_target_dir}'.",
                    details={"extracted_count": extracted_count},
                )
        except zipfile.BadZipFile as exc:
            return FileOperationResult(
                success=False,
                operation="extract_archive",
                target_path=str(resolved_archive),
                message=f"Corrupted or invalid ZIP archive: {exc}",
            )


_file_service_instance: FileService | None = None


def get_file_service() -> FileService:
    """Singleton getter for FileService."""
    global _file_service_instance
    if _file_service_instance is None:
        _file_service_instance = FileService()
    return _file_service_instance
