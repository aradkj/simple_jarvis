"""Safe Content Extraction for JARVIS File Intelligence."""

from __future__ import annotations

from pathlib import Path

from infrastructure.logging import get_logger
from tools.filesystem.document_extractor import DocumentExtractor

logger = get_logger("files.extractor")


class FileContentExtractor:
    """Safely extracts text snippets from documents, code, and configuration files."""

    CODE_EXTENSIONS = {
        ".py",
        ".pyw",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".json",
        ".xml",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
        ".sql",
        ".sh",
        ".bash",
        ".bat",
        ".cmd",
        ".ps1",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".java",
        ".go",
        ".rs",
        ".php",
        ".rb",
        ".lua",
        ".md",
        ".rst",
        ".txt",
        ".log",
        ".csv",
        ".tsv",
    }

    def __init__(self, max_excerpt_chars: int = 4000) -> None:
        self.max_excerpt_chars = max_excerpt_chars
        self._doc_extractor = DocumentExtractor(
            max_chars_default=max_excerpt_chars,
            max_pages_default=20,
        )

    def is_binary_file(self, path: Path) -> bool:
        """Heuristic check for binary content (e.g. presence of null bytes)."""
        try:
            with open(path, "rb") as f:
                chunk = f.read(1024)
                if b"\x00" in chunk:
                    return True
                # Check ratio of non-printable bytes
                text_characters = bytes(range(32, 127)) + b"\n\r\t\b"
                non_text = sum(b not in text_characters for b in chunk)
                if len(chunk) > 0 and (non_text / len(chunk)) > 0.3:
                    return True
        except Exception:
            return True
        return False

    def extract_excerpt(self, path: Path) -> tuple[str, bool]:
        """Extract a bounded text excerpt suitable for search indexing.

        Returns:
            Tuple of (extracted_text, is_binary)
        """
        if not path.is_file():
            return "", False

        suffix = path.suffix.lower()

        # 1. Document formats supported by DocumentExtractor (.pdf, .docx, .xlsx, .pptx, etc.)
        if self._doc_extractor.is_supported(path):
            try:
                doc = self._doc_extractor.extract(path, max_chars=self.max_excerpt_chars)
                text = (doc.text_content or "").strip()
                return text[: self.max_excerpt_chars], False
            except Exception as exc:
                logger.debug(f"DocumentExtractor error on {path.name}: {exc}")

        # 2. Check if binary
        if self.is_binary_file(path):
            return "", True

        # 3. Source code or generic text files
        if suffix in self.CODE_EXTENSIONS or not suffix:
            for encoding in ("utf-8", "utf-8-sig", "latin-1", "cp1256"):
                try:
                    with open(path, encoding=encoding, errors="replace") as f:
                        text = f.read(self.max_excerpt_chars)
                        return text.strip(), False
                except Exception:
                    continue

        return "", False
