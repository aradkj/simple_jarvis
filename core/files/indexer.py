"""Incremental File Indexer for JARVIS File Intelligence."""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path
from typing import Any

from core.files.content_extractor import FileContentExtractor
from core.files.database import FileIndexDatabase
from core.files.discovery import FileDiscoveryService
from core.files.models import IndexedFile
from infrastructure.logging import get_logger

logger = get_logger("files.indexer")


class FileIndexer:
    """Manages full and incremental indexing of local files into SQLite FTS5."""

    def __init__(
        self,
        db: FileIndexDatabase | None = None,
        discovery: FileDiscoveryService | None = None,
        extractor: FileContentExtractor | None = None,
    ) -> None:
        self.db = db or FileIndexDatabase()
        self.discovery = discovery or FileDiscoveryService()
        self.extractor = extractor or FileContentExtractor()
        self._is_indexing = False
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def is_indexing(self) -> bool:
        return self._is_indexing

    def index_single_file(self, path: Path | str) -> IndexedFile | None:
        """Inspect and index a single file immediately."""
        p = Path(path).resolve()
        if not p.is_file():
            self.db.remove_path(str(p))
            return None

        try:
            stat = p.stat()
            now = time.time()
            excerpt, is_binary = "", False

            # Extract content if not exceeding extraction size limit
            if stat.st_size <= self.discovery.scope.max_content_extract_bytes:
                excerpt, is_binary = self.extractor.extract_excerpt(p)

            indexed_file = IndexedFile(
                path=str(p),
                filename=p.name,
                extension=p.suffix.lower(),
                size_bytes=stat.st_size,
                mtime=stat.st_mtime,
                ctime=stat.st_ctime,
                is_binary=is_binary,
                content_excerpt=excerpt,
                char_count=len(excerpt),
                indexed_at=now,
            )
            self.db.upsert_file(indexed_file)
            return indexed_file
        except Exception as exc:
            logger.warning(f"Failed to index file {p}: {exc}")
            return None

    def run_sync_index(self, max_files: int | None = None) -> int:
        """Run a synchronous indexing pass over discovered files.

        Returns:
            Number of newly indexed or updated files.
        """
        self._is_indexing = True
        indexed_count = 0
        batch: list[IndexedFile] = []
        batch_size = 50
        valid_paths: set[str] = set()

        try:
            for p in self.discovery.scan_files():
                if self._stop_event.is_set():
                    break

                try:
                    p_str = str(p.resolve())
                    valid_paths.add(p_str)
                    stat = p.stat()

                    # Check if file already exists in DB and is unmodified
                    stored_meta = self.db.get_file_metadata(p_str)
                    if stored_meta and abs(stored_meta["mtime"] - stat.st_mtime) < 0.001:
                        # File is unchanged, skip content extraction
                        continue

                    excerpt, is_binary = "", False
                    if stat.st_size <= self.discovery.scope.max_content_extract_bytes:
                        excerpt, is_binary = self.extractor.extract_excerpt(p)

                    indexed = IndexedFile(
                        path=p_str,
                        filename=p.name,
                        extension=p.suffix.lower(),
                        size_bytes=stat.st_size,
                        mtime=stat.st_mtime,
                        ctime=stat.st_ctime,
                        is_binary=is_binary,
                        content_excerpt=excerpt,
                        char_count=len(excerpt),
                        indexed_at=time.time(),
                    )
                    batch.append(indexed)
                    indexed_count += 1

                    if len(batch) >= batch_size:
                        self.db.batch_upsert(batch)
                        batch.clear()

                    if max_files and indexed_count >= max_files:
                        break
                except Exception as exc:
                    logger.debug(f"Error processing {p}: {exc}")
                    continue

            if batch:
                self.db.batch_upsert(batch)
                batch.clear()

            # Clean up files deleted from disk
            if not self._stop_event.is_set() and not max_files:
                self.db.remove_missing_paths(valid_paths)

        finally:
            self._is_indexing = False

        return indexed_count

    def start_background_indexing(self, on_complete: Any = None) -> None:
        """Launch indexing in a daemon thread."""
        if self._is_indexing:
            return

        self._stop_event.clear()

        def _worker() -> None:
            count = self.run_sync_index()
            logger.info(f"Background indexing completed: {count} files updated.")
            if callable(on_complete):
                with contextlib.suppress(Exception):
                    on_complete(count)

        self._thread = threading.Thread(target=_worker, daemon=True, name="JarvisFileIndexer")
        self._thread.start()

    def stop_indexing(self) -> None:
        """Signal background indexing to halt."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
