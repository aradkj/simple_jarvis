"""Natural Language Bilingual File Search Engine for JARVIS."""

from __future__ import annotations

import re
import time

from core.files.database import FileIndexDatabase
from core.files.models import FileSearchResult
from infrastructure.logging import get_logger

logger = get_logger("files.search")


class FileSearchEngine:
    """Combines FTS5 content search, filename matching, and bilingual Persian/English query parsing."""

    # Common Persian words mapping to extensions or English terms
    PERSIAN_EXTENSION_MAP: dict[str, str] = {
        "پی دی اف": ".pdf",
        "پی‌دی‌اف": ".pdf",
        "pdf": ".pdf",
        "ورد": ".docx",
        "word": ".docx",
        "اکسل": ".xlsx",
        "excel": ".xlsx",
        "پاورپوینت": ".pptx",
        "powerpoint": ".pptx",
        "پایتون": ".py",
        "python": ".py",
        "جاوااسکریپت": ".js",
        "متنی": ".txt",
        "تکست": ".txt",
        "تصویر": ".png",
        "عکس": ".jpg",
    }

    # Common Persian intent synonyms
    PERSIAN_SYNONYMS: dict[str, list[str]] = {
        "رزومه": ["resume", "cv", "رزومه"],
        "پروژه": ["project", "پروژه"],
        "فاکتور": ["invoice", "factor", "فاکتور"],
        "قرارداد": ["contract", "agreement", "قرارداد"],
        "صورتجلسه": ["minutes", "meeting", "صورتجلسه"],
        "گزارش": ["report", "گزارش"],
        "ارائه": ["presentation", "slides", "ارائه"],
        "کتاب": ["book", "کتاب"],
        "جزوه": ["pamphlet", "notes", "جزوه"],
    }

    def __init__(self, db: FileIndexDatabase | None = None) -> None:
        self.db = db or FileIndexDatabase()

    def parse_query(self, raw_query: str) -> tuple[str, str | None]:
        """Extract search terms and optional extension filter from a bilingual query.

        Returns:
            Tuple of (cleaned_terms, extension_filter)
        """
        query_lower = raw_query.lower().strip()
        detected_ext: str | None = None

        # Check for extension indicators
        for term, ext in self.PERSIAN_EXTENSION_MAP.items():
            if term in query_lower:
                detected_ext = ext
                # Remove term from query
                query_lower = query_lower.replace(term, " ")
                break

        # Remove common query framing words in Persian and English
        noise_words = [
            "پیدا کن",
            "جستجو کن",
            "بیار",
            "کجاست",
            "رو باز کن",
            "نشان بده",
            "فایل",
            "فایل‌های",
            "پوشه",
            "find",
            "search",
            "locate",
            "where is",
            "file",
            "files",
            "for",
            "my",
            "show",
        ]
        for nw in noise_words:
            query_lower = re.sub(rf"\b{re.escape(nw)}\b", " ", query_lower)

        # Strip Persian grammatical clitics (e.g. رزومه‌ام -> رزومه, پروژه‌ها -> پروژه)
        tokens = query_lower.split()
        cleaned_tokens = []
        for t in tokens:
            for sfx in (
                "\u200cام",
                "\u200cات",
                "\u200cها",
                "\u200cهای",
                "\u200cت",
                "\u200cش",
                "\u200cمان",
                "\u200cتان",
                "\u200cشان",
            ):
                if t.endswith(sfx):
                    t = t[: -len(sfx)]
                    break
            cleaned_tokens.append(t)

        cleaned = " ".join(cleaned_tokens)
        return cleaned or raw_query, detected_ext

    def search(
        self,
        query: str,
        extension_filter: str | None = None,
        limit: int = 20,
    ) -> list[FileSearchResult]:
        """Perform unified bilingual file search."""
        if not query.strip():
            return []

        cleaned_terms, auto_ext = self.parse_query(query)
        effective_ext = extension_filter or auto_ext

        # 1. Expand query with Persian-English bilingual synonyms
        expanded_terms = [cleaned_terms]
        for fa_word, en_words in self.PERSIAN_SYNONYMS.items():
            if fa_word in cleaned_terms:
                expanded_terms.extend(en_words)

        combined_query = " ".join(set(expanded_terms))

        # 2. Query FTS5 for content and filename matches
        fts_results = self.db.search_fts(
            combined_query, extension_filter=effective_ext, limit=limit
        )

        # 3. Query LIKE for direct substring matches on path & name
        like_results = self.db.search_like(
            cleaned_terms, extension_filter=effective_ext, limit=limit
        )

        # 4. Merge, deduplicate, and score
        results_by_path: dict[str, FileSearchResult] = {}

        now = time.time()
        for r in fts_results:
            results_by_path[r.path] = r

        for r in like_results:
            if r.path not in results_by_path:
                results_by_path[r.path] = r
            else:
                # Boost if matched in both
                results_by_path[r.path].relevance_score += 1.0

        # Apply recency boost
        for r in results_by_path.values():
            age_days = (now - r.mtime) / 86400.0
            if age_days < 7:
                r.relevance_score += 1.5
            elif age_days < 30:
                r.relevance_score += 0.8

        sorted_results = sorted(
            results_by_path.values(),
            key=lambda x: x.relevance_score,
            reverse=True,
        )

        return sorted_results[:limit]
