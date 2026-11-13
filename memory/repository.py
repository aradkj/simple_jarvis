"""SQLite persistence and full-text indexing repository for JARVIS memories."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from infrastructure.logging import get_logger
from infrastructure.paths import get_data_dir
from memory.models import MemoryCategory, MemoryRecord, MemoryStatus

logger = get_logger("memory.repository")


class MemoryRepository:
    """Thread-safe SQLite repository providing CRUD, search, and indexing for memories."""

    def __init__(
        self,
        db_path: Path | None = None,
        connection: sqlite3.Connection | None = None,
    ) -> None:
        self.db_path = db_path or (get_data_dir() / "jarvis.db")
        self._external_conn = connection
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._fts5_available: bool = False
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        if self._external_conn is not None:
            return self._external_conn
        if self._connection is None:
            self._connection = sqlite3.connect(
                database=str(self.db_path),
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL;")
            self._connection.execute("PRAGMA foreign_keys=ON;")
            if not self._initialized:
                self._initialized = True
                self.initialize()
        return self._connection

    def initialize(self) -> None:
        """Create database tables, indexes, and optional FTS5 virtual table."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS memories (
                        id TEXT PRIMARY KEY,
                        category TEXT NOT NULL,
                        key TEXT NOT NULL,
                        content TEXT NOT NULL,
                        normalized_content TEXT NOT NULL,
                        project_id TEXT,
                        source_conversation_id TEXT NOT NULL,
                        source_message_id TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        last_accessed_at TEXT NOT NULL,
                        expires_at TEXT,
                        importance REAL NOT NULL DEFAULT 0.5,
                        confidence REAL NOT NULL DEFAULT 1.0,
                        status TEXT NOT NULL DEFAULT 'active',
                        user_approved INTEGER NOT NULL DEFAULT 1,
                        content_fingerprint TEXT NOT NULL,
                        metadata TEXT
                    );

                    CREATE INDEX IF NOT EXISTS idx_memories_cat_status
                        ON memories(category, status);
                    CREATE INDEX IF NOT EXISTS idx_memories_proj_status
                        ON memories(project_id, status);
                    CREATE INDEX IF NOT EXISTS idx_memories_key
                        ON memories(key);
                    CREATE INDEX IF NOT EXISTS idx_memories_fingerprint
                        ON memories(content_fingerprint);
                    CREATE INDEX IF NOT EXISTS idx_memories_status_appr
                        ON memories(status, user_approved);
                    """
                )

                # Initialize FTS5 if supported
                try:
                    conn.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                            id UNINDEXED,
                            key,
                            content,
                            category UNINDEXED,
                            project_id UNINDEXED,
                            tokenize='porter unicode61'
                        );
                        """
                    )
                    self._fts5_available = True
                    logger.debug("SQLite FTS5 full-text search table initialized.")
                except Exception as exc:
                    self._fts5_available = False
                    logger.info(
                        f"FTS5 not active on this SQLite build ({exc}); using indexed SQL fallback."
                    )

    @property
    def is_fts5_available(self) -> bool:
        """True if SQLite FTS5 search table is enabled and operational."""
        return self._fts5_available

    def save(self, record: MemoryRecord) -> str:
        """Insert or update a memory record transactionally."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO memories (
                        id, category, key, content, normalized_content, project_id,
                        source_conversation_id, source_message_id, created_at, updated_at,
                        last_accessed_at, expires_at, importance, confidence, status,
                        user_approved, content_fingerprint, metadata
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        category = excluded.category,
                        key = excluded.key,
                        content = excluded.content,
                        normalized_content = excluded.normalized_content,
                        project_id = excluded.project_id,
                        source_conversation_id = excluded.source_conversation_id,
                        source_message_id = excluded.source_message_id,
                        updated_at = excluded.updated_at,
                        last_accessed_at = excluded.last_accessed_at,
                        expires_at = excluded.expires_at,
                        importance = excluded.importance,
                        confidence = excluded.confidence,
                        status = excluded.status,
                        user_approved = excluded.user_approved,
                        content_fingerprint = excluded.content_fingerprint,
                        metadata = excluded.metadata;
                    """,
                    (
                        record.id,
                        record.category.value,
                        record.key,
                        record.content,
                        record.normalized_content,
                        record.project_id,
                        record.source_conversation_id,
                        record.source_message_id,
                        record.created_at.isoformat(),
                        record.updated_at.isoformat(),
                        record.last_accessed_at.isoformat(),
                        record.expires_at.isoformat() if record.expires_at else None,
                        record.importance,
                        record.confidence,
                        record.status.value,
                        1 if record.user_approved else 0,
                        record.content_fingerprint,
                        json.dumps(record.metadata),
                    ),
                )

                if self._fts5_available:
                    # Sync FTS table
                    conn.execute("DELETE FROM memories_fts WHERE id = ?;", (record.id,))
                    if record.status in (MemoryStatus.ACTIVE, MemoryStatus.PENDING_APPROVAL):
                        conn.execute(
                            """
                            INSERT INTO memories_fts (id, key, content, category, project_id)
                            VALUES (?, ?, ?, ?, ?);
                            """,
                            (
                                record.id,
                                record.key,
                                record.content,
                                record.category.value,
                                record.project_id or "",
                            ),
                        )
        return record.id

    def get(self, memory_id: str) -> MemoryRecord | None:
        """Retrieve a memory record by ID."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute("SELECT * FROM memories WHERE id = ?;", (memory_id,))
            row = cursor.fetchone()
        if row:
            return MemoryRecord.from_row(row)
        return None

    def delete(self, memory_id: str, soft: bool = True) -> bool:
        """Delete a memory record (soft-delete sets status to 'deleted')."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                if soft:
                    now_iso = datetime.now(UTC).isoformat()
                    cur = conn.execute(
                        "UPDATE memories SET status = ?, updated_at = ? WHERE id = ?;",
                        (MemoryStatus.DELETED.value, now_iso, memory_id),
                    )
                else:
                    cur = conn.execute("DELETE FROM memories WHERE id = ?;", (memory_id,))

                if self._fts5_available:
                    conn.execute("DELETE FROM memories_fts WHERE id = ?;", (memory_id,))
                return cur.rowcount > 0

    def list_records(
        self,
        category: MemoryCategory | None = None,
        status: MemoryStatus | None = None,
        project_id: str | None = None,
        user_approved_only: bool = False,
        search_query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List memory records matching filter criteria."""
        clauses = []
        params: list[Any] = []

        if category is not None:
            clauses.append("category = ?")
            params.append(category.value if hasattr(category, "value") else str(category))
        if status is not None:
            clauses.append("status = ?")
            params.append(status.value if hasattr(status, "value") else str(status))
        else:
            # Exclude deleted by default unless explicitly asked
            clauses.append("status != ?")
            params.append(MemoryStatus.DELETED.value)

        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)

        if user_approved_only:
            clauses.append("user_approved = 1")

        if search_query.strip():
            clauses.append("(content LIKE ? OR key LIKE ?)")
            pat = f"%{search_query.strip()}%"
            params.extend([pat, pat])

        where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT * FROM memories {where_sql} ORDER BY updated_at DESC LIMIT ? OFFSET ?;"
        params.extend([limit, offset])

        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

        return [MemoryRecord.from_row(r) for r in rows]

    def find_conflicts(
        self, category: MemoryCategory, key: str, project_id: str | None = None
    ) -> list[MemoryRecord]:
        """Find active existing records that share the same category, key, and project."""
        if not key.strip():
            return []

        sql = """
            SELECT * FROM memories
            WHERE category = ? AND key = ? AND status = ?
        """
        params: list[Any] = [category.value, key.strip(), MemoryStatus.ACTIVE.value]

        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        else:
            sql += " AND project_id IS NULL"

        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()

        return [MemoryRecord.from_row(r) for r in rows]

    def mark_superseded(self, old_id: str, new_id: str) -> None:
        """Mark an old memory record as superseded by a new one."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                now_iso = datetime.now(UTC).isoformat()
                conn.execute(
                    """
                    UPDATE memories
                    SET status = ?, updated_at = ?
                    WHERE id = ?;
                    """,
                    (MemoryStatus.SUPERSEDED.value, now_iso, old_id),
                )
                if self._fts5_available:
                    conn.execute("DELETE FROM memories_fts WHERE id = ?;", (old_id,))

    def record_access(self, memory_ids: list[str]) -> None:
        """Update last_accessed_at timestamp for specified memory IDs."""
        if not memory_ids:
            return
        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._get_connection()
            with conn:
                placeholders = ",".join("?" for _ in memory_ids)
                conn.execute(
                    f"UPDATE memories SET last_accessed_at = ? WHERE id IN ({placeholders});",
                    [now_iso, *memory_ids],
                )

    def cleanup_expired(self) -> int:
        """Mark lapsed active records as expired and remove from search index."""
        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._get_connection()
            with conn:
                cur = conn.execute(
                    """
                    UPDATE memories
                    SET status = ?
                    WHERE status = ? AND expires_at IS NOT NULL AND expires_at < ?;
                    """,
                    (MemoryStatus.EXPIRED.value, MemoryStatus.ACTIVE.value, now_iso),
                )
                count = cur.rowcount
                if count > 0 and self._fts5_available:
                    conn.execute(
                        """
                        DELETE FROM memories_fts
                        WHERE id IN (SELECT id FROM memories WHERE status = ?);
                        """,
                        (MemoryStatus.EXPIRED.value,),
                    )
                return count

    def clear_all(self, project_id: str | None = None) -> int:
        """Completely delete memories, optionally filtered by project ID."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                if project_id:
                    cur = conn.execute("DELETE FROM memories WHERE project_id = ?;", (project_id,))
                    if self._fts5_available:
                        conn.execute(
                            "DELETE FROM memories_fts WHERE project_id = ?;", (project_id,)
                        )
                else:
                    cur = conn.execute("DELETE FROM memories;")
                    if self._fts5_available:
                        conn.execute("DELETE FROM memories_fts;")
                return cur.rowcount

    def close(self) -> None:
        """Close connection if locally managed."""
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                except Exception:
                    pass
                finally:
                    self._connection = None
