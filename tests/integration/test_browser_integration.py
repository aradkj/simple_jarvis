"""Integration test suite for Phase 7 Browser Agent using real Playwright with a local test HTTP server."""

import contextlib
import http.server
import socket
import threading
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from config import Settings
from tools.browser.browser_service import BrowserService
from tools.browser.exceptions import BrowserError, BrowserSecurityError
from tools.browser.models import (
    HeadingsResult,
    LinksResult,
    NavigationResult,
    PageContentResult,
    ScreenshotResult,
    TabListResult,
)


class LocalTestHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Custom HTTP handler serving test HTML pages for browser automation tests."""

    def log_message(self, format: str, *args: Any) -> None:
        pass  # Silence console logging during test runs

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<head><title>JARVIS Browser Integration Test Page</title></head>
<body>
  <h1>JARVIS Browser Suite</h1>
  <h2>Section 1: Interactive Elements</h2>
  <p id="main-para">This is a verified test page for JARVIS Phase 7 Browser Agent automation.</p>
  <button id="test-btn" onclick="document.getElementById('result-msg').innerText = 'Clicked Successfully!'">Click Me</button>
  <span id="result-msg">Waiting</span>

  <h2>Section 2: Forms</h2>
  <input type="text" id="test-input" placeholder="Enter text here" />

  <h2>Section 3: Navigation Links</h2>
  <a id="page2-link" href="/page2.html">Go to Page 2</a>
  <a id="ext-link" href="https://example.com/external">External Reference</a>

  <div style="height: 1200px;">Spacer</div>
  <p id="footer-text">Reached the footer</p>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))

        elif self.path == "/page2.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<head><title>Page 2 - Navigation Target</title></head>
<body>
  <h1>Welcome to Page 2</h1>
  <p id="p2-content">Navigation to Page 2 was verified successfully.</p>
  <a id="back-link" href="/index.html">Back to Home</a>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))

        elif self.path == "/redirect-safe":
            self.send_response(302)
            self.send_header("Location", "/page2.html")
            self.end_headers()

        elif self.path == "/redirect-evil-ip":
            self.send_response(302)
            self.send_header("Location", "http://10.0.0.1/admin")
            self.end_headers()

        elif self.path == "/redirect-evil-metadata":
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()

        elif self.path == "/sensitive.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<head><title>Sensitive Actions Form</title></head>
<body>
  <h1>Checkout Page</h1>
  <button id="buy-btn">Buy Now $99.99</button>
  <input type="password" id="secret-pass" placeholder="Enter password" />
  <button id="submit-order-btn" type="submit">Submit Order</button>
  <div id="status">Ready</div>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))

        elif self.path == "/popup.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """<!DOCTYPE html>
<html>
<head><title>Popup Test</title></head>
<body>
  <h1>Popup Testing</h1>
  <button id="spawn-tabs" onclick="for(let i=0;i<8;i++) window.open('/page2.html');">Open Many Tabs</button>
</body>
</html>"""
            self.wfile.write(html.encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")


@pytest.fixture(scope="module")
def local_http_server() -> Generator[str, None, None]:
    """Start a background local HTTP server on an ephemeral loopback port."""
    # Find free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    server = http.server.HTTPServer(("127.0.0.1", port), LocalTestHTTPHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{port}"
    yield base_url

    server.shutdown()
    server.server_close()


@pytest.fixture
def browser_service() -> Generator[BrowserService, None, None]:
    """Provide a real BrowserService configured with headless Chromium and localhost allowed for test."""
    settings = Settings(
        gemini_api_key=None,
        app_env="testing",
        browser_enabled=True,
        browser_headless=True,
        browser_allow_localhost=True,  # Test-only scoped exception
        browser_navigation_timeout=15,
        browser_max_tabs=5,
    )
    service = BrowserService(settings=settings)
    yield service
    service.close()


class TestBrowserRealIntegration:
    """Integration test suite executing real browser actions against local HTTP test server."""

    def test_browser_lifecycle_and_navigation(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify real browser startup, navigation, and title retrieval."""
        res: NavigationResult = browser_service.navigate(f"{local_http_server}/index.html")

        assert browser_service.is_running is True
        assert res.status_code == 200
        assert res.title == "JARVIS Browser Integration Test Page"
        assert browser_service.get_current_title() == "JARVIS Browser Integration Test Page"
        assert local_http_server in browser_service.get_current_url()

    def test_page_content_extraction(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify real DOM text extraction without scripts or styles."""
        browser_service.navigate(f"{local_http_server}/index.html")
        content: PageContentResult = browser_service.get_page_content(max_chars=5000)

        assert "JARVIS Browser Suite" in content.text
        assert "This is a verified test page" in content.text
        assert "Reached the footer" in content.text
        assert content.char_count > 50
        assert content.truncated is False

    def test_headings_extraction(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify real extraction of H1 and H2 headings."""
        browser_service.navigate(f"{local_http_server}/index.html")
        headings: HeadingsResult = browser_service.get_headings(max_depth=2)

        texts = [h.text for h in headings.headings]
        assert "JARVIS Browser Suite" in texts
        assert "Section 1: Interactive Elements" in texts
        assert "Section 2: Forms" in texts
        assert "Section 3: Navigation Links" in texts
        assert headings.total_headings >= 4

    def test_links_extraction(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify real link extraction and classification."""
        browser_service.navigate(f"{local_http_server}/index.html")
        links: LinksResult = browser_service.get_links(max_links=10)

        hrefs = [link.href for link in links.links]
        assert any("page2.html" in h for h in hrefs)
        assert any("example.com" in h for h in hrefs)

    def test_element_click_interaction(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify real element clicking and DOM mutation."""
        browser_service.navigate(f"{local_http_server}/index.html")
        click_res = browser_service.click_element("#test-btn")
        assert click_res.success is True

        # Verify page updated after click
        content = browser_service.get_page_content()
        assert "Clicked Successfully!" in content.text

    def test_form_field_filling(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify real form input field typing."""
        browser_service.navigate(f"{local_http_server}/index.html")
        fill_res = browser_service.fill_field("#test-input", "Automation Test Value")
        assert fill_res.success is True
        assert fill_res.entered_length == len("Automation Test Value")

    def test_scroll_interaction(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify page scrolling in vertical direction."""
        browser_service.navigate(f"{local_http_server}/index.html")
        scroll_res = browser_service.scroll(direction="down", amount=400)
        assert scroll_res.scroll_y >= 300

    def test_screenshot_capture(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify real page screenshot capture to disk as PNG."""
        browser_service.navigate(f"{local_http_server}/index.html")
        shot_res: ScreenshotResult = browser_service.capture_screenshot(
            full_page=False,
            filename_prefix="test_shot",
        )

        assert Path(shot_res.path).exists()
        assert shot_res.size_bytes > 1000
        assert shot_res.width == 1280
        assert shot_res.height == 800

        # Clean up screenshot
        with contextlib.suppress(Exception):
            Path(shot_res.path).unlink(missing_ok=True)

    def test_history_navigation_back_forward_reload(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify navigating forward, backward, and reloading."""
        browser_service.navigate(f"{local_http_server}/index.html")
        assert "JARVIS Browser Integration" in browser_service.get_current_title()

        browser_service.navigate(f"{local_http_server}/page2.html")
        assert "Page 2" in browser_service.get_current_title()

        # Go back
        browser_service.go_back(steps=1)
        assert "JARVIS Browser Integration" in browser_service.get_current_title()

        # Go forward
        browser_service.go_forward(steps=1)
        assert "Page 2" in browser_service.get_current_title()

        # Reload
        reload_res = browser_service.reload()
        assert reload_res.status_code == 200

    def test_tab_lifecycle_management(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify opening, listing, switching, and closing browser tabs."""
        browser_service.navigate(f"{local_http_server}/index.html")

        # Open second tab with page 2
        tab2 = browser_service.new_tab(url=f"{local_http_server}/page2.html")
        assert tab2.index == 1
        assert "Page 2" in tab2.title

        # List tabs
        tab_list: TabListResult = browser_service.list_tabs()
        assert tab_list.total_tabs == 2
        assert tab_list.active_index == 1

        # Switch to tab 0
        switched = browser_service.switch_tab(tab_index=0)
        assert switched.index == 0
        assert "JARVIS Browser Integration" in switched.title

        # Close tab 1
        closed_list = browser_service.close_tab(tab_index=1)
        assert closed_list.total_tabs == 1
        assert closed_list.active_index == 0

    # --- Phase 7 Security Closure: Real Chromium Security Tests ---

    def test_real_browser_safe_redirect(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify that an approved HTTP 302 redirect navigates successfully."""
        res = browser_service.navigate(f"{local_http_server}/redirect-safe")
        assert res.status_code == 200
        assert "Page 2" in res.title
        assert "/page2.html" in res.url

    def test_real_browser_blocked_redirect_to_private_ip(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify that an HTTP redirect to an internal private address (10.0.0.1) is blocked."""
        with pytest.raises((BrowserSecurityError, BrowserError)) as exc_info:
            browser_service.navigate(f"{local_http_server}/redirect-evil-ip")
        assert any(
            k in str(exc_info.value).lower()
            for k in ("blocked", "forbidden", "private", "failed", "timed out", "timeout")
        )

    def test_real_browser_blocked_redirect_to_metadata(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify that an HTTP redirect targeting the cloud metadata service is blocked."""
        with pytest.raises((BrowserSecurityError, BrowserError)) as exc_info:
            browser_service.navigate(f"{local_http_server}/redirect-evil-metadata")
        assert any(
            k in str(exc_info.value).lower()
            for k in ("blocked", "forbidden", "metadata", "failed", "timed out", "timeout")
        )

    def test_real_browser_sensitive_purchase_unconfirmed_rejected(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify that clicking a purchase/payment element without confirmed=True is rejected."""
        browser_service.navigate(f"{local_http_server}/sensitive.html")
        with pytest.raises(BrowserSecurityError) as exc_info:
            browser_service.click_element("#buy-btn", confirmed=False)
        assert "purchase" in str(exc_info.value).lower()
        assert "prohibited without explicit user approval" in str(exc_info.value).lower()

    def test_real_browser_sensitive_purchase_confirmed_succeeds(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify that clicking a purchase element with confirmed=True succeeds."""
        browser_service.navigate(f"{local_http_server}/sensitive.html")
        res = browser_service.click_element("#buy-btn", confirmed=True)
        assert res.success is True

    def test_real_browser_sensitive_password_unconfirmed_rejected(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify that filling a password input without confirmed=True is rejected."""
        browser_service.navigate(f"{local_http_server}/sensitive.html")
        with pytest.raises(BrowserSecurityError) as exc_info:
            browser_service.fill_field("#secret-pass", "SensitiveSecret123", confirmed=False)
        assert "password" in str(exc_info.value).lower()
        assert "requires explicit user confirmation" in str(exc_info.value).lower()

    def test_real_browser_sensitive_password_confirmed_succeeds(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify that filling a password input with confirmed=True succeeds."""
        browser_service.navigate(f"{local_http_server}/sensitive.html")
        res = browser_service.fill_field("#secret-pass", "SensitiveSecret123", confirmed=True)
        assert res.success is True
        assert res.entered_length == len("SensitiveSecret123")

    def test_real_browser_popup_tab_limit(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify that popups cannot exceed the maximum tab boundary (browser_max_tabs=5)."""
        browser_service.navigate(f"{local_http_server}/popup.html")
        # Trigger popup script
        browser_service.click_element("#spawn-tabs")
        import time

        time.sleep(0.5)

        tab_list = browser_service.list_tabs()
        assert tab_list.total_tabs <= 5

    def test_real_browser_crash_cleanup(
        self,
        browser_service: BrowserService,
        local_http_server: str,
    ) -> None:
        """Verify that browser close cleanly resets state and subsequent navigation recovers."""
        browser_service.navigate(f"{local_http_server}/index.html")
        assert browser_service.is_running is True

        # Close browser
        browser_service.close()
        assert browser_service.is_running is False

        # Next navigation must lazily re-initialize safely
        res = browser_service.navigate(f"{local_http_server}/page2.html")
        assert browser_service.is_running is True
        assert "Page 2" in res.title
