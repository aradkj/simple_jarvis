"""Data models for JARVIS File Intelligence Subsystem."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class IndexedFile:
    """Metadata and searchable excerpt of an indexed file."""

    path: str
    filename: str
    extension: str
    size_bytes: int
    mtime: float
    ctime: float
    is_binary: bool = False
    content_excerpt: str = ""
    char_count: int = 0
    indexed_at: float = 0.0

    @property
    def modified_datetime(self) -> datetime:
        return datetime.fromtimestamp(self.mtime)


@dataclass
class FileSearchResult:
    """Result item returned by the FileSearchEngine."""

    path: str
    filename: str
    extension: str
    size_bytes: int
    mtime: float
    relevance_score: float
    snippet: str = ""
    match_type: str = "name"  # "name", "content", "path", "fuzzy"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "filename": self.filename,
            "extension": self.extension,
            "size_bytes": self.size_bytes,
            "modified": datetime.fromtimestamp(self.mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "relevance_score": round(self.relevance_score, 3),
            "snippet": self.snippet,
            "match_type": self.match_type,
        }


@dataclass
class IndexingScope:
    """Configuration defining directory boundaries and exclusions for file indexing."""

    root_paths: list[str] = field(default_factory=list)
    excluded_dir_names: set[str] = field(
        default_factory=lambda: {
            ".git",
            ".svn",
            ".hg",
            "node_modules",
            ".venv",
            "venv",
            "env",
            "__pycache__",
            ".pytest_cache",
            ".mypy_cache",
            ".ruff_cache",
            "AppData",
            "$Recycle.Bin",
            "System Volume Information",
            "Windows",
            "ProgramData",
        }
    )
    excluded_extensions: set[str] = field(
        default_factory=lambda: {
            ".iso",
            ".vmdk",
            ".img",
            ".cab",
            ".msi",
            ".sys",
            ".dll",
            ".obj",
            ".class",
            ".pyc",
            ".pyo",
            ".pyd",
            ".whl",
            ".tmp",
            ".bak",
        }
    )
    max_file_size_bytes: int = 50 * 1024 * 1024  # 50MB max file size to consider
    max_content_extract_bytes: int = 5 * 1024 * 1024  # 5MB max file size for content extraction
    max_excerpt_chars: int = 4000  # Cap extracted text indexed into FTS


@dataclass
class FileIndexStats:
    """Aggregate statistics for the file index."""

    total_files: int = 0
    total_size_bytes: int = 0
    indexed_extensions: dict[str, int] = field(default_factory=dict)
    last_indexed_at: float | None = None
