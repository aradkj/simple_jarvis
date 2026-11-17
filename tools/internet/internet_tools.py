"""Internet Search and Information Retrieval Tools for JARVIS.

Provides tools for live internet search and web page content inspection with
source attribution and URL safety checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult
from tools.internet.internet_service import InternetSearchService

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


class InternetSearchInput(BaseModel):
    """Input parameters for internet web search."""

    query: str = Field(description="Search terms or question to look up on the live internet")
    max_results: int = Field(
        default=5, description="Maximum number of search results to return (1 to 10)"
    )


class InternetPageReadInput(BaseModel):
    """Input parameters for reading web page content."""

    url: str = Field(description="Valid HTTP or HTTPS web URL to retrieve and read")
    max_chars: int = Field(default=4000, description="Maximum characters of text to extract")


class InternetSearchTool(BaseTool):
    """Live web search tool accessing the real internet."""

    name = "internet_search"
    description = (
        "Search the live internet for current information, news, websites, documentation, and facts. "
        "Returns titles, snippets, source URLs, and retrieval timestamps."
    )
    category = PermissionCategory.READ_ONLY
    input_schema = InternetSearchInput

    def __init__(self, service: InternetSearchService | None = None) -> None:
        super().__init__()
        self.service = service or InternetSearchService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Internet search cancelled by user")

        assert isinstance(params, InternetSearchInput)
        try:
            results = self.service.search(query=params.query, max_results=params.max_results)
            return ToolResult.success(
                data=[
                    {
                        "title": r.title,
                        "url": r.url,
                        "snippet": r.snippet,
                        "domain": r.source_domain,
                        "timestamp": r.timestamp,
                    }
                    for r in results
                ],
                count=len(results),
                query=params.query,
            )
        except Exception as exc:
            return ToolResult.failed(
                f"Failed to execute internet search for '{params.query}': {exc}"
            )

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query or terms"},
                    "max_results": {
                        "type": "integer",
                        "description": "Max results (1-10)",
                        "default": 5,
                    },
                },
                "required": ["query"],
            },
            requires_approval=False,
        )


class InternetPageReadTool(BaseTool):
    """Web page text extraction tool."""

    name = "internet_page_read"
    description = (
        "Fetch and read the textual content of a web page URL. Extracts clean text, removes scripts and markup, "
        "and returns title, word count, and content."
    )
    category = PermissionCategory.READ_ONLY
    input_schema = InternetPageReadInput

    def __init__(self, service: InternetSearchService | None = None) -> None:
        super().__init__()
        self.service = service or InternetSearchService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Page read cancelled by user")

        assert isinstance(params, InternetPageReadInput)
        try:
            content = self.service.read_page_content(url=params.url, max_chars=params.max_chars)
            return ToolResult.success(
                data={
                    "url": content.url,
                    "title": content.title,
                    "text_content": content.text_content,
                    "word_count": content.word_count,
                    "truncated": content.content_truncated,
                    "timestamp": content.retrieval_timestamp,
                }
            )
        except Exception as exc:
            return ToolResult.failed(f"Failed to read web page at '{params.url}': {exc}")

    @classmethod
    def get_definition(cls) -> ToolDefinition:
        return ToolDefinition(
            name=cls.name,
            description=cls.description,
            category=cls.category,
            risk_level=RiskLevel.LOW,
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "HTTP or HTTPS URL to read"},
                    "max_chars": {
                        "type": "integer",
                        "description": "Max characters to extract",
                        "default": 4000,
                    },
                },
                "required": ["url"],
            },
            requires_approval=False,
        )
