"""Tool implementations for JARVIS Phase 7 Browser Agent."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from core.permissions import PermissionCategory
from tools.base import BaseTool, ToolResult
from tools.browser.exceptions import BrowserError
from tools.browser.models import (
    BrowserClickElementInput,
    BrowserFillFieldInput,
    BrowserGetHeadingsInput,
    BrowserGetLinksInput,
    BrowserGetPageContentInput,
    BrowserGoBackInput,
    BrowserGoForwardInput,
    BrowserNavigateInput,
    BrowserReloadInput,
    BrowserScreenshotInput,
    BrowserScrollInput,
    BrowserSearchInput,
    BrowserTabCloseInput,
    BrowserTabNewInput,
    BrowserTabSwitchInput,
    EmptyInput,
)

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext
    from tools.browser.browser_service import BrowserService


class BaseBrowserTool(BaseTool):
    """Base class for all browser tools holding a BrowserService reference."""

    def __init__(self, browser_service: BrowserService) -> None:
        self.browser_service = browser_service
        super().__init__()

    @classmethod
    def get_definition(cls):
        from core.tool_proposal import RiskLevel, ToolDefinition

        schema = (
            cls.input_schema.model_json_schema()
            if hasattr(cls, "input_schema") and cls.input_schema
            else {"type": "object", "properties": {}}
        )
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema=schema,
            requires_approval=False,
        )


class BrowserNavigateTool(BaseBrowserTool):
    """Navigate the browser to an approved, validated web URL."""

    name = "browser_navigate"
    description = "Navigate to a verified, safe web URL in the browser (http/https only, internal networks blocked)."
    category = PermissionCategory.BROWSER_NAVIGATE
    input_schema = BrowserNavigateInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Browser navigation cancelled by user.")

        data: BrowserNavigateInput = params  # type: ignore
        try:
            res = self.browser_service.navigate(url=data.url, wait_until=data.wait_until)
            return ToolResult.success(
                data=res.model_dump(),
                url=res.url,
                title=res.title,
                status_code=res.status_code,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Unexpected browser navigation error: {exc}")


class BrowserSearchTool(BaseBrowserTool):
    """Search the web for information using a safe search interface."""

    name = "browser_search"
    description = (
        "Search the web for keywords or queries and return structured result snippets and links."
    )
    category = PermissionCategory.BROWSER_READ
    input_schema = BrowserSearchInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Web search cancelled by user.")

        data: BrowserSearchInput = params  # type: ignore
        try:
            res = self.browser_service.search_web(query=data.query, num_results=data.num_results)
            return ToolResult.success(
                data=res.model_dump(),
                query=res.query,
                total_found=res.total_found,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Web search error: {exc}")


class BrowserGetPageContentTool(BaseBrowserTool):
    """Extract visible, cleaned text and structural content from the current web page."""

    name = "browser_get_page_content"
    description = "Extract clean visible text content and heading overview from the currently active web page."
    category = PermissionCategory.BROWSER_READ
    input_schema = BrowserGetPageContentInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Page content extraction cancelled.")

        data: BrowserGetPageContentInput = params  # type: ignore
        try:
            res = self.browser_service.get_page_content(
                max_chars=data.max_chars,
                include_links=data.include_links,
            )
            return ToolResult.success(
                data=res.model_dump(),
                url=res.url,
                title=res.title,
                char_count=res.char_count,
                truncated=res.truncated,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Page content extraction error: {exc}")


class BrowserGetHeadingsTool(BaseBrowserTool):
    """Extract heading structure (H1, H2, H3) from the current web page."""

    name = "browser_get_headings"
    description = (
        "Extract the heading hierarchy (H1-H6) and section titles from the current web page."
    )
    category = PermissionCategory.BROWSER_READ
    input_schema = BrowserGetHeadingsInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Heading extraction cancelled.")

        data: BrowserGetHeadingsInput = params  # type: ignore
        try:
            res = self.browser_service.get_headings(max_depth=data.max_depth)
            return ToolResult.success(
                data=res.model_dump(),
                url=res.url,
                total_headings=res.total_headings,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Heading extraction error: {exc}")


class BrowserGetLinksTool(BaseBrowserTool):
    """Extract visible hyperlinks from the active web page."""

    name = "browser_get_links"
    description = (
        "Extract hyperlinks and source URLs from the active web page with domain classification."
    )
    category = PermissionCategory.BROWSER_READ
    input_schema = BrowserGetLinksInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Link extraction cancelled.")

        data: BrowserGetLinksInput = params  # type: ignore
        try:
            res = self.browser_service.get_links(
                max_links=data.max_links,
                filter_internal=data.filter_internal,
            )
            return ToolResult.success(
                data=res.model_dump(),
                url=res.url,
                total_links=res.total_links,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Link extraction error: {exc}")


class BrowserClickElementTool(BaseBrowserTool):
    """Click an identified safe element on the web page."""

    name = "browser_click_element"
    description = "Click a safe button, link, or interactive element on the current web page."
    category = PermissionCategory.BROWSER_INTERACT
    input_schema = BrowserClickElementInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Click operation cancelled.")

        data: BrowserClickElementInput = params  # type: ignore
        try:
            res = self.browser_service.click_element(
                selector=data.selector,
                timeout_ms=data.timeout_ms,
                confirmed=data.confirmed,
            )
            return ToolResult.success(
                data=res.model_dump(),
                selector=res.selector,
                navigation_occurred=res.navigation_occurred,
                current_url=res.current_url,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Element click error: {exc}")


class BrowserScrollTool(BaseBrowserTool):
    """Scroll the active web page."""

    name = "browser_scroll"
    description = "Scroll the web page up, down, or jump to top/bottom."
    category = PermissionCategory.BROWSER_INTERACT
    input_schema = BrowserScrollInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Scroll cancelled.")

        data: BrowserScrollInput = params  # type: ignore
        try:
            res = self.browser_service.scroll(direction=data.direction, amount=data.amount)
            return ToolResult.success(
                data=res.model_dump(),
                direction=res.direction,
                scroll_y=res.scroll_y,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Scroll error: {exc}")


class BrowserFillFieldTool(BaseBrowserTool):
    """Fill a non-sensitive field in a web form."""

    name = "browser_fill_field"
    description = "Fill a non-sensitive input or textarea element on the active web page."
    category = PermissionCategory.BROWSER_INTERACT
    input_schema = BrowserFillFieldInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Field input cancelled.")

        data: BrowserFillFieldInput = params  # type: ignore
        try:
            res = self.browser_service.fill_field(
                selector=data.selector,
                value=data.value,
                press_enter=data.press_enter,
                confirmed=data.confirmed,
            )
            return ToolResult.success(
                data=res.model_dump(),
                selector=res.selector,
                entered_length=res.entered_length,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Field fill error: {exc}")


class BrowserScreenshotTool(BaseBrowserTool):
    """Capture a screenshot of the visible web page."""

    name = "browser_screenshot"
    description = "Capture an image screenshot of the current web page and save to data directory."
    category = PermissionCategory.BROWSER_SCREENSHOT
    input_schema = BrowserScreenshotInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Screenshot cancelled.")

        data: BrowserScreenshotInput = params  # type: ignore
        try:
            res = self.browser_service.capture_screenshot(
                full_page=data.full_page,
                filename_prefix=data.filename_prefix,
            )
            return ToolResult.success(
                data=res.model_dump(),
                path=res.path,
                size_bytes=res.size_bytes,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Screenshot error: {exc}")


class BrowserTabNewTool(BaseBrowserTool):
    """Open a new browser tab."""

    name = "browser_tab_new"
    description = (
        "Open a new browser tab within the isolated context, optionally navigating to a URL."
    )
    category = PermissionCategory.BROWSER_TAB
    input_schema = BrowserTabNewInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("New tab cancelled.")

        data: BrowserTabNewInput = params  # type: ignore
        try:
            res = self.browser_service.new_tab(url=data.url)
            return ToolResult.success(
                data=res.model_dump(),
                index=res.index,
                title=res.title,
                url=res.url,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"New tab error: {exc}")


class BrowserTabListTool(BaseBrowserTool):
    """List all currently open browser tabs."""

    name = "browser_tab_list"
    description = "List all currently open browser tabs with their index, title, and current URL."
    category = PermissionCategory.BROWSER_TAB
    input_schema = EmptyInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        try:
            res = self.browser_service.list_tabs()
            return ToolResult.success(
                data=res.model_dump(),
                active_index=res.active_index,
                total_tabs=res.total_tabs,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"List tabs error: {exc}")


class BrowserTabSwitchTool(BaseBrowserTool):
    """Switch active focus to a specific tab index."""

    name = "browser_tab_switch"
    description = "Switch active tab focus to the specified tab index."
    category = PermissionCategory.BROWSER_TAB
    input_schema = BrowserTabSwitchInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Tab switch cancelled.")

        data: BrowserTabSwitchInput = params  # type: ignore
        try:
            res = self.browser_service.switch_tab(tab_index=data.tab_index)
            return ToolResult.success(
                data=res.model_dump(),
                index=res.index,
                title=res.title,
                url=res.url,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Tab switch error: {exc}")


class BrowserTabCloseTool(BaseBrowserTool):
    """Close a specific tab or active tab."""

    name = "browser_tab_close"
    description = "Close an open browser tab by index (or close active tab if not specified)."
    category = PermissionCategory.BROWSER_TAB
    input_schema = BrowserTabCloseInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Tab close cancelled.")

        data: BrowserTabCloseInput = params  # type: ignore
        try:
            res = self.browser_service.close_tab(tab_index=data.tab_index)
            return ToolResult.success(
                data=res.model_dump(),
                total_tabs=res.total_tabs,
                active_index=res.active_index,
            )
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Tab close error: {exc}")


class BrowserGoBackTool(BaseBrowserTool):
    """Navigate back in browser history."""

    name = "browser_go_back"
    description = "Navigate backward in the active tab's browsing history."
    category = PermissionCategory.BROWSER_NAVIGATE
    input_schema = BrowserGoBackInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        data: BrowserGoBackInput = params  # type: ignore
        try:
            res = self.browser_service.go_back(steps=data.steps)
            return ToolResult.success(data=res.model_dump(), url=res.url, title=res.title)
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Go back error: {exc}")


class BrowserGoForwardTool(BaseBrowserTool):
    """Navigate forward in browser history."""

    name = "browser_go_forward"
    description = "Navigate forward in the active tab's browsing history."
    category = PermissionCategory.BROWSER_NAVIGATE
    input_schema = BrowserGoForwardInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        data: BrowserGoForwardInput = params  # type: ignore
        try:
            res = self.browser_service.go_forward(steps=data.steps)
            return ToolResult.success(data=res.model_dump(), url=res.url, title=res.title)
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Go forward error: {exc}")


class BrowserReloadTool(BaseBrowserTool):
    """Reload the current web page."""

    name = "browser_reload"
    description = "Reload the currently active web page."
    category = PermissionCategory.BROWSER_NAVIGATE
    input_schema = BrowserReloadInput

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        data: BrowserReloadInput = params  # type: ignore
        try:
            res = self.browser_service.reload(ignore_cache=data.ignore_cache)
            return ToolResult.success(data=res.model_dump(), url=res.url, title=res.title)
        except BrowserError as exc:
            return ToolResult.failed(str(exc))
        except Exception as exc:
            return ToolResult.failed(f"Reload error: {exc}")
