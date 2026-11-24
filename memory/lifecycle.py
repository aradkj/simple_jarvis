"""Memory lifecycle transitions, conflict resolution, and retention management."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from infrastructure.logging import get_logger
from memory.models import MemoryRecord, MemoryStatus
from memory.privacy import MemoryPrivacyManager
from memory.repository import MemoryRepository

logger = get_logger("memory.lifecycle")


class MemoryLifecycleManager:
    """Manages memory lifecycle states, conflict superseding, and retention policies."""

    def __init__(
        self,
        repository: MemoryRepository,
        privacy_manager: MemoryPrivacyManager | None = None,
        embedding_provider: Any | None = None,
    ) -> None:
        self.repository = repository
        self.privacy_manager = privacy_manager or MemoryPrivacyManager()
        self.embedding_provider = embedding_provider

    def approve_candidate(self, candidate_id: str) -> MemoryRecord | None:
        """Promote a pending memory candidate to active status with conflict resolution."""
        rec = self.repository.get(candidate_id)
        if not rec:
            logger.warning(f"Candidate memory not found: {candidate_id}")
            return None

        # Conflict resolution: if this record has a designated key, supersede previous active ones
        if rec.key.strip():
            existing = self.repository.find_conflicts(
                category=rec.category, key=rec.key, project_id=rec.project_id
            )
            for old in existing:
                if old.id != rec.id:
                    logger.info(
                        f"Superseding older conflicting memory {old.id} with new {rec.id} (key='{rec.key}')"
                    )
                    self.repository.mark_superseded(old.id, rec.id)

        now = datetime.now(UTC)
        rec.status = MemoryStatus.ACTIVE
        rec.user_approved = True
        rec.updated_at = now
        rec.last_accessed_at = now
        if self.embedding_provider and getattr(self.embedding_provider, "is_available", False):
            try:
                rec.vector = self.embedding_provider.embed_text(rec.content)
                rec.metadata["embedding_provider"] = self.embedding_provider.provider_name
                rec.metadata["embedding_model"] = self.embedding_provider.model_name
            except Exception as exc:
                logger.debug(f"Candidate embedding vector calculation note: {exc}")
        self.repository.save(rec)
        return rec

    def consolidate_memories(self, project_id: str | None = None) -> dict[str, Any]:
        """Consolidate project memories: merge duplicates and resolve conflicts."""
        all_records = self.repository.list_records(
            project_id=project_id,
            status=MemoryStatus.ACTIVE,
            limit=200,
        )
        duplicates_removed = 0
        seen_fingerprints: dict[str, MemoryRecord] = {}

        for rec in all_records:
            fp = rec.content_fingerprint
            if fp in seen_fingerprints:
                existing = seen_fingerprints[fp]
                if existing.user_approved and not rec.user_approved:
                    self.repository.delete(rec.id, soft=True)
                    duplicates_removed += 1
                elif rec.user_approved and not existing.user_approved:
                    self.repository.delete(existing.id, soft=True)
                    seen_fingerprints[fp] = rec
                    duplicates_removed += 1
                else:
                    self.repository.delete(rec.id, soft=True)
                    duplicates_removed += 1
            else:
                seen_fingerprints[fp] = rec

        return {
            "project_id": project_id,
            "total_processed": len(all_records),
            "duplicates_merged": duplicates_removed,
            "remaining_active": len(seen_fingerprints),
        }

    def reject_candidate(self, candidate_id: str) -> bool:
        """Reject and delete a pending memory candidate."""
        return self.repository.delete(candidate_id, soft=False)

    def edit_memory(
        self,
        memory_id: str,
        new_content: str,
        importance: float | None = None,
    ) -> MemoryRecord | None:
        """Edit the textual content and properties of an existing memory record."""
        rec = self.repository.get(memory_id)
        if not rec:
            return None

        # Validate new content for prohibited credentials/secrets
        self.privacy_manager.validate_candidate_content(new_content)

        rec.content = new_content.strip()
        rec.normalized_content = new_content.strip().lower()
        rec.content_fingerprint = rec.compute_fingerprint()
        if importance is not None:
            rec.importance = max(0.0, min(1.0, importance))
        rec.updated_at = datetime.now(UTC)

        self.repository.save(rec)
        return rec

    def archive_memory(self, memory_id: str) -> bool:
        """Transition an active memory to archived status."""
        rec = self.repository.get(memory_id)
        if not rec:
            return False
        rec.status = MemoryStatus.ARCHIVED
        rec.updated_at = datetime.now(UTC)
        self.repository.save(rec)
        return True

    def restore_memory(self, memory_id: str) -> bool:
        """Restore an archived or superseded memory to active status."""
        rec = self.repository.get(memory_id)
        if not rec:
            return False
        rec.status = MemoryStatus.ACTIVE
        rec.updated_at = datetime.now(UTC)
        self.repository.save(rec)
        return True

    def delete_memory(self, memory_id: str, soft: bool = True) -> bool:
        """Delete a memory record."""
        return self.repository.delete(memory_id, soft=soft)
