"""Secure Read-Only File and Directory Inspection Tools for Phase 4.

Includes:
- DirectoryListTool: Safely lists immediate entries in an authorized directory with reparse point blocking.
- FileMetadataTool: Reads basic file metadata (size, created, modified) without following symlinks.
- FileReadTextTool: Reads safe text files within authorized boundaries using handle-based TOCTOU protection,
  binary detection, private key marker inspection, and secret redaction.
- FileSearchTextTool: Performs bounded, non-recursive or shallow text searches within authorized directories
  avoiding symlinks and reparse points.
"""

from __future__ import annotations

import contextlib
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from config import get_settings
from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult
from tools.filesystem.document_extractor import get_document_extractor
from tools.filesystem.file_service import get_file_service
from tools.filesystem.path_security import get_path_security_service, is_reparse_point

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


# --- Pydantic Input Schemas ---


class DirectoryListInput(BaseModel):
    directory_path: str = Field(description="Target directory path to inspect")
    include_hidden: bool = Field(default=False, description="Whether to include hidden entries")
    max_entries: int = Field(default=100, ge=1, le=500, description="Maximum entries to return")


class FileMetadataInput(BaseModel):
    file_path: str = Field(description="Target file path to inspect")


class FileReadTextInput(BaseModel):
    file_path: str = Field(description="Target text file path to read")
    max_chars: int = Field(
        default=16000, ge=100, le=50000, description="Maximum characters to read"
    )


class FileSearchTextInput(BaseModel):
    directory_path: str = Field(description="Authorized root directory to search inside")
    query: str = Field(description="Text substring or phrase to search for")
    max_results: int = Field(
        default=25, ge=1, le=100, description="Maximum matching lines/files to return"
    )
    max_depth: int = Field(default=2, ge=1, le=5, description="Maximum directory traversal depth")


# --- Tool Implementations ---


class DirectoryListTool(BaseTool):
    """Tool to safely inspect and list entries inside an explicitly authorized directory."""

    name = "file_list_directory"
    description = (
        "List files and subdirectories inside an explicitly authorized local directory path."
    )
    category = PermissionCategory.FILE_READ
    input_schema = DirectoryListInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Directory listing cancelled by user")

        settings = get_settings()
        if not settings.file_reading_enabled:
            return ToolResult.denied("File reading subsystem is disabled in configuration.")

        security = get_path_security_service()
        req_path = getattr(params, "directory_path", "")
        include_hidden = getattr(params, "include_hidden", False)
        max_entries = min(getattr(params, "max_entries", 100), settings.file_max_directory_entries)

        try:
            resolved_dir = security.validate_and_resolve_path(req_path)
            if not resolved_dir.is_dir():
                return ToolResult.failed(f"Path is not a directory: '{req_path}'")

            entries: list[dict[str, Any]] = []
            with os.scandir(resolved_dir) as it:
                for entry in it:
                    if context.is_cancelled():
                        return ToolResult.cancelled("Directory listing cancelled by user")

                    # Filter hidden files unless requested
                    if not include_hidden and entry.name.startswith("."):
                        continue

                    # Filter sensitive files from directory enumeration to avoid reconnaissance
                    if security.is_path_sensitive(Path(entry.path)):
                        continue

                    try:
                        stat = entry.stat(follow_symlinks=False)
                        is_reparse = is_reparse_point(entry.path)
                        is_dir = entry.is_dir(follow_symlinks=False)

                        entry_info: dict[str, Any] = {
                            "name": entry.name,
                            "type": "directory" if is_dir else "file",
                            "is_reparse_point": is_reparse,
                            "size_bytes": stat.st_size if not is_dir else 0,
                            "modified_at": datetime.fromtimestamp(
                                stat.st_mtime, tz=UTC
                            ).isoformat(),
                        }
                        entries.append(entry_info)
                    except Exception:
                        continue

                    if len(entries) >= max_entries:
                        break

            return ToolResult.success(
                data={
                    "directory": str(resolved_dir),
                    "entry_count": len(entries),
                    "is_truncated": len(entries) >= max_entries,
                    "entries": entries,
                    "is_local_content": True,
                }
            )
        except PermissionError as perm_err:
            return ToolResult.denied(str(perm_err))
        except Exception as exc:
            return ToolResult.failed(f"Failed to list directory: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "directory_path": {"type": "string", "description": "Directory path to list"},
                    "include_hidden": {"type": "boolean", "default": False},
                    "max_entries": {"type": "integer", "default": 100},
                },
                "required": ["directory_path"],
            },
            requires_approval=False,
            timeout_seconds=10.0,
        )


class FileMetadataTool(BaseTool):
    """Tool to read safe file metadata (size, dates, type) without loading file content."""

    name = "file_get_metadata"
    description = "Inspect safe metadata (size, last modified, creation time) of a file inside an authorized directory."
    category = PermissionCategory.FILE_READ
    input_schema = FileMetadataInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Metadata inspection cancelled by user")

        settings = get_settings()
        if not settings.file_reading_enabled:
            return ToolResult.denied("File reading subsystem is disabled in configuration.")

        security = get_path_security_service()
        req_path = getattr(params, "file_path", "")

        try:
            target_path = security.validate_and_resolve_path(req_path)
            if not target_path.exists():
                return ToolResult.failed(f"File not found: '{req_path}'")

            # Check reparse point on target
            if is_reparse_point(target_path):
                return ToolResult.denied(
                    "Access denied: Target path is a reparse point or symbolic link."
                )

            stat = target_path.stat(follow_symlinks=False)
            return ToolResult.success(
                data={
                    "filename": target_path.name,
                    "extension": target_path.suffix.lower(),
                    "is_directory": target_path.is_dir(),
                    "size_bytes": stat.st_size,
                    "size_kb": round(stat.st_size / 1024, 2),
                    "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                    "created_at": datetime.fromtimestamp(stat.st_ctime, tz=UTC).isoformat(),
                    "is_local_content": True,
                }
            )
        except PermissionError as perm_err:
            return ToolResult.denied(str(perm_err))
        except Exception as exc:
            return ToolResult.failed(f"Failed to read metadata: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "File path to inspect"}
                },
                "required": ["file_path"],
            },
            requires_approval=False,
            timeout_seconds=5.0,
        )


class FileReadTextTool(BaseTool):
    """Tool to read bounded text content from files in authorized directories with handle-based
    TOCTOU protection, binary file detection, private key marker defense, and secret redaction.
    """

    name = "file_read_text"
    description = "Read safe text file contents from an authorized directory with size limits and automatic secret redaction."
    category = PermissionCategory.FILE_READ
    input_schema = FileReadTextInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("File read cancelled by user")

        settings = get_settings()
        if not settings.file_reading_enabled:
            return ToolResult.denied("File reading subsystem is disabled in configuration.")

        security = get_path_security_service()
        req_path = getattr(params, "file_path", "")
        max_chars = min(getattr(params, "max_chars", 16000), settings.file_max_returned_chars)

        # Extension check prior to open
        p = Path(req_path)
        ext = p.suffix.lower()
        if ext and ext not in settings.file_allowed_extensions:
            return ToolResult.denied(
                f"Access denied: File extension '{ext}' is not in the allowed text extensions list."
            )

        fd: int | None = None
        try:
            # Handle-based safe opening with kernel verification against TOCTOU and reparse points
            fd, canonical_path, file_size = security.safe_open_for_reading(
                requested_path=req_path,
                max_size_bytes=settings.file_max_size_bytes,
            )

            # Read bounded byte buffer from the verified handle
            # Max chars * 4 bytes for multi-byte UTF-8 plus 4 extra for truncation detection
            max_read_bytes = (max_chars + 1) * 4
            raw_bytes = os.read(fd, max_read_bytes)

            # Binary detection: Reject files containing null bytes
            if b"\x00" in raw_bytes[:1024]:
                return ToolResult.denied("Access denied: Binary file content is not allowed.")

            # Decode text safely
            raw_text = raw_bytes.decode("utf-8", errors="replace")

            # Content-level defense against private keys / certificates
            if security.contains_private_key_markers(raw_text):
                return ToolResult.denied(
                    "Access denied: File content contains protected cryptographic key or credential material."
                )

            is_truncated = len(raw_text) > max_chars
            final_text = raw_text[:max_chars]

            # Redact secrets if enabled
            if settings.secret_redaction_enabled:
                final_text = security.redact_secrets(final_text)

            fingerprint = security.compute_content_fingerprint(final_text)

            return ToolResult.success(
                data={
                    "filename": canonical_path.name,
                    "character_count": len(final_text),
                    "is_truncated": is_truncated,
                    "content": final_text,
                    "is_local_content": True,
                    "content_fingerprint": fingerprint,
                }
            )
        except PermissionError as perm_err:
            return ToolResult.denied(str(perm_err))
        except FileNotFoundError:
            return ToolResult.failed(f"File not found: '{req_path}'")
        except IsADirectoryError:
            return ToolResult.failed(f"Path is a directory, not a file: '{req_path}'")
        except Exception as exc:
            return ToolResult.failed(f"Failed to read file: {exc}")
        finally:
            if fd is not None:
                with contextlib.suppress(Exception):
                    os.close(fd)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.MEDIUM,
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Target file path to read"},
                    "max_chars": {"type": "integer", "default": 16000},
                },
                "required": ["file_path"],
            },
            requires_approval=False,
            timeout_seconds=10.0,
        )


class FileSearchTextTool(BaseTool):
    """Tool to perform bounded text substring searches across files in an authorized directory."""

    name = "file_search_text"
    description = "Search for a text query or phrase within allowed files in an authorized directory up to bounded depth."
    category = PermissionCategory.FILE_SEARCH
    input_schema = FileSearchTextInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Search cancelled by user")

        settings = get_settings()
        if not settings.file_reading_enabled:
            return ToolResult.denied("File reading subsystem is disabled in configuration.")

        security = get_path_security_service()
        req_dir = getattr(params, "directory_path", "")
        query = getattr(params, "query", "").strip()
        if not query:
            return ToolResult.failed("Search query cannot be empty.")

        max_results = min(getattr(params, "max_results", 25), settings.file_max_search_results)
        max_depth = min(getattr(params, "max_depth", 2), settings.file_max_search_depth)

        try:
            resolved_root = security.validate_and_resolve_path(req_dir)
            if not resolved_root.is_dir():
                return ToolResult.failed(f"Search target is not a directory: '{req_dir}'")

            matches: list[dict[str, Any]] = []
            files_scanned = 0

            # Bounded DFS traversal
            stack: list[tuple[Path, int]] = [(resolved_root, 0)]

            while stack and len(matches) < max_results:
                if context.is_cancelled():
                    return ToolResult.cancelled("Search cancelled by user")

                curr_dir, depth = stack.pop()
                if depth > max_depth:
                    continue

                try:
                    with os.scandir(curr_dir) as it:
                        for entry in it:
                            if entry.name.startswith("."):
                                continue

                            entry_path = Path(entry.path)

                            # Skip any reparse point, symlink, or junction
                            if is_reparse_point(entry.path):
                                continue

                            # Skip sensitive files or directories
                            if security.is_path_sensitive(entry_path):
                                continue

                            is_dir = entry.is_dir(follow_symlinks=False)
                            if is_dir:
                                if depth < max_depth:
                                    stack.append((entry_path, depth + 1))
                            else:
                                ext = entry_path.suffix.lower()
                                if ext not in settings.file_allowed_extensions:
                                    continue

                                files_scanned += 1
                                fd: int | None = None
                                try:
                                    # Handle-based safe opening for TOCTOU defense
                                    fd, _, file_size = security.safe_open_for_reading(
                                        str(entry_path),
                                        max_size_bytes=settings.file_max_size_bytes,
                                    )
                                    raw_bytes = os.read(fd, 65536)  # Read initial 64KB for search
                                    if b"\x00" in raw_bytes[:1024]:
                                        continue  # Skip binary file

                                    text = raw_bytes.decode("utf-8", errors="ignore")
                                    if security.contains_private_key_markers(text):
                                        continue  # Skip sensitive files containing keys

                                    for line_num, line in enumerate(text.splitlines(), start=1):
                                        if query.lower() in line.lower():
                                            clean_line = line.strip()
                                            if settings.secret_redaction_enabled:
                                                clean_line = security.redact_secrets(clean_line)
                                            matches.append(
                                                {
                                                    "file": entry_path.name,
                                                    "relative_path": str(
                                                        entry_path.relative_to(resolved_root)
                                                    ),
                                                    "line_number": line_num,
                                                    "match": clean_line[:200],
                                                }
                                            )
                                            if len(matches) >= max_results:
                                                break
                                finally:
                                    if fd is not None:
                                        with contextlib.suppress(Exception):
                                            os.close(fd)
                except Exception:
                    continue

            return ToolResult.success(
                data={
                    "root_directory": str(resolved_root),
                    "query": query,
                    "files_scanned": files_scanned,
                    "match_count": len(matches),
                    "matches": matches,
                    "is_local_content": True,
                }
            )
        except PermissionError as perm_err:
            return ToolResult.denied(str(perm_err))
        except Exception as exc:
            return ToolResult.failed(f"Search failed: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.MEDIUM,
            parameters_schema={
                "type": "object",
                "properties": {
                    "directory_path": {
                        "type": "string",
                        "description": "Authorized directory to search",
                    },
                    "query": {"type": "string", "description": "Phrase or keyword to find"},
                    "max_results": {"type": "integer", "default": 25},
                    "max_depth": {"type": "integer", "default": 2},
                },
                "required": ["directory_path", "query"],
            },
            requires_approval=False,
            timeout_seconds=15.0,
        )


# ============================================================================
# Phase 8 Tools: Document Extraction, File Modification & Archive Operations
# ============================================================================


class FileDocumentExtractInput(BaseModel):
    file_path: str = Field(
        description="Target document path (.pdf, .docx, .xlsx, .pptx, .csv, .json, .txt, .md)"
    )
    max_chars: int = Field(
        default=32000, ge=100, le=100000, description="Maximum characters to extract"
    )
    max_pages: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum pages/slides to parse for multi-page documents",
    )


class FileWriteTextInput(BaseModel):
    file_path: str = Field(description="Target file path to write")
    content: str = Field(description="Text content to write")
    overwrite: bool = Field(
        default=False, description="Whether to overwrite if file already exists"
    )
    encoding: str = Field(default="utf-8", description="File character encoding (default: utf-8)")


class FileEditTextInput(BaseModel):
    file_path: str = Field(description="Target file path to edit")
    target_string: str | None = Field(
        default=None, description="Exact substring to find and replace"
    )
    replacement_string: str | None = Field(
        default=None, description="Replacement text for target_string"
    )
    append_content: str | None = Field(
        default=None, description="Content to append at the end of the file"
    )


class FileCopyInput(BaseModel):
    source_path: str = Field(description="Source file path to copy from")
    dest_path: str = Field(description="Destination file path to copy to")
    overwrite: bool = Field(
        default=False, description="Whether to overwrite destination if it exists"
    )


class FileMoveInput(BaseModel):
    source_path: str = Field(description="Source file path to move")
    dest_path: str = Field(description="Destination file path")
    overwrite: bool = Field(
        default=False, description="Whether to overwrite destination if it exists"
    )


class FileDeleteInput(BaseModel):
    file_path: str = Field(description="Path of file or directory to delete")
    permanent: bool = Field(
        default=False,
        description="Whether to permanently delete instead of using Windows Recycle Bin",
    )


class FileCompareDiffInput(BaseModel):
    file_path_a: str = Field(description="First file path")
    file_path_b: str = Field(description="Second file path")
    max_diff_lines: int = Field(
        default=500, ge=10, le=2000, description="Maximum diff lines to return"
    )


class FileFindDuplicatesInput(BaseModel):
    directory_path: str = Field(description="Authorized root directory to scan for duplicates")
    min_size_bytes: int = Field(
        default=1, ge=0, description="Minimum file size in bytes to inspect"
    )
    max_files: int = Field(default=500, ge=2, le=2000, description="Maximum files to scan")


class FileArchiveCreateInput(BaseModel):
    archive_path: str = Field(description="Path for the resulting .zip archive file")
    source_paths: list[str] = Field(
        description="List of files and/or directories to include in archive"
    )


class FileArchiveInspectInput(BaseModel):
    archive_path: str = Field(description="Path to .zip archive to inspect")


class FileArchiveExtractInput(BaseModel):
    archive_path: str = Field(description="Path to .zip archive to extract")
    target_directory: str = Field(
        description="Authorized target directory where contents will be extracted"
    )


class FileDocumentExtractTool(BaseTool):
    """Tool to extract text and structured metadata from documents (PDF, DOCX, XLSX, PPTX, CSV, TXT, etc.)."""

    name = "file_extract_document"
    description = "Extract text and structured metadata from PDF, Word (.docx), Excel (.xlsx), PowerPoint (.pptx), CSV, JSON, and text documents."
    category = PermissionCategory.FILE_READ
    input_schema = FileDocumentExtractInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Document extraction cancelled by user")

        settings = get_settings()
        if not settings.file_reading_enabled:
            return ToolResult.denied("File reading subsystem is disabled in configuration.")

        security = get_path_security_service()
        req_path = getattr(params, "file_path", "")
        max_chars = getattr(params, "max_chars", 32000)
        max_pages = getattr(params, "max_pages", 50)

        try:
            resolved_path = security.validate_and_resolve_path(req_path)
            extractor = get_document_extractor()
            doc = extractor.extract(resolved_path, max_chars=max_chars, max_pages=max_pages)

            content = doc.text_content
            if settings.secret_redaction_enabled:
                content = security.redact_secrets(content)

            return ToolResult.success(
                data={
                    "file_path": str(resolved_path),
                    "file_type": doc.file_type,
                    "text_content": content,
                    "char_count": len(content),
                    "word_count": len(content.split()),
                    "line_count": len(content.splitlines()),
                    "page_count": doc.page_count,
                    "sheet_count": doc.sheet_count,
                    "truncated": doc.truncated,
                    "metadata": doc.metadata,
                }
            )
        except PermissionError as perm_err:
            return ToolResult.denied(str(perm_err))
        except Exception as exc:
            return ToolResult.failed(f"Failed to extract document: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Target document path"},
                    "max_chars": {"type": "integer", "default": 32000},
                    "max_pages": {"type": "integer", "default": 50},
                },
                "required": ["file_path"],
            },
            requires_approval=False,
            timeout_seconds=20.0,
        )


class FileWriteTextTool(BaseTool):
    """Tool to write text content to a file inside an authorized directory."""

    name = "file_write_text"
    description = "Write or overwrite text content to a file inside an authorized directory with atomic safety."
    category = PermissionCategory.FILE_WRITE
    input_schema = FileWriteTextInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("File write cancelled by user")

        target_path = getattr(params, "file_path", "")
        content = getattr(params, "content", "")
        overwrite = getattr(params, "overwrite", False)
        encoding = getattr(params, "encoding", "utf-8")

        service = get_file_service()
        res = service.write_text(target_path, content, overwrite=overwrite, encoding=encoding)
        if not res.success:
            return ToolResult.failed(res.message)
        return ToolResult.success(data=res.details, message=res.message)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.MEDIUM,
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Target file path"},
                    "content": {"type": "string", "description": "Text content to write"},
                    "overwrite": {"type": "boolean", "default": False},
                    "encoding": {"type": "string", "default": "utf-8"},
                },
                "required": ["file_path", "content"],
            },
            requires_approval=True,
            timeout_seconds=15.0,
        )


class FileEditTextTool(BaseTool):
    """Tool to modify an existing text file by replacing exact strings or appending content."""

    name = "file_edit_text"
    description = "Edit an existing text file by replacing an exact string match or appending content, producing a diff."
    category = PermissionCategory.FILE_WRITE
    input_schema = FileEditTextInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("File edit cancelled by user")

        target_path = getattr(params, "file_path", "")
        target_str = getattr(params, "target_string", None)
        replacement_str = getattr(params, "replacement_string", None)
        append_content = getattr(params, "append_content", None)

        service = get_file_service()
        res = service.edit_text(
            target_path=target_path,
            target_string=target_str,
            replacement_string=replacement_str,
            append_content=append_content,
        )
        if not res.success:
            return ToolResult.failed(res.message)
        return ToolResult.success(data=res.details, message=res.message)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.MEDIUM,
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Target file path"},
                    "target_string": {
                        "type": "string",
                        "description": "Exact text to find and replace",
                    },
                    "replacement_string": {"type": "string", "description": "Replacement text"},
                    "append_content": {"type": "string", "description": "Text to append to file"},
                },
                "required": ["file_path"],
            },
            requires_approval=True,
            timeout_seconds=15.0,
        )


class FileCopyTool(BaseTool):
    """Tool to copy a file between authorized locations."""

    name = "file_copy"
    description = "Copy a file from one authorized path to another."
    category = PermissionCategory.FILE_WRITE
    input_schema = FileCopyInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("File copy cancelled by user")

        src = getattr(params, "source_path", "")
        dst = getattr(params, "dest_path", "")
        overwrite = getattr(params, "overwrite", False)

        service = get_file_service()
        res = service.copy_file(src, dst, overwrite=overwrite)
        if not res.success:
            return ToolResult.failed(res.message)
        return ToolResult.success(data=res.details, message=res.message)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "source_path": {"type": "string", "description": "Source file path"},
                    "dest_path": {"type": "string", "description": "Destination file path"},
                    "overwrite": {"type": "boolean", "default": False},
                },
                "required": ["source_path", "dest_path"],
            },
            requires_approval=False,
            timeout_seconds=15.0,
        )


class FileMoveTool(BaseTool):
    """Tool to move or rename a file between authorized locations."""

    name = "file_move"
    description = "Move or rename a file between authorized locations."
    category = PermissionCategory.FILE_WRITE
    input_schema = FileMoveInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("File move cancelled by user")

        src = getattr(params, "source_path", "")
        dst = getattr(params, "dest_path", "")
        overwrite = getattr(params, "overwrite", False)

        service = get_file_service()
        res = service.move_file(src, dst, overwrite=overwrite)
        if not res.success:
            return ToolResult.failed(res.message)
        return ToolResult.success(data=res.details, message=res.message)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.MEDIUM,
            parameters_schema={
                "type": "object",
                "properties": {
                    "source_path": {"type": "string", "description": "Source file path"},
                    "dest_path": {"type": "string", "description": "Destination file path"},
                    "overwrite": {"type": "boolean", "default": False},
                },
                "required": ["source_path", "dest_path"],
            },
            requires_approval=True,
            timeout_seconds=15.0,
        )


class FileDeleteTool(BaseTool):
    """Tool to delete a file or directory using Windows Recycle Bin (default) or permanent deletion with confirmation."""

    name = "file_delete"
    description = "Delete a file or directory inside an authorized path. By default, moves safely to Windows Recycle Bin."
    category = PermissionCategory.FILE_DELETE
    input_schema = FileDeleteInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("File deletion cancelled by user")

        target_path = getattr(params, "file_path", "")
        permanent = getattr(params, "permanent", False)

        service = get_file_service()
        res = service.delete_file(target_path, permanent=permanent)
        if not res.success:
            return ToolResult.failed(res.message)
        return ToolResult.success(data=res.details, message=res.message)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.HIGH,
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Target file or directory path"},
                    "permanent": {
                        "type": "boolean",
                        "default": False,
                        "description": "Permanently delete without Recycle Bin",
                    },
                },
                "required": ["file_path"],
            },
            requires_approval=True,
            timeout_seconds=15.0,
        )


class FileCompareDiffTool(BaseTool):
    """Tool to compute unified diff between two files."""

    name = "file_compare_diff"
    description = "Compare two text files and generate a unified diff."
    category = PermissionCategory.FILE_READ
    input_schema = FileCompareDiffInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Diff cancelled by user")

        fa = getattr(params, "file_path_a", "")
        fb = getattr(params, "file_path_b", "")
        max_lines = getattr(params, "max_diff_lines", 500)

        service = get_file_service()
        res = service.compare_diff(fa, fb, max_diff_lines=max_lines)
        if not res.success:
            return ToolResult.failed(res.message)
        return ToolResult.success(data=res.details, message=res.message)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "file_path_a": {"type": "string", "description": "First file path"},
                    "file_path_b": {"type": "string", "description": "Second file path"},
                    "max_diff_lines": {"type": "integer", "default": 500},
                },
                "required": ["file_path_a", "file_path_b"],
            },
            requires_approval=False,
            timeout_seconds=15.0,
        )


class FileFindDuplicatesTool(BaseTool):
    """Tool to find duplicate files via size clustering and SHA-256 hashes."""

    name = "file_find_duplicates"
    description = (
        "Scan an authorized directory for duplicate files based on content SHA-256 hashes."
    )
    category = PermissionCategory.FILE_READ
    input_schema = FileFindDuplicatesInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Duplicate scan cancelled by user")

        dir_path = getattr(params, "directory_path", "")
        min_size = getattr(params, "min_size_bytes", 1)
        max_files = getattr(params, "max_files", 500)

        service = get_file_service()
        res = service.find_duplicates(dir_path, min_size_bytes=min_size, max_files=max_files)
        if not res.success:
            return ToolResult.failed(res.message)
        return ToolResult.success(data=res.details, message=res.message)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "directory_path": {"type": "string", "description": "Directory to scan"},
                    "min_size_bytes": {"type": "integer", "default": 1},
                    "max_files": {"type": "integer", "default": 500},
                },
                "required": ["directory_path"],
            },
            requires_approval=False,
            timeout_seconds=30.0,
        )


class FileArchiveCreateTool(BaseTool):
    """Tool to create a ZIP archive of authorized files and directories."""

    name = "file_archive_create"
    description = "Create a safe ZIP archive from specified authorized files and directories."
    category = PermissionCategory.FILE_ARCHIVE
    input_schema = FileArchiveCreateInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Archive creation cancelled by user")

        archive_path = getattr(params, "archive_path", "")
        sources = getattr(params, "source_paths", [])

        service = get_file_service()
        res = service.create_archive(archive_path, sources)
        if not res.success:
            return ToolResult.failed(res.message)
        return ToolResult.success(data=res.details, message=res.message)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "archive_path": {"type": "string", "description": "Output .zip file path"},
                    "source_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of paths to archive",
                    },
                },
                "required": ["archive_path", "source_paths"],
            },
            requires_approval=False,
            timeout_seconds=30.0,
        )


class FileArchiveInspectTool(BaseTool):
    """Tool to inspect ZIP archive contents, sizes, and compression ratios without extracting."""

    name = "file_archive_inspect"
    description = "Inspect the entries, uncompressed sizes, and compression ratio of a ZIP archive without extracting it."
    category = PermissionCategory.FILE_ARCHIVE
    input_schema = FileArchiveInspectInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Archive inspection cancelled by user")

        archive_path = getattr(params, "archive_path", "")
        service = get_file_service()
        res = service.inspect_archive(archive_path)
        if not res.success:
            return ToolResult.failed(res.message)
        return ToolResult.success(data=res.details, message=res.message)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "archive_path": {"type": "string", "description": "Path to .zip archive"},
                },
                "required": ["archive_path"],
            },
            requires_approval=False,
            timeout_seconds=15.0,
        )


class FileArchiveExtractTool(BaseTool):
    """Tool to extract a ZIP archive with Zip Slip, bomb, and reserved name defenses."""

    name = "file_archive_extract"
    description = "Safely extract a ZIP archive into an authorized target directory with Zip Slip and bomb defenses."
    category = PermissionCategory.FILE_ARCHIVE
    input_schema = FileArchiveExtractInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Archive extraction cancelled by user")

        archive_path = getattr(params, "archive_path", "")
        target_dir = getattr(params, "target_directory", "")

        service = get_file_service()
        res = service.extract_archive(archive_path, target_dir)
        if not res.success:
            return ToolResult.failed(res.message)
        return ToolResult.success(data=res.details, message=res.message)

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.MEDIUM,
            parameters_schema={
                "type": "object",
                "properties": {
                    "archive_path": {"type": "string", "description": "Path to .zip archive"},
                    "target_directory": {
                        "type": "string",
                        "description": "Target directory to extract files into",
                    },
                },
                "required": ["archive_path", "target_directory"],
            },
            requires_approval=True,
            timeout_seconds=30.0,
        )
