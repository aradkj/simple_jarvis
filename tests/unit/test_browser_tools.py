"""Unit tests for all 16 JARVIS Phase 7 Browser Agent tools with mocked BrowserService."""

from unittest.mock import MagicMock

import pytest

from core.execution_context import ExecutionContext
from core.permissions import PermissionCategory
from tools.base import ToolExecutionStatus
from tools.browser.browser_service import BrowserService
from tools.browser.browser_tools import (
    BrowserClickElementTool,
    BrowserFillFieldTool,
    BrowserGetHeadingsTool,
    BrowserGetLinksTool,
    BrowserGetPageContentTool,
    BrowserGoBackTool,
    BrowserGoForwardTool,
    BrowserNavigateTool,
    BrowserReloadTool,
    BrowserScreenshotTool,
    BrowserScrollTool,
    BrowserSearchTool,
    BrowserTabCloseTool,
    BrowserTabListTool,
    BrowserTabNewTool,
    BrowserTabSwitchTool,
)
from tools.browser.exceptions import (
    BrowserInteractionError,
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
    ScrollResult,
    SearchResult,
    SearchResultItem,
    TabInfo,
    TabListResult,
)


@pytest.fixture
def mock_service() -> MagicMock:
    """Provide a mocked BrowserService instance."""
    return MagicMock(spec=BrowserService)


@pytest.fixture
def context() -> ExecutionContext:
    """Provide an uncancelled ExecutionContext."""
    return ExecutionContext()


@pytest.fixture
def cancelled_context() -> ExecutionContext:
    """Provide a cancelled ExecutionContext."""
    ctx = ExecutionContext()
    ctx.cancel()
    return ctx


class TestBrowserToolsUnit:
    """Unit tests for tool definitions, schema validation, and execution logic."""

    # 1. BrowserNavigateTool
    def test_navigate_tool_success(
        self, mock_service: MagicMock, context: ExecutionContext
    ) -> None:
        mock_service.navigate.return_value = NavigationResult(
            url="https://example.com",
            title="Example Domain",
            status_code=200,
            timing_ms=120.5,
        )
        tool = BrowserNavigateTool(mock_service)
        assert tool.name == "browser_navigate"
        assert tool.category == PermissionCategory.BROWSER_NAVIGATE

        params = tool.validate_input({"url": "https://example.com"})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["url"] == "https://example.com"
        assert res.data["title"] == "Example Domain"
        mock_service.navigate.assert_called_once_with(
            url="https://example.com", wait_until="domcontentloaded"
        )

    def test_navigate_tool_cancellation(
        self, mock_service: MagicMock, cancelled_context: ExecutionContext
    ) -> None:
        tool = BrowserNavigateTool(mock_service)
        params = tool.validate_input({"url": "https://example.com"})
        res = tool.execute(params, cancelled_context)
        assert res.status == ToolExecutionStatus.CANCELLED
        mock_service.navigate.assert_not_called()

    def test_navigate_tool_blocked_url_error(
        self, mock_service: MagicMock, context: ExecutionContext
    ) -> None:
        mock_service.navigate.side_effect = URLValidationError(
            "Navigation to 'file:///etc/passwd' blocked"
        )
        tool = BrowserNavigateTool(mock_service)
        params = tool.validate_input({"url": "file:///etc/passwd"})
        res = tool.execute(params, context)
        assert res.status == ToolExecutionStatus.FAILED
        assert "blocked" in res.error

    # 2. BrowserSearchTool
    def test_search_tool_success(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.search_web.return_value = SearchResult(
            query="FastAPI",
            results=[
                SearchResultItem(
                    title="FastAPI", url="https://fastapi.tiangolo.com", snippet="FastAPI framework"
                ),
            ],
            total_found=1,
        )
        tool = BrowserSearchTool(mock_service)
        assert tool.category == PermissionCategory.BROWSER_READ

        params = tool.validate_input({"query": "FastAPI", "num_results": 3})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["total_found"] == 1
        assert res.data["results"][0]["title"] == "FastAPI"

    # 3. BrowserGetPageContentTool
    def test_page_content_tool_success(
        self, mock_service: MagicMock, context: ExecutionContext
    ) -> None:
        mock_service.get_page_content.return_value = PageContentResult(
            url="https://example.com",
            title="Example Domain",
            text="This domain is for use in illustrative examples.",
            char_count=48,
            truncated=False,
        )
        tool = BrowserGetPageContentTool(mock_service)
        params = tool.validate_input({"max_chars": 5000})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["char_count"] == 48
        assert res.data["truncated"] is False

    # 4. BrowserGetHeadingsTool
    def test_get_headings_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.get_headings.return_value = HeadingsResult(
            url="https://example.com",
            title="Example",
            headings=[
                HeadingItem(level=1, text="Main Title"),
                HeadingItem(level=2, text="Sub Title"),
            ],
            total_headings=2,
        )
        tool = BrowserGetHeadingsTool(mock_service)
        params = tool.validate_input({"max_depth": 2})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["total_headings"] == 2
        assert len(res.data["headings"]) == 2

    # 5. BrowserGetLinksTool
    def test_get_links_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.get_links.return_value = LinksResult(
            url="https://example.com",
            links=[
                LinkItem(
                    text="More information...",
                    href="https://iana.org/domains/example",
                    is_external=True,
                )
            ],
            total_links=1,
        )
        tool = BrowserGetLinksTool(mock_service)
        params = tool.validate_input({"max_links": 10, "filter_internal": False})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["total_links"] == 1

    # 6. BrowserClickElementTool
    def test_click_element_tool_success(
        self, mock_service: MagicMock, context: ExecutionContext
    ) -> None:
        mock_service.click_element.return_value = ClickResult(
            selector="button#submit",
            success=True,
            navigation_occurred=True,
            current_url="https://example.com/success",
        )
        tool = BrowserClickElementTool(mock_service)
        assert tool.category == PermissionCategory.BROWSER_INTERACT

        params = tool.validate_input({"selector": "button#submit", "timeout_ms": 3000})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["navigation_occurred"] is True

    def test_click_element_tool_failure(
        self, mock_service: MagicMock, context: ExecutionContext
    ) -> None:
        mock_service.click_element.side_effect = BrowserInteractionError("Element not found")
        tool = BrowserClickElementTool(mock_service)
        params = tool.validate_input({"selector": "button.missing"})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.FAILED
        assert "not found" in res.error

    # 7. BrowserScrollTool
    def test_scroll_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.scroll.return_value = ScrollResult(
            direction="down",
            amount=500,
            scroll_y=500,
            max_scroll_y=2000,
        )
        tool = BrowserScrollTool(mock_service)
        params = tool.validate_input({"direction": "down", "amount": 500})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["scroll_y"] == 500

    # 8. BrowserFillFieldTool
    def test_fill_field_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.fill_field.return_value = FillResult(
            selector="input#search",
            success=True,
            entered_length=6,
            press_enter=True,
        )
        tool = BrowserFillFieldTool(mock_service)
        params = tool.validate_input(
            {"selector": "input#search", "value": "Python", "press_enter": True}
        )
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["entered_length"] == 6

    # 9. BrowserScreenshotTool
    def test_screenshot_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.capture_screenshot.return_value = ScreenshotResult(
            path="C:/AI/jarvis/data/screenshots/test.png",
            width=1280,
            height=800,
            size_bytes=45200,
        )
        tool = BrowserScreenshotTool(mock_service)
        assert tool.category == PermissionCategory.BROWSER_SCREENSHOT

        params = tool.validate_input({"full_page": False})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert "test.png" in res.data["path"]

    # 10. BrowserTabNewTool
    def test_tab_new_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.new_tab.return_value = TabInfo(
            index=1,
            title="New Tab",
            url="about:blank",
            is_active=True,
        )
        tool = BrowserTabNewTool(mock_service)
        assert tool.category == PermissionCategory.BROWSER_TAB

        params = tool.validate_input({})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["index"] == 1

    # 11. BrowserTabListTool
    def test_tab_list_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.list_tabs.return_value = TabListResult(
            tabs=[
                TabInfo(index=0, title="Page 1", url="https://example.com", is_active=True),
                TabInfo(index=1, title="Page 2", url="https://python.org", is_active=False),
            ],
            active_index=0,
            total_tabs=2,
        )
        tool = BrowserTabListTool(mock_service)
        params = tool.validate_input({})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["total_tabs"] == 2

    # 12. BrowserTabSwitchTool
    def test_tab_switch_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.switch_tab.return_value = TabInfo(
            index=1,
            title="Page 2",
            url="https://python.org",
            is_active=True,
        )
        tool = BrowserTabSwitchTool(mock_service)
        params = tool.validate_input({"tab_index": 1})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["index"] == 1

    # 13. BrowserTabCloseTool
    def test_tab_close_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.close_tab.return_value = TabListResult(
            tabs=[TabInfo(index=0, title="Page 1", url="https://example.com", is_active=True)],
            active_index=0,
            total_tabs=1,
        )
        tool = BrowserTabCloseTool(mock_service)
        params = tool.validate_input({"tab_index": 1})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["total_tabs"] == 1

    # 14. BrowserGoBackTool
    def test_go_back_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.go_back.return_value = NavigationResult(
            url="https://example.com/page1",
            title="Page 1",
            status_code=200,
        )
        tool = BrowserGoBackTool(mock_service)
        params = tool.validate_input({"steps": 1})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["url"] == "https://example.com/page1"

    # 15. BrowserGoForwardTool
    def test_go_forward_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.go_forward.return_value = NavigationResult(
            url="https://example.com/page2",
            title="Page 2",
            status_code=200,
        )
        tool = BrowserGoForwardTool(mock_service)
        params = tool.validate_input({"steps": 1})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        assert res.data["url"] == "https://example.com/page2"

    # 16. BrowserReloadTool
    def test_reload_tool(self, mock_service: MagicMock, context: ExecutionContext) -> None:
        mock_service.reload.return_value = NavigationResult(
            url="https://example.com",
            title="Example Domain",
            status_code=200,
        )
        tool = BrowserReloadTool(mock_service)
        params = tool.validate_input({"ignore_cache": True})
        res = tool.execute(params, context)

        assert res.status == ToolExecutionStatus.SUCCESS
        mock_service.reload.assert_called_once_with(ignore_cache=True)
