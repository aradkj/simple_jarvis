"""Memory lifecycle transitions, conflict resolution, and retention management."""

from __future__ import annotations

from datetime import UTC, datetime

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
    ) -> None:
        self.repository = repository
        self.privacy_manager = privacy_manager or MemoryPrivacyManager()

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
        self.repository.save(rec)
        return rec

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
