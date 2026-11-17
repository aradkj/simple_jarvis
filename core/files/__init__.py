"""JARVIS File Intelligence Subsystem."""

from core.files.database import FileIndexDatabase
from core.files.discovery import FileDiscoveryService
from core.files.file_tools import (
    FileIndexSyncTool,
    FileInspectTool,
    FileOpenTool,
    FileSearchTool,
    get_file_database,
    get_file_indexer,
    get_file_search_engine,
)
from core.files.indexer import FileIndexer
from core.files.models import FileIndexStats, FileSearchResult, IndexedFile, IndexingScope
from core.files.search import FileSearchEngine

__all__ = [
    "FileDiscoveryService",
    "FileIndexDatabase",
    "FileIndexStats",
    "FileIndexSyncTool",
    "FileIndexer",
    "FileInspectTool",
    "FileOpenTool",
    "FileSearchEngine",
    "FileSearchResult",
    "FileSearchTool",
    "IndexedFile",
    "IndexingScope",
    "get_file_database",
    "get_file_indexer",
    "get_file_search_engine",
]
