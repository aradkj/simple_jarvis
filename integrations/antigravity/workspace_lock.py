"""Workspace locking manager for Antigravity integration."""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from infrastructure.logging import get_logger

logger = get_logger("antigravity_workspace_lock")


class WorkspaceLockError(Exception):
    """Raised when a workspace lock cannot be acquired."""


class WorkspaceLockManager:
    """Manages thread-safe and task-safe locking on workspace directories."""

    _instance: WorkspaceLockManager | None = None
    _global_lock = threading.RLock()

    def __init__(self) -> None:
        self._locks: dict[str, threading.RLock] = {}
        self._active_tasks: dict[str, str] = {}  # canonical_path -> task_id

    @classmethod
    def get_instance(cls) -> WorkspaceLockManager:
        with cls._global_lock:
            if cls._instance is None:
                cls._instance = WorkspaceLockManager()
            return cls._instance

    def _normalize_path(self, path: str | Path) -> str:
        return str(Path(path).resolve()).lower()

    def is_locked(self, path: str | Path) -> bool:
        norm = self._normalize_path(path)
        with self._global_lock:
            return norm in self._active_tasks

    def get_locking_task(self, path: str | Path) -> str | None:
        norm = self._normalize_path(path)
        with self._global_lock:
            return self._active_tasks.get(norm)

    def acquire(self, path: str | Path, task_id: str, timeout: float = 5.0) -> bool:
        """Acquire lock on a workspace for a specific task."""
        norm = self._normalize_path(path)
        with self._global_lock:
            existing = self._active_tasks.get(norm)
            if existing and existing != task_id:
                logger.warning(f"Workspace '{path}' is already locked by task '{existing}'")
                return False
            if norm not in self._locks:
                self._locks[norm] = threading.Lock()
            lock = self._locks[norm]

        acquired = lock.acquire(timeout=timeout)
        if not acquired:
            current_task = self._active_tasks.get(norm, "unknown")
            logger.warning(
                f"Failed to acquire workspace lock for '{path}'. Currently held by task '{current_task}'"
            )
            return False

        with self._global_lock:
            self._active_tasks[norm] = task_id
            logger.info(f"Acquired workspace lock for '{path}' by task '{task_id}'")
        return True

    def release(self, path: str | Path, task_id: str) -> None:
        """Release lock on a workspace."""
        norm = self._normalize_path(path)
        with self._global_lock:
            current = self._active_tasks.get(norm)
            if current and current != task_id:
                logger.warning(
                    f"Task '{task_id}' attempting to release lock held by '{current}' on '{path}'"
                )
                return

            if norm in self._active_tasks:
                del self._active_tasks[norm]

            lock = self._locks.get(norm)

        if lock:
            try:
                lock.release()
                logger.info(f"Released workspace lock for '{path}' from task '{task_id}'")
            except RuntimeError:
                # Lock wasn't acquired by this thread or already released
                pass

    @contextmanager
    def lock_workspace(
        self, path: str | Path, task_id: str, timeout: float = 5.0
    ) -> Generator[bool, None, None]:
        success = self.acquire(path, task_id, timeout=timeout)
        if not success:
            raise WorkspaceLockError(f"Workspace '{path}' is locked by another operation.")
        try:
            yield True
        finally:
            self.release(path, task_id)
