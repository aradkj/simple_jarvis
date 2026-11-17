"""File Discovery Service for scanning files across user and project directories."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from core.files.models import IndexingScope
from infrastructure.logging import get_logger

logger = get_logger("files.discovery")


class FileDiscoveryService:
    """Discovers files across user libraries and project folders while enforcing exclusion boundaries."""

    def __init__(self, scope: IndexingScope | None = None) -> None:
        self.scope = scope or self._get_default_scope()

    @staticmethod
    def _get_default_scope() -> IndexingScope:
        """Construct standard default scanning scope covering user workspace and libraries."""
        roots: list[str] = []

        # Current workspace root (e.g. C:\AI\jarvis or C:\AI)
        current_ai = Path(r"C:\AI")
        if current_ai.exists():
            roots.append(str(current_ai))

        user_home = Path.home()
        for folder_name in ("Desktop", "Documents", "Downloads", "Projects"):
            folder_path = user_home / folder_name
            if folder_path.exists():
                roots.append(str(folder_path))

        return IndexingScope(root_paths=roots)

    def scan_files(self) -> Iterator[Path]:
        """Yield valid Path objects within scope, respecting exclusion rules."""
        for root_str in self.scope.root_paths:
            root_path = Path(root_str)
            if not root_path.exists():
                continue

            yield from self._walk_directory(root_path)

    def _walk_directory(self, current_dir: Path) -> Iterator[Path]:
        """Recursively walk directory using scandir with fast exclusions."""
        try:
            with os.scandir(current_dir) as entries:
                for entry in entries:
                    name = entry.name
                    # Fast directory check & exclusion
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if name in self.scope.excluded_dir_names or name.startswith("."):
                                continue
                            yield from self._walk_directory(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            # Check extension
                            suffix = Path(name).suffix.lower()
                            if suffix in self.scope.excluded_extensions:
                                continue

                            # Check size
                            try:
                                stat = entry.stat(follow_symlinks=False)
                                if stat.st_size > self.scope.max_file_size_bytes:
                                    continue
                            except OSError:
                                continue

                            yield Path(entry.path)
                    except OSError:
                        continue
        except (PermissionError, OSError) as exc:
            logger.debug(f"Permission denied or access error on {current_dir}: {exc}")
