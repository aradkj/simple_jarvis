"""Executable tools for JARVIS File Intelligence."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.files.database import FileIndexDatabase
from core.files.indexer import FileIndexer
from core.files.search import FileSearchEngine
from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from infrastructure.logging import get_logger
from tools.base import BaseTool, ToolResult

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext

logger = get_logger("files.tools")

# Global instances for sharing between tools
_db_instance: FileIndexDatabase | None = None
_indexer_instance: FileIndexer | None = None
_search_instance: FileSearchEngine | None = None


def get_file_database() -> FileIndexDatabase:
    global _db_instance
    if _db_instance is None:
        _db_instance = FileIndexDatabase()
    return _db_instance


def get_file_indexer() -> FileIndexer:
    global _indexer_instance
    if _indexer_instance is None:
        _indexer_instance = FileIndexer(db=get_file_database())
    return _indexer_instance


def get_file_search_engine() -> FileSearchEngine:
    global _search_instance
    if _search_instance is None:
        _search_instance = FileSearchEngine(db=get_file_database())
    return _search_instance


class FileSearchInput(BaseModel):
    query: str = Field(description="Search terms or natural language query (Persian or English)")
    extension: str | None = Field(
        default=None, description="Optional extension filter, e.g. '.pdf' or 'docx'"
    )
    limit: int = Field(default=20, description="Maximum number of results to return")


class FileSearchTool(BaseTool):
    """Search for files across the laptop by filename, path, or extracted content."""

    name = "file_search"
    description = (
        "Search local files by natural language query, filename, or content in Persian or English."
    )
    category = PermissionCategory.FILE_SEARCH
    input_schema = FileSearchInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        assert isinstance(params, FileSearchInput)
        try:
            # If database is completely empty, run a quick sync index pass first
            engine = get_file_search_engine()
            stats = engine.db.get_stats()
            if stats.total_files == 0:
                indexer = get_file_indexer()
                indexer.run_sync_index(max_files=100)

            results = engine.search(
                query=params.query,
                extension_filter=params.extension,
                limit=params.limit,
            )

            data = {
                "query": params.query,
                "count": len(results),
                "files": [r.to_dict() for r in results],
            }
            return ToolResult.success(data)
        except Exception as exc:
            logger.error(f"file_search failed: {exc}", exc_info=True)
            return ToolResult.failed(f"File search failed: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema=cls.input_schema.model_json_schema(),
            requires_approval=False,
        )


class FileOpenInput(BaseModel):
    file_path: str = Field(description="Absolute or relative path of the file to open")
    application: str | None = Field(
        default=None, description="Specific program to open with (e.g. 'code', 'notepad')"
    )


class FileOpenTool(BaseTool):
    """Open a file in its default Windows application or a specified program."""

    name = "file_open"
    description = "Open a local file in its default Windows application or in a specific program like VS Code or Notepad."
    category = PermissionCategory.WINDOWS_OPERATION
    input_schema = FileOpenInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        assert isinstance(params, FileOpenInput)
        try:
            target = Path(params.file_path).resolve()
            if not target.exists():
                # Try finding it via search if partial name was passed
                engine = get_file_search_engine()
                matches = engine.search(params.file_path, limit=1)
                if matches:
                    target = Path(matches[0].path)
                else:
                    return ToolResult.failed(f"File not found: '{params.file_path}'")

            if params.application:
                app_cmd = params.application.lower()
                if app_cmd in ("code", "vscode"):
                    subprocess.Popen(["code", str(target)], shell=True)
                elif app_cmd == "notepad":
                    subprocess.Popen(["notepad.exe", str(target)])
                else:
                    subprocess.Popen([app_cmd, str(target)], shell=True)
            else:
                # Use native Windows default file association
                os.startfile(str(target))

            return ToolResult.success(
                {
                    "status": "opened",
                    "file_path": str(target),
                    "application": params.application or "default",
                }
            )
        except Exception as exc:
            logger.error(f"file_open failed: {exc}", exc_info=True)
            return ToolResult.failed(f"Failed to open file: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema=cls.input_schema.model_json_schema(),
            requires_approval=False,
        )


class FileInspectInput(BaseModel):
    file_path: str = Field(description="Path of file to inspect")
    max_lines: int = Field(default=80, description="Maximum lines of content to read")


class FileInspectTool(BaseTool):
    """Inspect file metadata and safe head preview."""

    name = "file_inspect"
    description = "Inspect local file metadata, size, line count, and safe text content preview."
    category = PermissionCategory.FILE_READ
    input_schema = FileInspectInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        assert isinstance(params, FileInspectInput)
        try:
            target = Path(params.file_path).resolve()
            if not target.is_file():
                return ToolResult.failed(f"File does not exist: '{params.file_path}'")

            stat = target.stat()
            lines: list[str] = []
            is_text = True

            try:
                with open(target, encoding="utf-8", errors="replace") as f:
                    for _ in range(params.max_lines):
                        line = f.readline()
                        if not line:
                            break
                        lines.append(line.rstrip("\r\n"))
            except Exception:
                is_text = False

            data = {
                "file_path": str(target),
                "filename": target.name,
                "size_bytes": stat.st_size,
                "is_text": is_text,
                "preview_lines": lines if is_text else [],
                "preview_line_count": len(lines),
            }
            return ToolResult.success(data)
        except Exception as exc:
            return ToolResult.failed(f"Inspection error: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema=cls.input_schema.model_json_schema(),
            requires_approval=False,
        )


class FileIndexSyncInput(BaseModel):
    max_files: int | None = Field(default=500, description="Max files to scan/index in this pass")


class FileIndexSyncTool(BaseTool):
    """Trigger or refresh the local file intelligence index."""

    name = "file_index_sync"
    description = "Synchronize and update the local file intelligence index."
    category = PermissionCategory.FILE_SEARCH
    input_schema = FileIndexSyncInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        assert isinstance(params, FileIndexSyncInput)
        try:
            indexer = get_file_indexer()
            indexed_count = indexer.run_sync_index(max_files=params.max_files)
            stats = indexer.db.get_stats()
            return ToolResult.success(
                {
                    "updated_files": indexed_count,
                    "total_indexed": stats.total_files,
                    "total_size_mb": round(stats.total_size_bytes / (1024 * 1024), 2),
                }
            )
        except Exception as exc:
            return ToolResult.failed(f"Sync failed: {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema=cls.input_schema.model_json_schema(),
            requires_approval=False,
        )
