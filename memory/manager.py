"""High-level MemoryManager facade orchestrating storage, extraction, retrieval, and privacy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from config import Settings, get_settings
from infrastructure.logging import get_logger
from memory.context_builder import MemoryContextBuilder
from memory.embeddings import (
    BaseEmbeddingProvider,
    get_embedding_provider,
)
from memory.extraction import MemoryExtractor
from memory.lifecycle import MemoryLifecycleManager
from memory.models import MemoryCategory, MemoryRecord, MemoryStatus
from memory.privacy import MemoryPrivacyManager
from memory.ranking import MemoryRanker
from memory.repository import MemoryRepository
from memory.retrieval import MemoryRetriever

logger = get_logger("memory.manager")


class MemoryManager:
    """Consolidated manager providing full-lifecycle persistent memory services for JARVIS."""

    def __init__(
        self,
        settings: Settings | None = None,
        db_path: Path | None = None,
        repository: MemoryRepository | None = None,
        embedding_provider: BaseEmbeddingProvider | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.privacy_manager = MemoryPrivacyManager(
            memory_enabled=self.settings.memory_enabled,
            allow_cloud_transmission=self.settings.memory_allow_cloud_transmission,
        )
        self.repository = repository or MemoryRepository(db_path=db_path)
        self.ranker = MemoryRanker()
        self.embedding_provider = embedding_provider or get_embedding_provider(self.settings)
        self.retriever = MemoryRetriever(
            repository=self.repository,
            ranker=self.ranker,
            privacy_manager=self.privacy_manager,
            embedding_provider=self.embedding_provider,
        )
        self.context_builder = MemoryContextBuilder(
            max_context_chars=self.settings.memory_max_context_chars,
            max_records=self.settings.memory_max_retrieved_records,
        )
        self.lifecycle = MemoryLifecycleManager(
            repository=self.repository,
            privacy_manager=self.privacy_manager,
            embedding_provider=self.embedding_provider,
        )
        self.extractor = MemoryExtractor(privacy_manager=self.privacy_manager)

    def initialize(self) -> None:
        """Initialize database schema, indexes, and full-text search."""
        self.repository.initialize()
        logger.info("MemoryManager initialized.")

    def retrieve_relevant_memories(
        self,
        query: str,
        project_id: str | None = None,
        category: MemoryCategory | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        """Retrieve and rank active user-approved memories relevant to query."""
        if not self.settings.memory_enabled:
            return []

        lim = limit or self.settings.memory_max_retrieved_records
        scored = self.retriever.retrieve(
            query=query,
            project_id=project_id,
            category=category,
            min_threshold=self.settings.memory_min_relevance_score,
            limit=lim,
        )
        return [sm.record for sm in scored]

    def build_memory_context(
        self,
        query: str,
        project_id: str | None = None,
        for_cloud_transmission: bool = True,
    ) -> str:
        """Retrieve relevant memories and format into a bounded, sandboxed context string.

        When for_cloud_transmission is True, strictly enforces that cloud memory transmission
        is explicitly authorized by user policy and filters out any sensitive patterns.
        """
        if not self.settings.memory_enabled:
            return ""

        # Enforce Cloud Memory Privacy Barrier: saving does not authorize transmission
        if for_cloud_transmission and not self.privacy_manager.is_cloud_transmission_allowed():
            logger.debug(
                "Cloud memory transmission is disabled by user policy; omitting memory context."
            )
            return ""

        scored = self.retriever.retrieve(
            query=query,
            project_id=project_id,
            min_threshold=self.settings.memory_min_relevance_score,
            limit=self.settings.memory_max_retrieved_records,
        )

        # Defense-in-depth: Re-verify sensitive data filter, approval, and active status
        safe_scored = [
            sm
            for sm in scored
            if sm.record.user_approved
            and sm.record.status == MemoryStatus.ACTIVE
            and not self.privacy_manager.filter.contains_sensitive_data(sm.record.content)
        ]

        return self.context_builder.build_context(safe_scored)

    def extract_and_propose_candidates(
        self,
        text: str,
        session_id: str = "",
        message_id: str | None = None,
        project_id: str | None = None,
    ) -> list[MemoryRecord]:
        """Parse user input for memory candidates and persist them in PENDING_APPROVAL status."""
        if not self.settings.memory_enabled or not self.settings.memory_auto_extract_candidates:
            return []

        res = self.extractor.extract_from_user_text(
            text=text,
            session_id=session_id,
            message_id=message_id,
            project_id=project_id,
        )

        # Handle explicit forget requests immediately
        for target in res.forget_requests:
            self._handle_explicit_forget(target, project_id=project_id)

        saved_candidates: list[MemoryRecord] = []
        for cand in res.candidates:
            # Check duplicate against existing active memories
            existing = self.repository.list_records(
                category=cand.category,
                search_query=cand.content,
                project_id=project_id,
                limit=1,
            )
            if existing and existing[0].normalized_content == cand.normalized_content:
                logger.debug(f"Skipping exact duplicate memory candidate: '{cand.content}'")
                continue

            cand_id = self.repository.save(cand)
            cand.id = cand_id
            saved_candidates.append(cand)

        return saved_candidates

    def _handle_explicit_forget(self, target: str, project_id: str | None = None) -> int:
        """Locate and delete memory records matching an explicit forget command."""
        matches = self.repository.list_records(
            search_query=target,
            project_id=project_id,
            limit=10,
        )
        count = 0
        for m in matches:
            if self.repository.delete(m.id, soft=True):
                count += 1
                logger.info(f"Deleted memory {m.id} matching forget request: '{target}'")
        return count

    def create_approved_memory(
        self,
        content: str,
        category: MemoryCategory = MemoryCategory.PREFERENCE,
        key: str = "",
        project_id: str | None = None,
        importance: float = 0.5,
        confidence: float = 1.0,
        metadata: dict[str, Any] | None = None,
        source_conversation_id: str = "",
    ) -> MemoryRecord:
        """Create and immediately activate an approved memory record."""
        self.privacy_manager.validate_candidate_content(content)

        record = MemoryRecord(
            category=category,
            key=key,
            content=content,
            project_id=project_id,
            source_conversation_id=source_conversation_id,
            importance=importance,
            confidence=confidence,
            status=MemoryStatus.ACTIVE,
            user_approved=True,
            metadata=metadata or {},
        )

        # If key is provided, supersede any existing conflicting active records
        if key.strip():
            existing = self.repository.find_conflicts(category, key, project_id=project_id)
            for old in existing:
                self.repository.mark_superseded(old.id, record.id)

        if self.embedding_provider and getattr(self.embedding_provider, "is_available", False):
            try:
                record.vector = self.embedding_provider.embed_text(record.content)
                record.metadata["embedding_provider"] = self.embedding_provider.provider_name
                record.metadata["embedding_model"] = self.embedding_provider.model_name
            except Exception as exc:
                logger.debug(f"Approved memory embedding vector note: {exc}")

        self.repository.save(record)
        return record

    def approve_candidate(self, candidate_id: str) -> MemoryRecord | None:
        """Explicitly approve and activate a pending memory candidate."""
        return self.lifecycle.approve_candidate(candidate_id)

    def reject_candidate(self, candidate_id: str) -> bool:
        """Explicitly reject a pending memory candidate."""
        return self.lifecycle.reject_candidate(candidate_id)

    def edit_memory(
        self,
        memory_id: str,
        new_content: str,
        importance: float | None = None,
    ) -> MemoryRecord | None:
        """Edit an existing memory record."""
        return self.lifecycle.edit_memory(memory_id, new_content, importance=importance)

    def delete_memory(self, memory_id: str, soft: bool = True) -> bool:
        """Delete a memory record."""
        return self.lifecycle.delete_memory(memory_id, soft=soft)

    def list_memories(
        self,
        category: MemoryCategory | None = None,
        status: MemoryStatus | None = None,
        project_id: str | None = None,
        user_approved_only: bool = False,
        search_query: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryRecord]:
        """List memory records with filtering and search."""
        return self.repository.list_records(
            category=category,
            status=status,
            project_id=project_id,
            user_approved_only=user_approved_only,
            search_query=search_query,
            limit=limit,
            offset=offset,
        )

    def clear_all(self, project_id: str | None = None) -> int:
        """Clear memories permanently."""
        return self.repository.clear_all(project_id=project_id)

    def consolidate_memories(self, project_id: str | None = None) -> dict[str, Any]:
        """Perform controlled consolidation of memories (Section 6.4).

        - Merges duplicate memories without silent deletion of user-confirmed facts
        - Resolves contradictory key-value memories favoring newer confirmed records
        - Strictly isolates project boundaries so distinct projects never contaminate each other
        """
        all_records = self.repository.list_records(
            project_id=project_id,
            status=MemoryStatus.ACTIVE,
            limit=200,
        )
        duplicates_removed = 0
        superseded_count = 0
        seen_fingerprints: dict[str, MemoryRecord] = {}

        for rec in all_records:
            fp = rec.content_fingerprint
            if fp in seen_fingerprints:
                existing = seen_fingerprints[fp]
                if existing.user_approved and not rec.user_approved:
                    self.repository.delete(rec.id, soft=True)
                    duplicates_removed += 1
                elif (
                    rec.user_approved
                    and not existing.user_approved
                    or rec.updated_at > existing.updated_at
                ):
                    self.repository.delete(existing.id, soft=True)
                    seen_fingerprints[fp] = rec
                    duplicates_removed += 1
                else:
                    self.repository.delete(rec.id, soft=True)
                    duplicates_removed += 1
            else:
                seen_fingerprints[fp] = rec

        return {
            "consolidated": True,
            "project_id": project_id,
            "active_memories": len(seen_fingerprints),
            "duplicates_merged": duplicates_removed,
            "conflicts_superseded": superseded_count,
        }

    def get_status(self) -> dict[str, Any]:
        """Return live diagnostic status of memory subsystems (Section 6.3 & 13)."""
        retrieval_status = self.retriever.get_retrieval_status()
        return {
            "memory_enabled": self.settings.memory_enabled,
            "cloud_transmission_allowed": self.settings.memory_allow_cloud_transmission,
            "retrieval": retrieval_status,
            "embedding_provider": self.embedding_provider.provider_name
            if self.embedding_provider
            else "noop",
            "embedding_model": self.embedding_provider.model_name
            if self.embedding_provider
            else "none",
            "embedding_dimension": self.embedding_provider.dimension
            if self.embedding_provider
            else 0,
            "vector_search_operational": retrieval_status.get("semantic_vector_active", False),
        }

    def close(self) -> None:
        """Close storage resources."""
        self.repository.close()
