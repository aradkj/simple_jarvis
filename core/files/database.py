"""SQLite FTS5 Storage for JARVIS File Intelligence."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from core.files.models import FileIndexStats, FileSearchResult, IndexedFile
from infrastructure.logging import get_logger

logger = get_logger("files.database")


class FileIndexDatabase:
    """Manages SQLite database with FTS5 full-text indexing for files."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        if db_path is None:
            # Default to local data directory
            data_dir = Path.home() / ".jarvis" / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = data_dir / "file_index.db"
        else:
            self.db_path = Path(db_path)
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a configured SQLite connection."""
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        """Initialize schema including metadata table and FTS5 virtual table."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS files_meta (
                    path TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    mtime REAL NOT NULL,
                    ctime REAL NOT NULL,
                    is_binary INTEGER NOT NULL,
                    char_count INTEGER NOT NULL,
                    indexed_at REAL NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_files_ext ON files_meta(extension)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_files_mtime ON files_meta(mtime)
                """
            )

            # Virtual FTS5 table for bilingual & technical full text search
            # tokenize="unicode61" handles Latin, Arabic, and Persian scripts cleanly
            cursor.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                    path UNINDEXED,
                    filename,
                    extension,
                    content,
                    tokenize = 'unicode61'
                )
                """
            )
            conn.commit()

    def upsert_file(self, file: IndexedFile) -> None:
        """Insert or update a single file's metadata and FTS content."""
        self.batch_upsert([file])

    def batch_upsert(self, files: list[IndexedFile]) -> None:
        """Efficiently batch insert or update multiple files in a single transaction."""
        if not files:
            return

        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            for f in files:
                # 1. Update metadata
                cursor.execute(
                    """
                    INSERT INTO files_meta (
                        path, filename, extension, size_bytes, mtime, ctime,
                        is_binary, char_count, indexed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        filename=excluded.filename,
                        extension=excluded.extension,
                        size_bytes=excluded.size_bytes,
                        mtime=excluded.mtime,
                        ctime=excluded.ctime,
                        is_binary=excluded.is_binary,
                        char_count=excluded.char_count,
                        indexed_at=excluded.indexed_at
                    """,
                    (
                        f.path,
                        f.filename,
                        f.extension,
                        f.size_bytes,
                        f.mtime,
                        f.ctime,
                        1 if f.is_binary else 0,
                        f.char_count,
                        f.indexed_at,
                    ),
                )

                # 2. Update FTS index: delete old entry first then insert
                cursor.execute("DELETE FROM files_fts WHERE path = ?", (f.path,))
                cursor.execute(
                    """
                    INSERT INTO files_fts (path, filename, extension, content)
                    VALUES (?, ?, ?, ?)
                    """,
                    (f.path, f.filename, f.extension, f.content_excerpt),
                )

            conn.commit()

    def remove_missing_paths(self, valid_paths: set[str]) -> int:
        """Remove indexed files that no longer exist on disk."""
        removed_count = 0
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT path FROM files_meta")
            existing_db_paths = [row["path"] for row in cursor.fetchall()]

            for db_p in existing_db_paths:
                if db_p not in valid_paths:
                    cursor.execute("DELETE FROM files_meta WHERE path = ?", (db_p,))
                    cursor.execute("DELETE FROM files_fts WHERE path = ?", (db_p,))
                    removed_count += 1

            if removed_count > 0:
                conn.commit()

        return removed_count

    def remove_path(self, path: str) -> None:
        """Remove a specific path from the database."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM files_meta WHERE path = ?", (path,))
            cursor.execute("DELETE FROM files_fts WHERE path = ?", (path,))
            conn.commit()

    def get_file_metadata(self, path: str) -> dict[str, Any] | None:
        """Retrieve stored metadata for a file path."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files_meta WHERE path = ?", (path,))
            row = cursor.fetchone()
            if row:
                return dict(row)
        return None

    def search_fts(
        self,
        query: str,
        extension_filter: str | None = None,
        limit: int = 50,
    ) -> list[FileSearchResult]:
        """Perform full-text search against filenames and contents using SQLite FTS5."""
        if not query.strip():
            return []

        # Sanitize query for FTS5 (escape special characters like quotes and dashes)
        safe_terms = [
            f'"{term.replace('"', '""')}"*' for term in query.strip().split() if term.strip()
        ]
        if not safe_terms:
            return []
        fts_query = " OR ".join(safe_terms)

        results: list[FileSearchResult] = []
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()

            try:
                # Query with bm25 ranking and snippet generation
                sql = """
                    SELECT
                        m.path,
                        m.filename,
                        m.extension,
                        m.size_bytes,
                        m.mtime,
                        bm25(files_fts) AS rank,
                        snippet(files_fts, 3, '[', ']', '...', 16) AS excerpt
                    FROM files_fts
                    JOIN files_meta m ON files_fts.path = m.path
                    WHERE files_fts MATCH ?
                """
                params: list[Any] = [fts_query]

                if extension_filter:
                    norm_ext = extension_filter.lower()
                    if not norm_ext.startswith("."):
                        norm_ext = f".{norm_ext}"
                    sql += " AND m.extension = ?"
                    params.append(norm_ext)

                sql += " ORDER BY rank LIMIT ?"
                params.append(limit)

                cursor.execute(sql, params)
                for row in cursor.fetchall():
                    # In SQLite FTS5, lower bm25 score means more relevant (typically negative)
                    score = abs(float(row["rank"])) if row["rank"] else 1.0
                    results.append(
                        FileSearchResult(
                            path=row["path"],
                            filename=row["filename"],
                            extension=row["extension"],
                            size_bytes=row["size_bytes"],
                            mtime=row["mtime"],
                            relevance_score=score,
                            snippet=row["excerpt"] or "",
                            match_type="content",
                        )
                    )
            except sqlite3.OperationalError as exc:
                logger.warning(f"FTS search failed for query '{query}': {exc}")
                # Fallback to simple LIKE search on filename and path
                return self.search_like(query, extension_filter=extension_filter, limit=limit)

        return results

    def search_like(
        self,
        query: str,
        extension_filter: str | None = None,
        limit: int = 50,
    ) -> list[FileSearchResult]:
        """Fallback search using SQL LIKE on filename and path."""
        results: list[FileSearchResult] = []
        pattern = f"%{query.strip()}%"

        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            sql = """
                SELECT path, filename, extension, size_bytes, mtime
                FROM files_meta
                WHERE (filename LIKE ? OR path LIKE ?)
            """
            params: list[Any] = [pattern, pattern]

            if extension_filter:
                norm_ext = extension_filter.lower()
                if not norm_ext.startswith("."):
                    norm_ext = f".{norm_ext}"
                sql += " AND extension = ?"
                params.append(norm_ext)

            sql += " ORDER BY mtime DESC LIMIT ?"
            params.append(limit)

            cursor.execute(sql, params)
            for row in cursor.fetchall():
                results.append(
                    FileSearchResult(
                        path=row["path"],
                        filename=row["filename"],
                        extension=row["extension"],
                        size_bytes=row["size_bytes"],
                        mtime=row["mtime"],
                        relevance_score=1.0,
                        snippet="",
                        match_type="name",
                    )
                )

        return results

    def get_stats(self) -> FileIndexStats:
        """Compute aggregate index stats."""
        with self._lock, self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*), COALESCE(SUM(size_bytes), 0), MAX(indexed_at) FROM files_meta"
            )
            count_row = cursor.fetchone()
            total_files = count_row[0] or 0
            total_size = count_row[1] or 0
            last_indexed = count_row[2]

            cursor.execute(
                """
                SELECT extension, COUNT(*) as cnt
                FROM files_meta
                GROUP BY extension
                ORDER BY cnt DESC
                LIMIT 20
                """
            )
            exts = {row["extension"]: row["cnt"] for row in cursor.fetchall()}

        return FileIndexStats(
            total_files=total_files,
            total_size_bytes=total_size,
            indexed_extensions=exts,
            last_indexed_at=last_indexed,
        )
