"""Input and output data models for JARVIS Phase 7 Browser Agent tools."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --- Navigation Models ---


class BrowserNavigateInput(BaseModel):
    """Input parameters for browser navigation."""

    url: str = Field(
        ...,
        description="The destination URL to navigate to (must be http or https).",
        min_length=1,
        max_length=2048,
    )
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = Field(
        default="domcontentloaded",
        description="When to consider navigation complete.",
    )


class BrowserGoBackInput(BaseModel):
    """Input parameters for navigating back in history."""

    steps: int = Field(default=1, ge=1, le=10, description="Number of steps to navigate back.")


class BrowserGoForwardInput(BaseModel):
    """Input parameters for navigating forward in history."""

    steps: int = Field(default=1, ge=1, le=10, description="Number of steps to navigate forward.")


class BrowserReloadInput(BaseModel):
    """Input parameters for reloading the current page."""

    ignore_cache: bool = Field(default=False, description="Whether to bypass browser cache.")


class EmptyInput(BaseModel):
    """Empty input schema for parameterless tools."""


# --- Search Models ---


class BrowserSearchInput(BaseModel):
    """Input parameters for searching the web."""

    query: str = Field(
        ...,
        description="The search keywords or query string.",
        min_length=1,
        max_length=500,
    )
    num_results: int = Field(
        default=5,
        ge=1,
        le=15,
        description="Maximum number of search results to return.",
    )


class SearchResultItem(BaseModel):
    """Single search result entry."""

    title: str
    url: str
    snippet: str = ""


class SearchResult(BaseModel):
    """Structured response from web search."""

    query: str
    results: list[SearchResultItem] = Field(default_factory=list)
    total_found: int = 0
    search_provider: str = "duckduckgo"


# --- Page Inspection Models ---


class BrowserGetPageContentInput(BaseModel):
    """Input parameters for extracting visible text from current page."""

    max_chars: int = Field(
        default=16000,
        ge=100,
        le=100000,
        description="Maximum characters of visible text to extract.",
    )
    include_links: bool = Field(
        default=False,
        description="Whether to include inline link references in markdown format.",
    )


class BrowserGetHeadingsInput(BaseModel):
    """Input parameters for extracting heading structure."""

    max_depth: int = Field(
        default=3,
        ge=1,
        le=6,
        description="Maximum heading level (1 for h1 only, 3 for h1-h3, up to 6).",
    )


class BrowserGetLinksInput(BaseModel):
    """Input parameters for extracting links from the page."""

    max_links: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of links to extract.",
    )
    filter_internal: bool = Field(
        default=False,
        description="If True, only return links within the same origin/domain.",
    )


# --- Safe Interaction Models ---


class BrowserClickElementInput(BaseModel):
    """Input parameters for clicking a page element."""

    selector: str = Field(
        ...,
        description="CSS selector, text selector (e.g. 'text=Submit'), or XPath for target element.",
        min_length=1,
        max_length=500,
    )
    timeout_ms: int = Field(
        default=5000,
        ge=500,
        le=30000,
        description="Maximum milliseconds to wait for element to be visible and clickable.",
    )
    confirmed: bool = Field(
        default=False,
        description="Explicit user confirmation for sensitive click actions (e.g. submit, purchase).",
    )


class BrowserScrollInput(BaseModel):
    """Input parameters for scrolling the page."""

    direction: Literal["up", "down", "top", "bottom"] = Field(
        default="down",
        description="Scroll direction or jump to top/bottom.",
    )
    amount: int = Field(
        default=500,
        ge=50,
        le=5000,
        description="Scroll pixel distance (ignored if direction is 'top' or 'bottom').",
    )


class BrowserFillFieldInput(BaseModel):
    """Input parameters for filling a form field."""

    selector: str = Field(
        ...,
        description="CSS selector or locator for the input or textarea element.",
        min_length=1,
        max_length=500,
    )
    value: str = Field(
        ...,
        description="Text value to enter into the field (non-sensitive fields only).",
        max_length=5000,
    )
    press_enter: bool = Field(
        default=False,
        description="Whether to press Enter key after filling the field.",
    )
    confirmed: bool = Field(
        default=False,
        description="Explicit user confirmation for sensitive input fields (e.g. passwords).",
    )


class BrowserScreenshotInput(BaseModel):
    """Input parameters for capturing a screenshot."""

    full_page: bool = Field(
        default=False,
        description="Whether to capture full scrollable page or only visible viewport.",
    )
    filename_prefix: str = Field(
        default="browser_screenshot",
        description="Filename prefix for the saved PNG screenshot.",
        max_length=50,
    )


# --- Tab Models ---


class BrowserTabNewInput(BaseModel):
    """Input parameters for opening a new browser tab."""

    url: str | None = Field(
        default=None,
        description="Optional initial URL to navigate to in the new tab.",
        max_length=2048,
    )


class BrowserTabSwitchInput(BaseModel):
    """Input parameters for switching to an open tab."""

    tab_index: int = Field(
        ...,
        ge=0,
        le=20,
        description="Zero-based index of the tab to activate.",
    )


class BrowserTabCloseInput(BaseModel):
    """Input parameters for closing a browser tab."""

    tab_index: int | None = Field(
        default=None,
        ge=0,
        le=20,
        description="Index of tab to close (default: current active tab).",
    )


# --- Output Data Models ---


class NavigationResult(BaseModel):
    """Outcome of a page navigation."""

    url: str
    title: str
    status_code: int = 200
    timing_ms: float = 0.0
    load_state: str = "completed"


class PageContentResult(BaseModel):
    """Extracted text and structural content from the current page."""

    url: str
    title: str
    text: str
    char_count: int
    truncated: bool = False
    headings_summary: list[str] = Field(default_factory=list)


class HeadingItem(BaseModel):
    """Individual heading on the page."""

    level: int
    text: str


class HeadingsResult(BaseModel):
    """Collection of headings extracted from the page."""

    url: str
    title: str
    headings: list[HeadingItem] = Field(default_factory=list)
    total_headings: int = 0


class LinkItem(BaseModel):
    """Individual link extracted from the page."""

    text: str
    href: str
    is_external: bool = False


class LinksResult(BaseModel):
    """Collection of links extracted from the page."""

    url: str
    links: list[LinkItem] = Field(default_factory=list)
    total_links: int = 0


class ClickResult(BaseModel):
    """Result of an element click action."""

    selector: str
    success: bool
    navigation_occurred: bool = False
    current_url: str = ""
    current_title: str = ""


class ScrollResult(BaseModel):
    """Result of a scroll action."""

    direction: str
    amount: int
    scroll_x: int = 0
    scroll_y: int = 0
    max_scroll_y: int = 0


class FillResult(BaseModel):
    """Result of filling a field."""

    selector: str
    success: bool
    entered_length: int
    press_enter: bool = False


class ScreenshotResult(BaseModel):
    """Result of a screenshot capture."""

    path: str
    width: int
    height: int
    format: str = "png"
    size_bytes: int = 0


class TabInfo(BaseModel):
    """Summary of a single browser tab."""

    index: int
    title: str
    url: str
    is_active: bool = False


class TabListResult(BaseModel):
    """Summary of all open browser tabs."""

    tabs: list[TabInfo] = Field(default_factory=list)
    active_index: int = 0
    total_tabs: int = 0
