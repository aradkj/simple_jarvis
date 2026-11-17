"""Live Internet Intelligence and Search Service for JARVIS.

Provides reliable web search, web page content extraction, source URL tracking,
and timestamped retrieval without synthetic fabrication.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime

from config import Settings, get_settings
from infrastructure.logging import get_logger
from tools.browser.url_security import URLSecurityValidator

logger = get_logger("internet_service")


@dataclass
class SearchResultItem:
    """Individual web search result."""

    title: str
    url: str
    snippet: str
    source_domain: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


@dataclass
class WebPageContent:
    """Extracted text content from a web page."""

    url: str
    title: str
    text_content: str
    word_count: int
    retrieval_timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    content_truncated: bool = False


class InternetSearchService:
    """Service providing live web search and secure web page retrieval."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

    def search(self, query: str, max_results: int = 5) -> list[SearchResultItem]:
        """Perform a live web search returning titles, snippets, source URLs, and timestamps."""
        if not query or not query.strip():
            raise ValueError("Search query cannot be empty.")

        cleaned_query = query.strip()
        logger.info(f"Executing live internet search for: '{cleaned_query}'")
        results: list[SearchResultItem] = []

        # 1. Search via DuckDuckGo HTML search endpoint
        try:
            encoded_q = urllib.parse.quote(cleaned_query)
            url = f"https://html.duckduckgo.com/html/?q={encoded_q}"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self._user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,fa;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                raw_html = resp.read().decode("utf-8", errors="replace")

            # Extract result blocks
            title_pattern = re.compile(
                r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                re.DOTALL | re.IGNORECASE,
            )
            snippet_pattern = re.compile(
                r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                re.DOTALL | re.IGNORECASE,
            )

            titles_matches = title_pattern.findall(raw_html)
            snippet_matches = snippet_pattern.findall(raw_html)

            for i, (href, raw_title) in enumerate(titles_matches[:max_results]):
                clean_title = html.unescape(re.sub(r"<[^>]+>", "", raw_title).strip())
                raw_snippet = snippet_matches[i] if i < len(snippet_matches) else ""
                clean_snippet = html.unescape(re.sub(r"<[^>]+>", "", raw_snippet).strip())

                # Unquote DuckDuckGo uddg parameter if present
                actual_url = href
                if "uddg=" in href:
                    m = re.search(r"uddg=([^&]+)", href)
                    if m:
                        actual_url = urllib.parse.unquote(m.group(1))

                domain = urllib.parse.urlparse(actual_url).netloc
                results.append(
                    SearchResultItem(
                        title=clean_title,
                        url=actual_url,
                        snippet=clean_snippet,
                        source_domain=domain,
                    )
                )

        except Exception as exc:
            logger.warning(
                f"DuckDuckGo HTML search query failed: {exc}. Trying fallback search API."
            )

        # 2. Fallback: DuckDuckGo Instant Answer API if HTML returned 0 results
        if not results:
            try:
                api_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(cleaned_query)}&format=json&no_html=1"
                req = urllib.request.Request(api_url, headers={"User-Agent": self._user_agent})
                with urllib.request.urlopen(req, timeout=8.0) as resp:
                    api_data = json.loads(resp.read().decode("utf-8"))

                # Abstract
                abstract = api_data.get("AbstractText", "")
                abstract_url = api_data.get("AbstractURL", "")
                heading = api_data.get("Heading", cleaned_query)
                if abstract and abstract_url:
                    results.append(
                        SearchResultItem(
                            title=heading,
                            url=abstract_url,
                            snippet=abstract,
                            source_domain=urllib.parse.urlparse(abstract_url).netloc,
                        )
                    )

                # Related topics
                for topic in api_data.get("RelatedTopics", []):
                    if len(results) >= max_results:
                        break
                    t_text = topic.get("Text", "")
                    t_url = topic.get("FirstURL", "")
                    if t_text and t_url:
                        results.append(
                            SearchResultItem(
                                title=t_text.split(" - ")[0] if " - " in t_text else t_text[:60],
                                url=t_url,
                                snippet=t_text,
                                source_domain=urllib.parse.urlparse(t_url).netloc,
                            )
                        )
            except Exception as api_exc:
                logger.error(f"Fallback instant search API error: {api_exc}")

        if not results:
            logger.warning(f"No internet search results retrieved for query: '{cleaned_query}'")

        return results

    def read_page_content(self, url: str, max_chars: int = 5000) -> WebPageContent:
        """Securely fetch and extract readable text content from a web page URL."""
        # 1. URL Security Validation (SSRF, local IP protection)
        val_res = URLSecurityValidator.validate_url(url)
        if not val_res.is_valid:
            raise ValueError(f"URL security policy rejected '{url}': {val_res.error_message}")
        validated_url = val_res.normalized_url or url

        logger.info(f"Fetching web page content from: {validated_url}")
        req = urllib.request.Request(
            validated_url,
            headers={
                "User-Agent": self._user_agent,
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=12.0) as resp:
                _content_type = resp.headers.get("Content-Type", "")
                raw_bytes = resp.read(2_000_000)  # max 2MB raw download guard

            raw_text = raw_bytes.decode("utf-8", errors="replace")

            # Extract Title
            title_match = re.search(
                r"<title[^>]*>(.*?)</title>", raw_text, re.IGNORECASE | re.DOTALL
            )
            page_title = (
                html.unescape(title_match.group(1).strip()) if title_match else validated_url
            )

            # Remove scripts, styles, svg, header, footer, nav
            cleaned_html = re.sub(
                r"<(script|style|svg|noscript|header|footer|nav)[^>]*>.*?</\1>",
                " ",
                raw_text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            # Remove remaining HTML tags
            clean_text = re.sub(r"<[^>]+>", " ", cleaned_html)
            clean_text = html.unescape(clean_text)
            # Normalize whitespace
            clean_text = re.sub(r"\s+", " ", clean_text).strip()

            truncated = False
            if len(clean_text) > max_chars:
                clean_text = clean_text[:max_chars] + "... [Content truncated]"
                truncated = True

            word_count = len(clean_text.split())
            return WebPageContent(
                url=validated_url,
                title=page_title,
                text_content=clean_text,
                word_count=word_count,
                content_truncated=truncated,
            )
        except Exception as exc:
            logger.error(f"Error fetching web page {validated_url}: {exc}")
            raise RuntimeError(f"Failed to read web page at '{validated_url}': {exc}") from exc
