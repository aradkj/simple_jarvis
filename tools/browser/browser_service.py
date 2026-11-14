"""Browser automation service for JARVIS Phase 7 using Playwright.

Provides controlled, isolated browser lifecycle management, navigation,
DOM inspection, tab management, safe element interaction, and screenshot capture.
Execution is designed to be called from background workers or execution threads.
"""

from __future__ import annotations

import contextlib
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from config import Settings, get_settings
from infrastructure.logging import get_logger
from infrastructure.paths import get_data_dir
from tools.browser.exceptions import (
    BrowserCrashError,
    BrowserError,
    BrowserInteractionError,
    BrowserNavigationError,
    BrowserNotInitializedError,
    BrowserSecurityError,
    BrowserTabLimitError,
    BrowserTimeoutError,
    URLValidationError,
)
from tools.browser.models import (
    ClickResult,
    FillResult,
    HeadingItem,
    HeadingsResult,
    LinkItem,
    LinksResult,
    NavigationResult,
    PageContentResult,
    ScreenshotResult,
    SearchResult,
    SearchResultItem,
    TabInfo,
    TabListResult,
)
from tools.browser.url_security import URLSecurityValidator

if TYPE_CHECKING:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright

logger = get_logger("browser.service")


class BrowserService:
    """Manages an isolated Playwright browser instance, context, tabs, and page actions."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._lock = threading.RLock()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._pages: list[Page] = []
        self._active_page_index: int = 0
        self._navigation_step_count: int = 0

    @property
    def is_running(self) -> bool:
        """Check whether the browser process and context are currently active."""
        with self._lock:
            return bool(
                self._browser is not None
                and self._browser.is_connected()
                and self._context is not None
            )

    def initialize(self) -> None:
        """Lazily start Playwright, launch Chromium, and create an isolated context."""
        with self._lock:
            if self.is_running:
                return

            try:
                from playwright.sync_api import sync_playwright

                self._playwright = sync_playwright().start()
                headless = getattr(self._settings, "browser_headless", True)

                # Launch Chromium with security sandboxing
                launch_args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-popup-blocking",
                ]

                self._browser = self._playwright.chromium.launch(
                    headless=headless,
                    args=launch_args,
                )

                # Create strictly isolated context (no cookies, passwords, or host profile sharing)
                user_agent = (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36 JARVIS-Agent/0.2.1"
                )

                self._context = self._browser.new_context(
                    user_agent=user_agent,
                    viewport={"width": 1280, "height": 800},
                    accept_downloads=getattr(self._settings, "browser_downloads_enabled", False),
                    java_script_enabled=True,
                    ignore_https_errors=False,  # Enforce TLS certificate validation
                )

                # Route-level redirect, subresource, and navigation security validation
                allow_loc = getattr(self._settings, "browser_allow_localhost", False)

                def handle_route(route: Any) -> None:
                    req = route.request
                    req_url = req.url

                    # Allow data URLs strictly for inline images, fonts, and stylesheets
                    if (
                        req_url.startswith("data:image/")
                        or req_url.startswith("data:font/")
                        or req_url.startswith("data:text/css")
                    ):
                        route.continue_()
                        return

                    res = URLSecurityValidator.validate_url(req_url, allow_localhost=allow_loc)
                    if not res.is_valid:
                        logger.warning(
                            f"Connection-level security blocked request: {req_url} ({res.rejection_reason})"
                        )
                        route.abort("blockedbyclient")
                        return

                    route.continue_()

                self._context.route("**/*", handle_route)

                # Popup and new tab tracking with limit enforcement
                max_tabs = getattr(self._settings, "browser_max_tabs", 5)

                def handle_new_page(new_p: Page) -> None:
                    with self._lock:
                        valid_pages = [p for p in self._pages if not p.is_closed()]
                        if len(valid_pages) >= max_tabs:
                            logger.warning(
                                f"Popup/new tab blocked: maximum tab limit ({max_tabs}) reached."
                            )
                            with contextlib.suppress(Exception):
                                new_p.close()
                            return
                        self._pages.append(new_p)

                self._context.on("page", handle_new_page)

                # Download interception and blocking if not enabled
                def handle_download(download: Any) -> None:
                    downloads_enabled = getattr(self._settings, "browser_downloads_enabled", False)
                    if not downloads_enabled:
                        logger.warning(
                            f"Unauthorized download blocked: {download.suggested_filename}"
                        )
                        with contextlib.suppress(Exception):
                            download.cancel()

                self._context.on("download", handle_download)

                # Open the initial page
                initial_page = self._context.new_page()
                self._pages = [initial_page]
                self._active_page_index = 0
                logger.info("BrowserService initialized successfully with isolated context.")

            except Exception as exc:
                self._cleanup_resources()
                logger.error(f"Failed to initialize BrowserService: {exc}")
                raise BrowserError(f"Browser initialization failed: {exc}") from exc

    def _cleanup_resources(self) -> None:
        """Internal cleanup of all Playwright resources."""
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        finally:
            self._context = None
            self._pages = []
            self._active_page_index = 0

        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        finally:
            self._browser = None

        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        finally:
            self._playwright = None

    def close(self) -> None:
        """Gracefully close all pages, context, browser process, and Playwright driver."""
        with self._lock:
            self._cleanup_resources()
            logger.info("BrowserService closed gracefully.")

    def _get_active_page(self) -> Page:
        """Get the current active tab page. Ensures initialization."""
        self.initialize()
        # Clean up any closed pages
        self._pages = [p for p in self._pages if not p.is_closed()]
        if not self._pages:
            if self._context:
                new_p = self._context.new_page()
                self._pages.append(new_p)
                self._active_page_index = 0
            else:
                raise BrowserNotInitializedError("Browser context is not available.")

        if self._active_page_index >= len(self._pages):
            self._active_page_index = len(self._pages) - 1

        return self._pages[self._active_page_index]

    # --- Navigation Capabilities ---

    def navigate(
        self,
        url: str,
        wait_until: str = "domcontentloaded",
    ) -> NavigationResult:
        """Navigate the active tab to the specified URL after validating URL security.

        Args:
            url: The destination URL.
            wait_until: 'load', 'domcontentloaded', or 'networkidle'.

        Returns:
            NavigationResult with title, status, and timing.
        """
        with self._lock:
            # 1. Check cumulative navigation step boundary
            max_steps = getattr(self._settings, "browser_max_navigation_steps", 20)
            if self._navigation_step_count >= max_steps:
                raise BrowserSecurityError(
                    f"Navigation step limit ({max_steps}) exceeded for this session to prevent infinite loops."
                )

            # 2. Security validation
            allow_localhost = getattr(self._settings, "browser_allow_localhost", False)
            validation = URLSecurityValidator.validate_url(url, allow_localhost=allow_localhost)
            if not validation.is_valid:
                logger.warning(f"URL rejected by security: {url} -> {validation.rejection_reason}")
                raise URLValidationError(
                    f"Navigation to '{url}' blocked: {validation.rejection_reason}"
                )

            target_url = validation.normalized_url or url
            page = self._get_active_page()
            timeout_ms = getattr(self._settings, "browser_navigation_timeout", 30) * 1000

            start_time = time.perf_counter()
            try:
                resp = page.goto(target_url, timeout=timeout_ms, wait_until=wait_until)
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                self._navigation_step_count += 1

                # Re-validate destination URL in case of HTTP redirects
                final_url = page.url
                final_val = URLSecurityValidator.validate_url(
                    final_url, allow_localhost=allow_localhost
                )
                if not final_val.is_valid:
                    # Immediately navigate away if redirected to a forbidden internal target
                    page.goto("about:blank")
                    raise BrowserSecurityError(
                        f"Redirected to forbidden address '{final_url}': {final_val.rejection_reason}"
                    )

                status_code = resp.status if resp else 200
                title = page.title()

                return NavigationResult(
                    url=final_url,
                    title=title,
                    status_code=status_code,
                    timing_ms=round(elapsed_ms, 2),
                    load_state="completed",
                )

            except URLValidationError:
                raise
            except BrowserSecurityError:
                raise
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                msg = str(exc)
                if "Timeout" in msg or "timeout" in msg:
                    raise BrowserTimeoutError(
                        f"Navigation to '{target_url}' timed out after {timeout_ms / 1000}s"
                    ) from exc
                if "Target closed" in msg or "Browser closed" in msg:
                    self._cleanup_resources()
                    raise BrowserCrashError(f"Browser crashed during navigation: {msg}") from exc
                raise BrowserNavigationError(f"Navigation failed: {msg}") from exc

    def go_back(self, steps: int = 1) -> NavigationResult:
        """Navigate back in history."""
        with self._lock:
            page = self._get_active_page()
            timeout_ms = getattr(self._settings, "browser_navigation_timeout", 30) * 1000
            allow_localhost = getattr(self._settings, "browser_allow_localhost", False)
            for _ in range(steps):
                page.go_back(timeout=timeout_ms)

            # Re-validate destination URL
            final_url = page.url
            val = URLSecurityValidator.validate_url(final_url, allow_localhost=allow_localhost)
            if not val.is_valid:
                page.goto("about:blank")
                raise BrowserSecurityError(
                    f"History back navigated to forbidden address '{final_url}': {val.rejection_reason}"
                )

            return NavigationResult(
                url=final_url,
                title=page.title(),
                status_code=200,
                load_state="completed",
            )

    def go_forward(self, steps: int = 1) -> NavigationResult:
        """Navigate forward in history."""
        with self._lock:
            page = self._get_active_page()
            timeout_ms = getattr(self._settings, "browser_navigation_timeout", 30) * 1000
            allow_localhost = getattr(self._settings, "browser_allow_localhost", False)
            for _ in range(steps):
                page.go_forward(timeout=timeout_ms)

            # Re-validate destination URL
            final_url = page.url
            val = URLSecurityValidator.validate_url(final_url, allow_localhost=allow_localhost)
            if not val.is_valid:
                page.goto("about:blank")
                raise BrowserSecurityError(
                    f"History forward navigated to forbidden address '{final_url}': {val.rejection_reason}"
                )

            return NavigationResult(
                url=final_url,
                title=page.title(),
                status_code=200,
                load_state="completed",
            )

    def reload(self, ignore_cache: bool = False) -> NavigationResult:
        """Reload the current page."""
        with self._lock:
            page = self._get_active_page()
            timeout_ms = getattr(self._settings, "browser_navigation_timeout", 30) * 1000
            allow_localhost = getattr(self._settings, "browser_allow_localhost", False)
            resp = page.reload(timeout=timeout_ms)

            # Re-validate destination URL
            final_url = page.url
            val = URLSecurityValidator.validate_url(final_url, allow_localhost=allow_localhost)
            if not val.is_valid:
                page.goto("about:blank")
                raise BrowserSecurityError(
                    f"Page reload landed on forbidden address '{final_url}': {val.rejection_reason}"
                )

            return NavigationResult(
                url=final_url,
                title=page.title(),
                status_code=resp.status if resp else 200,
                load_state="completed",
            )

    def get_current_url(self) -> str:
        """Get the URL of the active tab."""
        with self._lock:
            return self._get_active_page().url

    def get_current_title(self) -> str:
        """Get the title of the active tab."""
        with self._lock:
            return self._get_active_page().title()

    # --- Search Capabilities ---

    def search_web(self, query: str, num_results: int = 5) -> SearchResult:
        """Perform a web search using a safe public search interface and extract results."""
        with self._lock:
            import urllib.parse

            encoded_query = urllib.parse.quote_plus(query.strip())
            search_url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

            # Navigate to DuckDuckGo HTML interface
            self.navigate(search_url, wait_until="domcontentloaded")
            page = self._get_active_page()

            # Wait briefly for result snippets
            results: list[SearchResultItem] = []
            try:
                # DuckDuckGo HTML result elements
                rows = page.query_selector_all(".result")
                for row in rows[:num_results]:
                    title_elem = row.query_selector(".result__title .result__a")
                    snippet_elem = row.query_selector(".result__snippet")

                    if title_elem:
                        title_text = title_elem.inner_text().strip()
                        raw_href = title_elem.get_attribute("href") or ""

                        # Extract actual destination from DuckDuckGo redirect URL
                        actual_url = raw_href
                        if "uddg=" in raw_href:
                            parsed_href = urllib.parse.urlparse(raw_href)
                            query_params = urllib.parse.parse_qs(parsed_href.query)
                            if "uddg" in query_params:
                                actual_url = query_params["uddg"][0]

                        snippet_text = snippet_elem.inner_text().strip() if snippet_elem else ""

                        if title_text and actual_url:
                            results.append(
                                SearchResultItem(
                                    title=title_text,
                                    url=actual_url,
                                    snippet=snippet_text,
                                )
                            )
            except Exception as exc:
                logger.warning(f"Error parsing search results: {exc}")

            return SearchResult(
                query=query,
                results=results,
                total_found=len(results),
                search_provider="duckduckgo",
            )

    # --- Page Inspection Capabilities ---

    def get_page_content(
        self,
        max_chars: int = 16000,
        include_links: bool = False,
    ) -> PageContentResult:
        """Extract visible, cleaned text and structure from the active tab.

        Removes script, style, and hidden DOM content to prevent injection leakage.
        """
        with self._lock:
            page = self._get_active_page()
            url = page.url
            title = page.title()

            # JS script to extract visible text cleanly while stripping scripts, styles, etc.
            extraction_script = """
            () => {
                const clone = document.body.cloneNode(true);
                // Remove non-visible elements
                const removeTags = ['script', 'style', 'noscript', 'svg', 'canvas', 'iframe', 'template'];
                removeTags.forEach(tag => {
                    const elements = clone.getElementsByTagName(tag);
                    while (elements.length > 0) elements[0].remove();
                });

                // Extract headings summary
                const headings = [];
                clone.querySelectorAll('h1, h2, h3').forEach(h => {
                    const text = h.innerText.trim();
                    if (text) headings.push(`${h.tagName.toUpperCase()}: ${text}`);
                });

                return {
                    text: clone.innerText || clone.textContent || '',
                    headings: headings.slice(0, 10)
                };
            }
            """

            try:
                data = page.evaluate(extraction_script)
                raw_text = (data.get("text") or "").strip()
                headings = data.get("headings", [])
            except Exception as exc:
                logger.warning(f"DOM evaluation failed, falling back to inner_text: {exc}")
                raw_text = page.inner_text("body").strip()
                headings = []

            # Truncate to configured maximum characters
            budget = min(max_chars, getattr(self._settings, "browser_max_extracted_chars", 16000))
            is_truncated = len(raw_text) > budget
            extracted_text = raw_text[:budget]

            return PageContentResult(
                url=url,
                title=title,
                text=extracted_text,
                char_count=len(extracted_text),
                truncated=is_truncated,
                headings_summary=headings,
            )

    def get_headings(self, max_depth: int = 3) -> HeadingsResult:
        """Extract heading hierarchy (h1 through h[max_depth])."""
        with self._lock:
            page = self._get_active_page()
            tags = [f"h{i}" for i in range(1, max_depth + 1)]
            selector = ", ".join(tags)

            script = f"""
            () => {{
                const nodes = document.querySelectorAll('{selector}');
                return Array.from(nodes).map(n => ({{
                    level: parseInt(n.tagName.substring(1)),
                    text: n.innerText.trim()
                }})).filter(item => item.text.length > 0);
            }}
            """
            raw_headings = page.evaluate(script)
            headings = [HeadingItem(level=h["level"], text=h["text"]) for h in raw_headings]

            return HeadingsResult(
                url=page.url,
                title=page.title(),
                headings=headings,
                total_headings=len(headings),
            )

    def get_links(self, max_links: int = 50, filter_internal: bool = False) -> LinksResult:
        """Extract visible hyperlinks from the page."""
        with self._lock:
            page = self._get_active_page()
            current_origin = page.evaluate("window.location.origin")

            script = f"""
            () => {{
                const links = document.querySelectorAll('a[href]');
                const currentOrigin = '{current_origin}';
                const results = [];
                for (const a of links) {{
                    const href = a.href;
                    const text = a.innerText.trim() || a.getAttribute('aria-label') || a.getAttribute('title') || '';
                    if (!href || href.startsWith('javascript:') || href.startsWith('mailto:') || href.startsWith('tel:')) {{
                        continue;
                    }}
                    const isExternal = !href.startsWith(currentOrigin);
                    results.push({{
                        text: text,
                        href: href,
                        is_external: isExternal
                    }});
                }}
                return results;
            }}
            """
            raw_links = page.evaluate(script)

            items: list[LinkItem] = []
            for item in raw_links:
                if filter_internal and item["is_external"]:
                    continue
                items.append(
                    LinkItem(
                        text=item["text"],
                        href=item["href"],
                        is_external=item["is_external"],
                    )
                )
                if len(items) >= max_links:
                    break

            return LinksResult(
                url=page.url,
                links=items,
                total_links=len(items),
            )

    # --- Safe Interaction Capabilities ---

    def click_element(
        self,
        selector: str,
        timeout_ms: int = 5000,
        confirmed: bool = False,
    ) -> ClickResult:
        """Click an identified page element using a stable locator."""
        with self._lock:
            page = self._get_active_page()
            old_url = page.url

            try:
                # Wait for element to be visible and attached
                locator = page.locator(selector).first
                locator.wait_for(state="visible", timeout=timeout_ms)

                # Inspect element attributes and visible text for sensitive purchase or payment actions
                elem_info = locator.evaluate(
                    """el => ({
                        tag: el.tagName.toLowerCase(),
                        type: (el.getAttribute('type') || '').toLowerCase(),
                        text: (el.innerText || el.value || el.getAttribute('aria-label') || '').toLowerCase()
                    })"""
                )
                elem_text = elem_info.get("text", "")
                is_purchase_action = any(
                    k in elem_text
                    for k in (
                        "buy now",
                        "purchase",
                        "checkout",
                        "pay now",
                        "place order",
                        "خرید",
                        "پرداخت",
                    )
                )
                if is_purchase_action and not confirmed:
                    raise BrowserSecurityError(
                        f"Sensitive purchase/payment action detected on element '{selector}' ('{elem_text.strip()}'). "
                        "Automatic purchases and payments are strictly prohibited without explicit user approval."
                    )

                locator.click(timeout=timeout_ms)

                # Check if navigation occurred as a result
                page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                new_url = page.url

                # Validate destination URL if click caused navigation
                allow_localhost = getattr(self._settings, "browser_allow_localhost", False)
                val = URLSecurityValidator.validate_url(new_url, allow_localhost=allow_localhost)
                if not val.is_valid:
                    page.goto("about:blank")
                    raise BrowserSecurityError(
                        f"Click navigated to forbidden address '{new_url}': {val.rejection_reason}"
                    )

                return ClickResult(
                    selector=selector,
                    success=True,
                    navigation_occurred=(new_url != old_url),
                    current_url=new_url,
                    current_title=page.title(),
                )
            except (BrowserSecurityError, BrowserInteractionError):
                raise
            except Exception as exc:
                raise BrowserInteractionError(f"Click on '{selector}' failed: {exc}") from exc

    def scroll(self, direction: str = "down", amount: int = 500) -> Any:
        """Scroll page viewport in specified direction."""
        with self._lock:
            page = self._get_active_page()

            if direction == "down":
                script = f"window.scrollBy(0, {amount});"
            elif direction == "up":
                script = f"window.scrollBy(0, -{amount});"
            elif direction == "top":
                script = "window.scrollTo(0, 0);"
            elif direction == "bottom":
                script = "window.scrollTo(0, document.body.scrollHeight);"
            else:
                script = f"window.scrollBy(0, {amount});"

            page.evaluate(script)
            # Give brief rendering time
            time.sleep(0.1)

            positions = page.evaluate(
                "() => ({ x: window.scrollX, y: window.scrollY, maxY: document.body.scrollHeight })"
            )
            from tools.browser.models import ScrollResult

            return ScrollResult(
                direction=direction,
                amount=amount,
                scroll_x=positions.get("x", 0),
                scroll_y=positions.get("y", 0),
                max_scroll_y=positions.get("maxY", 0),
            )

    def fill_field(
        self,
        selector: str,
        value: str,
        press_enter: bool = False,
        confirmed: bool = False,
    ) -> FillResult:
        """Fill a non-sensitive input or textarea element."""
        with self._lock:
            page = self._get_active_page()

            try:
                locator = page.locator(selector).first
                locator.wait_for(state="visible", timeout=5000)

                # Inspect element type and attributes to protect sensitive credential fields
                elem_type = locator.evaluate("el => (el.getAttribute('type') || '').toLowerCase()")
                if elem_type == "password" and not confirmed:
                    raise BrowserSecurityError(
                        f"Filling password field '{selector}' requires explicit user confirmation."
                    )

                locator.fill(value)

                if press_enter:
                    locator.press("Enter")
                    time.sleep(0.2)

                return FillResult(
                    selector=selector,
                    success=True,
                    entered_length=len(value),
                    press_enter=press_enter,
                )
            except (BrowserSecurityError, BrowserInteractionError):
                raise
            except Exception as exc:
                raise BrowserInteractionError(f"Filling field '{selector}' failed: {exc}") from exc

    def capture_screenshot(
        self,
        full_page: bool = False,
        filename_prefix: str = "browser_screenshot",
    ) -> ScreenshotResult:
        """Capture a screenshot of the current page and save to data directory."""
        with self._lock:
            page = self._get_active_page()

            # Ensure screenshot output directory exists
            screenshot_dir = get_data_dir() / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{filename_prefix}_{timestamp}.png"
            file_path = screenshot_dir / filename

            try:
                page.screenshot(path=str(file_path), full_page=full_page)
                file_size = file_path.stat().st_size
                viewport = page.viewport_size or {"width": 1280, "height": 800}

                return ScreenshotResult(
                    path=str(file_path),
                    width=viewport.get("width", 1280),
                    height=viewport.get("height", 800),
                    format="png",
                    size_bytes=file_size,
                )
            except Exception as exc:
                raise BrowserError(f"Screenshot capture failed: {exc}") from exc

    # --- Tab Management Capabilities ---

    def new_tab(self, url: str | None = None) -> TabInfo:
        """Open a new browser tab within the isolated context, respecting max tabs limit."""
        with self._lock:
            self.initialize()
            max_tabs = getattr(self._settings, "browser_max_tabs", 5)

            # Clean closed pages
            self._pages = [p for p in self._pages if not p.is_closed()]
            if len(self._pages) >= max_tabs:
                raise BrowserTabLimitError(
                    f"Maximum tabs limit ({max_tabs}) reached. Close an existing tab before opening a new one."
                )

            assert self._context is not None
            page = self._context.new_page()
            self._pages.append(page)
            self._active_page_index = len(self._pages) - 1

            if url:
                self.navigate(url)

            return TabInfo(
                index=self._active_page_index,
                title=page.title(),
                url=page.url,
                is_active=True,
            )

    def list_tabs(self) -> TabListResult:
        """List all currently open tabs with their indices, titles, and URLs."""
        with self._lock:
            self.initialize()
            self._pages = [p for p in self._pages if not p.is_closed()]
            tabs: list[TabInfo] = []

            for i, p in enumerate(self._pages):
                tabs.append(
                    TabInfo(
                        index=i,
                        title=p.title() or "Untitled",
                        url=p.url or "about:blank",
                        is_active=(i == self._active_page_index),
                    )
                )

            return TabListResult(
                tabs=tabs,
                active_index=self._active_page_index,
                total_tabs=len(tabs),
            )

    def switch_tab(self, tab_index: int) -> TabInfo:
        """Switch active focus to a specific tab index."""
        with self._lock:
            self.initialize()
            self._pages = [p for p in self._pages if not p.is_closed()]

            if tab_index < 0 or tab_index >= len(self._pages):
                raise BrowserError(
                    f"Invalid tab index {tab_index}. Active tabs: 0 to {len(self._pages) - 1}"
                )

            self._active_page_index = tab_index
            active_p = self._pages[tab_index]
            active_p.bring_to_front()

            return TabInfo(
                index=tab_index,
                title=active_p.title(),
                url=active_p.url,
                is_active=True,
            )

    def close_tab(self, tab_index: int | None = None) -> TabListResult:
        """Close a specific tab or the active tab."""
        with self._lock:
            self.initialize()
            self._pages = [p for p in self._pages if not p.is_closed()]

            if not self._pages:
                raise BrowserError("No open tabs to close.")

            target_idx = self._active_page_index if tab_index is None else tab_index
            if target_idx < 0 or target_idx >= len(self._pages):
                raise BrowserError(f"Invalid tab index {target_idx}.")

            page_to_close = self._pages.pop(target_idx)
            with contextlib.suppress(Exception):
                page_to_close.close()

            # If all tabs closed, create a fresh blank tab
            if not self._pages and self._context:
                fresh_page = self._context.new_page()
                self._pages = [fresh_page]
                self._active_page_index = 0
            else:
                if self._active_page_index >= len(self._pages):
                    self._active_page_index = len(self._pages) - 1

            return self.list_tabs()
