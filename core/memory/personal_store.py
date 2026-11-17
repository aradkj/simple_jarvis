"""Permanent Personal Memory & Identity Store for JARVIS.

Provides thread-safe, structured SQLite storage for:
- User profile & identity attributes
- People, contacts, and personal relationships
- User preferences (coding environments, tools, habits) with conflict resolution
- Structured user facts (subject-predicate-object)
- Assistant personality configuration
- JSON export, import, and backup capabilities
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from infrastructure.logging import get_logger
from infrastructure.paths import get_data_dir

logger = get_logger("memory.personal_store")


@dataclass
class PersonRecord:
    """Record representing a known person or relationship."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    relationship: str = ""  # e.g., friend, sister, colleague, manager, father
    occupation: str = ""  # e.g., graphic designer, software developer
    notes: str = ""
    attributes: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> PersonRecord:
        attr_raw = row["attributes"]
        attr_dict = {}
        if attr_raw:
            try:
                attr_dict = json.loads(attr_raw)
            except Exception:
                attr_dict = {}
        return cls(
            id=row["id"],
            name=row["name"],
            relationship=row["relationship"],
            occupation=row["occupation"] or "",
            notes=row["notes"] or "",
            attributes=attr_dict,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class FactRecord:
    """Discrete structured fact known about user, people, or projects."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    subject: str = ""  # e.g. "user", "Ali", "JARVIS project"
    predicate: str = ""  # e.g. "works_as", "prefers", "created", "located_at"
    object_val: str = ""  # e.g. "graphic designer", "VS Code", "C:\\AI\\jarvis"
    raw_statement: str = ""  # e.g. "Ali is a graphic designer"
    context: str = ""
    confirmed: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["object"] = self.object_val
        return d

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> FactRecord:
        return cls(
            id=row["id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object_val=row["object_val"],
            raw_statement=row["raw_statement"] or "",
            context=row["context"] or "",
            confirmed=bool(row["confirmed"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class PersonalityConfig:
    """Configurable personality, tone, and behavioral attributes for JARVIS."""

    assistant_name: str = "JARVIS"
    tone: str = "calm"  # calm, formal, friendly, direct, witty
    formality: str = "standard"  # formal, standard, casual
    detail_level: str = "balanced"  # concise, balanced, thorough
    proactivity: str = "balanced"  # reactive, balanced, proactive
    custom_instructions: str = ""
    enable_voice_humor: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PersonalityConfig:
        return cls(
            assistant_name=data.get("assistant_name", "JARVIS"),
            tone=data.get("tone", "calm"),
            formality=data.get("formality", "standard"),
            detail_level=data.get("detail_level", "balanced"),
            proactivity=data.get("proactivity", "balanced"),
            custom_instructions=data.get("custom_instructions", ""),
            enable_voice_humor=bool(data.get("enable_voice_humor", True)),
        )


class PersonalStore:
    """High-performance, thread-safe SQLite persistence engine for user identity & personal memory."""

    _instance: PersonalStore | None = None
    _lock = threading.RLock()

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (get_data_dir() / "personal_memory.db")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: sqlite3.Connection | None = None
        self._init_db()

    @classmethod
    def get_instance(cls, db_path: Path | None = None) -> PersonalStore:
        with cls._lock:
            if cls._instance is None:
                cls._instance = PersonalStore(db_path=db_path)
            return cls._instance

    def _get_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            self._connection = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                timeout=10.0,
            )
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA journal_mode=WAL;")
            self._connection.execute("PRAGMA synchronous=NORMAL;")
            self._connection.execute("PRAGMA foreign_keys=ON;")
        return self._connection

    def _init_db(self) -> None:
        """Create tables and indexes idempotently."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS personal_profile (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS people_relationships (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL UNIQUE,
                        relationship TEXT NOT NULL,
                        occupation TEXT,
                        notes TEXT,
                        attributes TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS personal_preferences (
                        category TEXT NOT NULL,
                        pref_key TEXT NOT NULL,
                        pref_value TEXT NOT NULL,
                        active INTEGER NOT NULL DEFAULT 1,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (category, pref_key)
                    );

                    CREATE TABLE IF NOT EXISTS user_facts (
                        id TEXT PRIMARY KEY,
                        subject TEXT NOT NULL,
                        predicate TEXT NOT NULL,
                        object_val TEXT NOT NULL,
                        raw_statement TEXT,
                        context TEXT,
                        confirmed INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS personality_config (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_people_name ON people_relationships(name);
                    CREATE INDEX IF NOT EXISTS idx_pref_cat ON personal_preferences(category);
                    CREATE INDEX IF NOT EXISTS idx_facts_subject ON user_facts(subject);
                    """
                )

                # Initialize default personality config if empty
                cur = conn.cursor()
                cur.execute("SELECT COUNT(*) as c FROM personality_config")
                row = cur.fetchone()
                if row and row["c"] == 0:
                    defaults = PersonalityConfig().to_dict()
                    now = datetime.now(UTC).isoformat()
                    cur.executemany(
                        "INSERT INTO personality_config (key, value, updated_at) VALUES (?, ?, ?)",
                        [(k, str(v), now) for k, v in defaults.items()],
                    )

    # -------------------------------------------------------------------------
    # Profile & Identity
    # -------------------------------------------------------------------------

    def set_profile_attribute(self, key: str, value: str) -> None:
        """Set or update a personal profile attribute (e.g., name, occupation, skills)."""
        key_clean = key.strip().lower()
        val_clean = value.strip()
        now = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO personal_profile (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                    """,
                    (key_clean, val_clean, now),
                )
        logger.info(f"Profile updated: {key_clean} = {val_clean}")

    def get_profile_attribute(self, key: str, default: str = "") -> str:
        """Retrieve a specific profile attribute."""
        key_clean = key.strip().lower()
        with self._lock:
            cur = self._get_connection().cursor()
            cur.execute("SELECT value FROM personal_profile WHERE key = ?", (key_clean,))
            row = cur.fetchone()
            return str(row["value"]) if row else default

    def get_full_profile(self) -> dict[str, str]:
        """Return all user profile attributes."""
        with self._lock:
            cur = self._get_connection().cursor()
            cur.execute("SELECT key, value FROM personal_profile")
            return {row["key"]: row["value"] for row in cur.fetchall()}

    def delete_profile_attribute(self, key: str) -> bool:
        """Delete a profile attribute."""
        key_clean = key.strip().lower()
        with self._lock:
            conn = self._get_connection()
            with conn:
                cur = conn.execute("DELETE FROM personal_profile WHERE key = ?", (key_clean,))
                return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # People & Relationships
    # -------------------------------------------------------------------------

    def add_or_update_person(
        self,
        name: str,
        relationship: str,
        occupation: str = "",
        notes: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> PersonRecord:
        """Store or update a person record."""
        name_clean = name.strip()
        rel_clean = relationship.strip()
        occ_clean = occupation.strip()
        notes_clean = notes.strip()
        attr_dict = attributes or {}
        now = datetime.now(UTC).isoformat()

        with self._lock:
            conn = self._get_connection()
            with conn:
                cur = conn.cursor()
                cur.execute(
                    "SELECT * FROM people_relationships WHERE LOWER(name) = LOWER(?)", (name_clean,)
                )
                existing = cur.fetchone()
                if existing:
                    rec_id = existing["id"]
                    # Merge notes and attributes if not provided
                    final_occ = occ_clean or existing["occupation"] or ""
                    final_notes = notes_clean or existing["notes"] or ""
                    final_rel = rel_clean or existing["relationship"]
                    cur.execute(
                        """
                        UPDATE people_relationships
                        SET relationship = ?, occupation = ?, notes = ?, attributes = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (final_rel, final_occ, final_notes, json.dumps(attr_dict), now, rec_id),
                    )
                else:
                    rec_id = str(uuid.uuid4())
                    cur.execute(
                        """
                        INSERT INTO people_relationships
                        (id, name, relationship, occupation, notes, attributes, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            rec_id,
                            name_clean,
                            rel_clean,
                            occ_clean,
                            notes_clean,
                            json.dumps(attr_dict),
                            now,
                            now,
                        ),
                    )

        rec = self.get_person(name_clean)
        logger.info(f"Person recorded: {name_clean} ({rel_clean}, {occ_clean})")
        return rec or PersonRecord(
            id=rec_id,
            name=name_clean,
            relationship=rel_clean,
            occupation=occ_clean,
            notes=notes_clean,
        )

    COMMON_BILINGUAL_NAMES: dict[str, str] = {
        "علی": "ali",
        "ali": "علی",
        "آراد": "arad",
        "arad": "آراد",
        "سارا": "sara",
        "sara": "سارا",
        "sarah": "سارا",
        "رضا": "reza",
        "reza": "رضا",
        "محمد": "mohammad",
        "mohammad": "محمد",
        "مهدی": "mehdi",
        "mehdi": "مهدی",
        "مریم": "maryam",
        "maryam": "مریم",
    }

    def get_person(self, name: str) -> PersonRecord | None:
        """Retrieve a person by name (case-insensitive, bilingual-aware)."""
        name_clean = name.strip()
        with self._lock:
            cur = self._get_connection().cursor()
            cur.execute(
                "SELECT * FROM people_relationships WHERE LOWER(name) = LOWER(?)", (name_clean,)
            )
            row = cur.fetchone()
            if row:
                return PersonRecord.from_row(row)
            # Try bilingual alias
            alias = self.COMMON_BILINGUAL_NAMES.get(name_clean.lower())
            if alias:
                cur.execute(
                    "SELECT * FROM people_relationships WHERE LOWER(name) = LOWER(?)", (alias,)
                )
                row = cur.fetchone()
                if row:
                    return PersonRecord.from_row(row)
            return None

    def find_people(self, query: str) -> list[PersonRecord]:
        """Find people matching a query (by name, relationship, or occupation)."""
        q = f"%{query.strip().lower()}%"
        with self._lock:
            cur = self._get_connection().cursor()
            cur.execute(
                """
                SELECT * FROM people_relationships
                WHERE LOWER(name) LIKE ? OR LOWER(relationship) LIKE ? OR LOWER(occupation) LIKE ? OR LOWER(notes) LIKE ?
                ORDER BY updated_at DESC
                """,
                (q, q, q, q),
            )
            return [PersonRecord.from_row(r) for r in cur.fetchall()]

    def list_people(self) -> list[PersonRecord]:
        """Return all known people."""
        with self._lock:
            cur = self._get_connection().cursor()
            cur.execute("SELECT * FROM people_relationships ORDER BY name ASC")
            return [PersonRecord.from_row(r) for r in cur.fetchall()]

    def delete_person(self, name: str) -> bool:
        """Delete a person by name (case-insensitive, bilingual-aware)."""
        name_clean = name.strip()
        with self._lock:
            conn = self._get_connection()
            with conn:
                cur = conn.execute(
                    "DELETE FROM people_relationships WHERE LOWER(name) = LOWER(?)",
                    (name_clean,),
                )
                if cur.rowcount > 0:
                    return True
                # Try bilingual alias
                alias = self.COMMON_BILINGUAL_NAMES.get(name_clean.lower())
                if alias:
                    cur = conn.execute(
                        "DELETE FROM people_relationships WHERE LOWER(name) = LOWER(?)",
                        (alias,),
                    )
                    return cur.rowcount > 0
                return False

    # -------------------------------------------------------------------------
    # Preferences & Conflict Resolution
    # -------------------------------------------------------------------------

    def set_preference(self, category: str, pref_key: str, pref_value: str) -> None:
        """Store or update a preference. Newer values actively supersede older ones."""
        cat_clean = category.strip().lower()
        key_clean = pref_key.strip().lower()
        val_clean = pref_value.strip()
        now = datetime.now(UTC).isoformat()

        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO personal_preferences (category, pref_key, pref_value, active, updated_at)
                    VALUES (?, ?, ?, 1, ?)
                    ON CONFLICT(category, pref_key) DO UPDATE
                    SET pref_value=excluded.pref_value, active=1, updated_at=excluded.updated_at
                    """,
                    (cat_clean, key_clean, val_clean, now),
                )
        logger.info(f"Preference updated: [{cat_clean}] {key_clean} = {val_clean}")

    def get_preference(self, category: str, pref_key: str, default: str = "") -> str:
        """Retrieve an active preference."""
        with self._lock:
            cur = self._get_connection().cursor()
            cur.execute(
                "SELECT pref_value FROM personal_preferences WHERE LOWER(category) = LOWER(?) AND LOWER(pref_key) = LOWER(?) AND active = 1",
                (category.strip(), pref_key.strip()),
            )
            row = cur.fetchone()
            return str(row["pref_value"]) if row else default

    def list_preferences(self, category: str | None = None) -> list[dict[str, Any]]:
        """List active preferences, optionally filtered by category."""
        with self._lock:
            cur = self._get_connection().cursor()
            if category:
                cur.execute(
                    "SELECT category, pref_key, pref_value, updated_at FROM personal_preferences WHERE LOWER(category) = LOWER(?) AND active = 1 ORDER BY pref_key ASC",
                    (category.strip(),),
                )
            else:
                cur.execute(
                    "SELECT category, pref_key, pref_value, updated_at FROM personal_preferences WHERE active = 1 ORDER BY category ASC, pref_key ASC"
                )
            return [
                {
                    "category": r["category"],
                    "key": r["pref_key"],
                    "value": r["pref_value"],
                    "updated_at": r["updated_at"],
                }
                for r in cur.fetchall()
            ]

    def delete_preference(self, category: str, pref_key: str) -> bool:
        """Delete or deactivate a preference."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                cur = conn.execute(
                    "DELETE FROM personal_preferences WHERE LOWER(category) = LOWER(?) AND LOWER(pref_key) = LOWER(?)",
                    (category.strip(), pref_key.strip()),
                )
                return cur.rowcount > 0

    # -------------------------------------------------------------------------
    # Structured User Facts
    # -------------------------------------------------------------------------

    def add_fact(
        self,
        subject: str,
        predicate: str,
        object_val: str,
        raw_statement: str = "",
        context: str = "",
    ) -> FactRecord:
        """Store a structured fact."""
        rec_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        sub = subject.strip()
        pred = predicate.strip()
        obj = object_val.strip()

        with self._lock:
            conn = self._get_connection()
            with conn:
                # Check if exact subject & predicate already exists; if so, update value
                cur = conn.cursor()
                cur.execute(
                    "SELECT id FROM user_facts WHERE LOWER(subject) = LOWER(?) AND LOWER(predicate) = LOWER(?)",
                    (sub, pred),
                )
                existing = cur.fetchone()
                if existing:
                    rec_id = existing["id"]
                    cur.execute(
                        """
                        UPDATE user_facts
                        SET object_val = ?, raw_statement = ?, context = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (obj, raw_statement or f"{sub} {pred} {obj}", context, now, rec_id),
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO user_facts
                        (id, subject, predicate, object_val, raw_statement, context, confirmed, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                        """,
                        (
                            rec_id,
                            sub,
                            pred,
                            obj,
                            raw_statement or f"{sub} {pred} {obj}",
                            context,
                            now,
                            now,
                        ),
                    )

        logger.info(f"Fact recorded: {sub} -> {pred} -> {obj}")
        return FactRecord(
            id=rec_id,
            subject=sub,
            predicate=pred,
            object_val=obj,
            raw_statement=raw_statement,
            context=context,
        )

    def find_facts(self, query: str = "", subject: str = "") -> list[FactRecord]:
        """Find facts by subject or textual query."""
        with self._lock:
            cur = self._get_connection().cursor()
            if subject:
                cur.execute(
                    "SELECT * FROM user_facts WHERE LOWER(subject) = LOWER(?) ORDER BY updated_at DESC",
                    (subject.strip(),),
                )
            elif query:
                q = f"%{query.strip().lower()}%"
                cur.execute(
                    """
                    SELECT * FROM user_facts
                    WHERE LOWER(subject) LIKE ? OR LOWER(predicate) LIKE ? OR LOWER(object_val) LIKE ? OR LOWER(raw_statement) LIKE ?
                    ORDER BY updated_at DESC
                    """,
                    (q, q, q, q),
                )
            else:
                cur.execute("SELECT * FROM user_facts ORDER BY updated_at DESC")
            return [FactRecord.from_row(r) for r in cur.fetchall()]

    def remember_project(
        self, project_name: str, path: str | Path, description: str = ""
    ) -> FactRecord:
        """Store or update a recognized software project path and metadata."""
        p_str = str(Path(path).resolve())
        return self.add_fact(
            subject=f"project:{project_name.lower().strip()}",
            predicate="project_path",
            object_val=p_str,
            raw_statement=f"Project '{project_name}' is located at {p_str}"
            + (f" ({description})" if description else ""),
        )

    def get_remembered_project_path(self, project_name: str) -> Path | None:
        """Retrieve remembered project path and physically verify on disk."""
        facts = self.find_facts(f"project:{project_name.lower().strip()}")
        for f in facts:
            if f.predicate == "project_path":
                p = Path(f.object_val)
                if p.exists() and p.is_dir():
                    return p
        return None

    def delete_fact(self, fact_id: str) -> bool:
        """Delete a single fact by ID."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                cur = conn.execute("DELETE FROM user_facts WHERE id = ?", (fact_id.strip(),))
                return cur.rowcount > 0

    def delete_facts_by_subject(self, subject: str) -> int:
        """Delete all facts for a given subject."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                cur = conn.execute(
                    "DELETE FROM user_facts WHERE LOWER(subject) = LOWER(?)",
                    (subject.strip(),),
                )
                return cur.rowcount

    # -------------------------------------------------------------------------
    # Personality Configuration
    # -------------------------------------------------------------------------

    def get_personality_config(self) -> PersonalityConfig:
        """Retrieve current personality settings."""
        with self._lock:
            cur = self._get_connection().cursor()
            cur.execute("SELECT key, value FROM personality_config")
            rows = {row["key"]: row["value"] for row in cur.fetchall()}
            if not rows:
                return PersonalityConfig()
            return PersonalityConfig(
                assistant_name=rows.get("assistant_name", "JARVIS"),
                tone=rows.get("tone", "calm"),
                formality=rows.get("formality", "standard"),
                detail_level=rows.get("detail_level", "balanced"),
                proactivity=rows.get("proactivity", "balanced"),
                custom_instructions=rows.get("custom_instructions", ""),
                enable_voice_humor=rows.get("enable_voice_humor", "True").lower() == "true",
            )

    def update_personality_config(self, config: PersonalityConfig) -> None:
        """Save updated personality configuration."""
        now = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._get_connection()
            with conn:
                cur = conn.cursor()
                for k, v in config.to_dict().items():
                    cur.execute(
                        """
                        INSERT INTO personality_config (key, value, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                        """,
                        (k, str(v), now),
                    )
        logger.info(
            f"Personality configuration updated: tone={config.tone}, formality={config.formality}"
        )

    # -------------------------------------------------------------------------
    # Backup, Export & Import
    # -------------------------------------------------------------------------

    def export_all_json(self) -> str:
        """Export the full personal identity, people, preferences, and facts database to JSON."""
        data = {
            "version": "1.0",
            "exported_at": datetime.now(UTC).isoformat(),
            "profile": self.get_full_profile(),
            "people": [p.to_dict() for p in self.list_people()],
            "preferences": self.list_preferences(),
            "facts": [f.to_dict() for f in self.find_facts()],
            "personality": self.get_personality_config().to_dict(),
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def import_all_json(self, json_str: str, overwrite: bool = False) -> dict[str, int]:
        """Import database from JSON backup with validation."""
        data = json.loads(json_str)
        counts = {"profile": 0, "people": 0, "preferences": 0, "facts": 0}

        if overwrite:
            self.clear_all()

        # Import profile
        profile = data.get("profile", {})
        for k, v in profile.items():
            self.set_profile_attribute(k, str(v))
            counts["profile"] += 1

        # Import people
        people = data.get("people", [])
        for p in people:
            self.add_or_update_person(
                name=p["name"],
                relationship=p["relationship"],
                occupation=p.get("occupation", ""),
                notes=p.get("notes", ""),
                attributes=p.get("attributes", {}),
            )
            counts["people"] += 1

        # Import preferences
        prefs = data.get("preferences", [])
        for pref in prefs:
            self.set_preference(pref["category"], pref["key"], pref["value"])
            counts["preferences"] += 1

        # Import facts
        facts = data.get("facts", [])
        for f in facts:
            obj_val = f.get("object_val") or f.get("object", "")
            self.add_fact(
                subject=f["subject"],
                predicate=f["predicate"],
                object_val=obj_val,
                raw_statement=f.get("raw_statement", ""),
                context=f.get("context", ""),
            )
            counts["facts"] += 1

        # Import personality
        if "personality" in data:
            self.update_personality_config(PersonalityConfig.from_dict(data["personality"]))

        logger.info(f"Imported personal memory: {counts}")
        return counts

    def clear_all(self) -> None:
        """Clear all personal profile, people, preferences, and facts."""
        with self._lock:
            conn = self._get_connection()
            with conn:
                conn.execute("DELETE FROM personal_profile;")
                conn.execute("DELETE FROM people_relationships;")
                conn.execute("DELETE FROM personal_preferences;")
                conn.execute("DELETE FROM user_facts;")
        logger.info("Cleared all personal memory store tables.")

    # -------------------------------------------------------------------------
    # Context Injection Builder
    # -------------------------------------------------------------------------

    def build_memory_summary_block(self) -> str:
        """Generate a concise, sandboxed system prompt block of personal identity and memory."""
        lines = []

        # Profile
        profile = self.get_full_profile()
        if profile:
            lines.append("# User Identity & Profile:")
            for k, v in profile.items():
                lines.append(f"- {k.capitalize()}: {v}")

        # People
        people = self.list_people()
        if people:
            lines.append("\n# Known People & Relationships:")
            for p in people:
                occ_part = f" ({p.occupation})" if p.occupation else ""
                lines.append(f"- {p.name}: {p.relationship}{occ_part}. {p.notes}".strip())

        # Preferences
        prefs = self.list_preferences()
        if prefs:
            lines.append("\n# Active User Preferences:")
            for pref in prefs:
                lines.append(f"- [{pref['category']}] {pref['key']}: {pref['value']}")

        # Facts
        facts = self.find_facts()
        if facts:
            lines.append("\n# Known Personal Facts:")
            for f in facts[:15]:  # Bounded to top 15 most recent
                lines.append(f"- {f.subject} -> {f.predicate} -> {f.object_val}")

        return "\n".join(lines)
