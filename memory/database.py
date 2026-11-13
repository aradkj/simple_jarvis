"""SQLite storage engine implementation for JARVIS memory foundation."""

import contextlib
import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from infrastructure.logging import get_logger
from infrastructure.paths import get_data_dir
from memory.base import BaseMemoryStore, ConversationMessage, MessageRole, MessageStatus

logger = get_logger("memory.database")


class SQLiteMemoryStore(BaseMemoryStore):
    """Local SQLite memory store providing persistent conversation history and key-value state."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (get_data_dir() / "jarvis.db")
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        """Obtain a reusable connection configured with WAL journal mode."""
        if self._connection is None:
            self._connection = sqlite3.connect(
                database=str(self.db_path),
                check_same_thread=False,
            )
            self._connection.row_factory = sqlite3.Row
            # Enable WAL mode and foreign keys for performance and data integrity
            self._connection.execute("PRAGMA journal_mode=WAL;")
            self._connection.execute("PRAGMA foreign_keys=ON;")
            if not self._initialized:
                self._initialized = True
                self.initialize()
        return self._connection

    def initialize(self) -> None:
        """Create necessary database schema and execute safe migrations."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS sessions (
                        session_id TEXT PRIMARY KEY,
                        title TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS messages (
                        message_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        status TEXT DEFAULT 'completed',
                        model TEXT,
                        metadata TEXT,
                        interruption_reason TEXT,
                        provider_id TEXT,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS preferences (
                        pref_key TEXT PRIMARY KEY,
                        pref_value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_messages_session_id
                        ON messages(session_id, created_at);

                    -- Phase 5 Persistent Memory Table
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

                # Initialize FTS5 virtual table if supported
                with contextlib.suppress(Exception):
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

                # Safe idempotent migration: ensure columns exist
                cursor = conn.execute("PRAGMA table_info(messages);")
                columns = [col["name"] for col in cursor.fetchall()]
                if "status" not in columns:
                    conn.execute("ALTER TABLE messages ADD COLUMN status TEXT DEFAULT 'completed';")
                if "model" not in columns:
                    conn.execute("ALTER TABLE messages ADD COLUMN model TEXT;")
                if "interruption_reason" not in columns:
                    conn.execute("ALTER TABLE messages ADD COLUMN interruption_reason TEXT;")
                if "provider_id" not in columns:
                    conn.execute("ALTER TABLE messages ADD COLUMN provider_id TEXT;")

        logger.debug(f"SQLite memory database initialized at {self.db_path}")

    def create_session(self, title: str = "New Conversation") -> str:
        """Create a new conversation session record and return its ID."""
        session_id = str(uuid.uuid4())
        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO sessions (session_id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?);
                    """,
                    (session_id, title, now_iso, now_iso),
                )
        return session_id

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """List conversation sessions sorted by most recently updated."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                """
                SELECT session_id, title, created_at, updated_at
                FROM sessions
                ORDER BY updated_at DESC
                LIMIT ?;
                """,
                (limit,),
            )
            return [dict(row) for row in cursor.fetchall()]

    def store_message(self, message: ConversationMessage) -> str:
        """Store a conversation message in the database."""
        msg_id = message.message_id or str(uuid.uuid4())
        created_at_iso = message.created_at.isoformat()
        metadata_json = json.dumps(message.metadata, default=str)

        with self._lock:
            conn = self._get_connection()
            with conn:
                # Ensure session entry exists
                conn.execute(
                    """
                    INSERT OR IGNORE INTO sessions (session_id, title, created_at, updated_at)
                    VALUES (?, ?, ?, ?);
                    """,
                    (message.session_id, "Conversation Session", created_at_iso, created_at_iso),
                )
                # Insert message
                conn.execute(
                    """
                    INSERT INTO messages (
                        message_id, session_id, role, content, status, model, metadata, interruption_reason, provider_id, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        msg_id,
                        message.session_id,
                        message.role.value,
                        message.content,
                        message.status.value,
                        message.model,
                        metadata_json,
                        message.interruption_reason,
                        message.provider_id,
                        created_at_iso,
                    ),
                )
                # Update session timestamp
                conn.execute(
                    "UPDATE sessions SET updated_at = ? WHERE session_id = ?;",
                    (created_at_iso, message.session_id),
                )
        return msg_id

    def update_message_content(
        self,
        message_id: str,
        content: str,
        status: MessageStatus = MessageStatus.COMPLETED,
        interruption_reason: str | None = None,
        provider_id: str | None = None,
        model_id: str | None = None,
    ) -> None:
        """Update the content and delivery status of an existing message."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                # Update existing message, updating metadata and interruption_reason if supplied
                if (
                    interruption_reason is not None
                    or provider_id is not None
                    or model_id is not None
                ):
                    # Fetch existing metadata
                    cur = conn.execute(
                        "SELECT metadata, model FROM messages WHERE message_id = ?;", (message_id,)
                    )
                    row = cur.fetchone()
                    meta = {}
                    current_model = model_id
                    if row:
                        if not current_model and row["model"]:
                            current_model = row["model"]
                        if row["metadata"]:
                            try:
                                meta = json.loads(row["metadata"])
                            except Exception:
                                meta = {}
                    str_interruption = (
                        str(interruption_reason) if interruption_reason is not None else None
                    )
                    str_provider = str(provider_id) if provider_id is not None else None
                    str_model = str(current_model) if current_model is not None else None

                    if str_interruption is not None:
                        meta["interruption_reason"] = str_interruption
                    if str_provider is not None:
                        meta["provider_id"] = str_provider
                    if str_model is not None:
                        meta["model_id"] = str_model

                    conn.execute(
                        """
                        UPDATE messages
                        SET content = ?, status = ?, model = COALESCE(?, model), metadata = ?, interruption_reason = ?, provider_id = COALESCE(?, provider_id)
                        WHERE message_id = ?;
                        """,
                        (
                            content,
                            status.value,
                            str_model,
                            json.dumps(meta, default=str),
                            str_interruption,
                            str_provider,
                            message_id,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE messages
                        SET content = ?, status = ?
                        WHERE message_id = ?;
                        """,
                        (content, status.value, message_id),
                    )

    def get_messages(self, session_id: str, limit: int = 50) -> list[ConversationMessage]:
        """Retrieve recent conversation messages for a session in deterministic chronological order."""
        with self._lock:
            conn = self._get_connection()
            # Inspect table columns to safely support legacy schemas during test transitions
            cur_info = conn.execute("PRAGMA table_info(messages);")
            col_names = {c["name"] for c in cur_info.fetchall()}
            has_interruption = "interruption_reason" in col_names
            has_provider = "provider_id" in col_names

            select_cols = [
                "message_id",
                "session_id",
                "role",
                "content",
                "status",
                "model",
                "metadata",
                "created_at",
            ]
            if has_interruption:
                select_cols.append("interruption_reason")
            if has_provider:
                select_cols.append("provider_id")

            cursor = conn.execute(
                f"""
                SELECT {", ".join(select_cols)}
                FROM messages
                WHERE session_id = ?
                ORDER BY created_at ASC, rowid ASC
                LIMIT ?;
                """,
                (session_id, limit),
            )
            rows = cursor.fetchall()

        messages: list[ConversationMessage] = []
        for r in rows:
            row_dict = dict(r)
            meta = {}
            if row_dict.get("metadata"):
                try:
                    meta = json.loads(row_dict["metadata"])
                except Exception:
                    meta = {}

            status_val = row_dict.get("status") or "completed"
            try:
                msg_status = MessageStatus(status_val)
            except ValueError:
                msg_status = MessageStatus.COMPLETED

            model_val = row_dict.get("model")
            interruption_val = row_dict.get("interruption_reason") or meta.get(
                "interruption_reason"
            )
            provider_val = row_dict.get("provider_id") or meta.get("provider_id")

            messages.append(
                ConversationMessage(
                    message_id=row_dict["message_id"],
                    session_id=row_dict["session_id"],
                    role=MessageRole(row_dict["role"]),
                    content=row_dict["content"],
                    status=msg_status,
                    model=model_val,
                    metadata=meta,
                    interruption_reason=interruption_val,
                    provider_id=provider_val,
                    created_at=datetime.fromisoformat(row_dict["created_at"]),
                )
            )
        return messages

    def clear_session_messages(self, session_id: str) -> None:
        """Delete all messages belonging strictly to the specified session."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("DELETE FROM messages WHERE session_id = ?;", (session_id,))

    def set_preference(self, key: str, value: str) -> None:
        """Store or update a user preference."""
        now_iso = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO preferences (pref_key, pref_value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(pref_key) DO UPDATE SET
                        pref_value = excluded.pref_value,
                        updated_at = excluded.updated_at;
                    """,
                    (key, value, now_iso),
                )

    def get_preference(self, key: str, default: str | None = None) -> str | None:
        """Retrieve a user preference by key."""
        with self._lock:
            conn = self._get_connection()
            cursor = conn.execute(
                "SELECT pref_value FROM preferences WHERE pref_key = ?;",
                (key,),
            )
            row = cursor.fetchone()
        if row:
            return str(row["pref_value"])
        return default

    def close(self) -> None:
        """Close the database connection safely."""
        with self._lock:
            if self._connection is not None:
                try:
                    self._connection.close()
                    logger.debug("Closed SQLite memory database connection.")
                except Exception as exc:
                    logger.warning(f"Error closing SQLite connection: {exc}")
                finally:
                    self._connection = None
