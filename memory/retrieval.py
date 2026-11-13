"""Retrieval coordinator with FTS5 lexical matching, project filtering, and ranking."""

from __future__ import annotations

import re

from infrastructure.logging import get_logger
from memory.models import MemoryCategory, MemoryRecord, MemoryStatus
from memory.privacy import MemoryPrivacyManager
from memory.ranking import MemoryRanker, ScoredMemory
from memory.repository import MemoryRepository

logger = get_logger("memory.retrieval")


class MemoryRetriever:
    """Coordinates search, multi-signal ranking, and project-scoped memory retrieval."""

    def __init__(
        self,
        repository: MemoryRepository,
        ranker: MemoryRanker | None = None,
        privacy_manager: MemoryPrivacyManager | None = None,
    ) -> None:
        self.repository = repository
        self.ranker = ranker or MemoryRanker()
        self.privacy_manager = privacy_manager or MemoryPrivacyManager()

    def _sanitize_fts_query(self, query: str) -> str:
        """Sanitize query string into safe alphanumeric tokens for SQLite FTS5."""
        tokens = re.findall(r"\w+", query)
        if not tokens:
            return ""
        # Match each token as a prefix or exact term
        return " OR ".join(f'"{t}"*' for t in tokens[:10])

    def retrieve_candidates(
        self,
        query: str,
        project_id: str | None = None,
        category: MemoryCategory | None = None,
    ) -> list[MemoryRecord]:
        """Fetch active, approved memory records eligible for relevance ranking."""
        if not self.privacy_manager.is_retrieval_allowed():
            return []

        # 1. Clean up any expired records first
        self.repository.cleanup_expired()

        results_map: dict[str, MemoryRecord] = {}

        # Attempt FTS5 retrieval if available and query is present
        sanitized_fts = self._sanitize_fts_query(query) if query.strip() else ""
        if self.repository.is_fts5_available and sanitized_fts:
            try:
                conn = self.repository._get_connection()
                with self.repository._lock:
                    cur = conn.execute(
                        """
                        SELECT m.*
                        FROM memories m
                        JOIN memories_fts f ON m.id = f.id
                        WHERE memories_fts MATCH ?
                          AND m.status = ?
                          AND m.user_approved = 1
                        ORDER BY rank
                        LIMIT 30;
                        """,
                        (sanitized_fts, MemoryStatus.ACTIVE.value),
                    )
                    for r in cur.fetchall():
                        rec = MemoryRecord.from_row(r)
                        results_map[rec.id] = rec
            except Exception as exc:
                logger.debug(f"FTS5 candidate search fell back to SQL: {exc}")

        # 2. Add SQL-based candidates (guarantees general preferences and user profile records are considered)
        sql_records = self.repository.list_records(
            category=category,
            status=MemoryStatus.ACTIVE,
            user_approved_only=True,
            limit=50,
        )
        for r in sql_records:
            results_map[r.id] = r

        # 3. Filter by project scope:
        # Include if record has NO project_id OR matches the current project_id.
        # Exclude records explicitly belonging to a DIFFERENT project.
        filtered: list[MemoryRecord] = []
        for rec in results_map.values():
            if rec.status != MemoryStatus.ACTIVE or not rec.user_approved:
                continue
            if category is not None and rec.category != category:
                continue
            if project_id:
                if rec.project_id is not None and rec.project_id != project_id:
                    continue  # Belonging to another project
            else:
                if rec.project_id is not None:
                    continue  # Project-specific record when outside project scope
            filtered.append(rec)

        return filtered

    def retrieve(
        self,
        query: str,
        project_id: str | None = None,
        category: MemoryCategory | None = None,
        min_threshold: float = 0.15,
        limit: int = 5,
    ) -> list[ScoredMemory]:
        """Retrieve, rank, threshold-filter, and log memory access."""
        candidates = self.retrieve_candidates(query, project_id=project_id, category=category)
        if not candidates:
            return []

        ranked = self.ranker.rank_records(
            records=candidates,
            query=query,
            current_project_id=project_id,
            min_threshold=min_threshold,
            limit=limit,
        )

        # Record access timestamp for retrieved memories
        if ranked:
            self.repository.record_access([sm.record.id for sm in ranked])

        return ranked
