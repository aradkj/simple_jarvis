"""End-to-End Chat Certification test suite for Phase 7 Browser Agent capabilities."""

from collections.abc import Generator
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from ai.base import AIResponse
from ai.manager import ProviderManager
from config import Settings
from core.agent import JARVISAgent
from core.planner import StepType
from memory.database import SQLiteMemoryStore
from tools.browser.models import SearchResult, SearchResultItem


@pytest.fixture
def test_agent_with_browser(tmp_path) -> Generator[JARVISAgent, None, None]:
    """Provide a real JARVISAgent configured with browser capabilities and mock AI provider."""
    settings = Settings(
        app_env="testing",
        gemini_api_key=SecretStr("AIzaMockKeyForTesting1234"),
        data_dir=tmp_path / "data",
        logs_dir=tmp_path / "logs",
        browser_enabled=True,
        browser_headless=True,
        browser_allow_localhost=True,
    )
    store = SQLiteMemoryStore(db_path=tmp_path / "test_memory.db")
    store.initialize()

    mock_provider = MagicMock(spec=ProviderManager)
    mock_provider.is_ready.return_value = True
    mock_provider.default_model = "gemini-3.5-flash-lite"
    mock_provider.provider_name = "MockGemini"
    mock_provider.generate_text.return_value = AIResponse(
        text="صفحه وب مورد نظر باز شد و محتوای آن آماده است.",
        provider_id="gemini",
        model="gemini-3.5-flash-lite",
    )

    agent = JARVISAgent(
        settings=settings,
        memory_store=store,
        ai_provider=mock_provider,
    )
    yield agent
    agent.shutdown()


class TestBrowserEndToEndCertification:
    """Verifies end-to-end intent recognition, plan formulation, tool routing, and truthful reporting."""

    # --- 1. Persian and English Intent Recognition ---

    def test_persian_navigate_intent_recognition(
        self, test_agent_with_browser: JARVISAgent
    ) -> None:
        """Verify: «سایت گوگل رو باز کن» maps to browser_navigate with google URL."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="سایت گوگل رو باز کن",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_navigate"
        assert "google.com" in tool_steps[0].parameters.get("url", "")

    def test_english_navigate_intent_recognition(
        self, test_agent_with_browser: JARVISAgent
    ) -> None:
        """Verify: 'Navigate to https://fastapi.tiangolo.com' maps to browser_navigate."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="Navigate to https://fastapi.tiangolo.com",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_navigate"
        assert tool_steps[0].parameters.get("url") == "https://fastapi.tiangolo.com"

    def test_persian_search_intent_recognition(self, test_agent_with_browser: JARVISAgent) -> None:
        """Verify: «در اینترنت درباره FastAPI جستجو کن» maps to browser_search."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="در اینترنت درباره FastAPI جستجو کن",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_search"
        assert "FastAPI" in tool_steps[0].parameters.get("query", "")

    def test_english_search_intent_recognition(self, test_agent_with_browser: JARVISAgent) -> None:
        """Verify: 'Search the web for Python 3.12 release notes' maps to browser_search."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="Search the web for Python 3.12 release notes",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_search"
        assert "Python 3.12" in tool_steps[0].parameters.get("query", "")

    def test_persian_screenshot_intent_recognition(
        self, test_agent_with_browser: JARVISAgent
    ) -> None:
        """Verify: «از صفحه اسکرینشات بگیر» maps to browser_screenshot."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="از صفحه اسکرینشات بگیر",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_screenshot"

    def test_english_screenshot_intent_recognition(
        self, test_agent_with_browser: JARVISAgent
    ) -> None:
        """Verify: 'Take a screenshot' maps to browser_screenshot."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="Take a screenshot",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_screenshot"

    def test_persian_tab_new_intent_recognition(self, test_agent_with_browser: JARVISAgent) -> None:
        """Verify: «یک تب جدید باز کن» maps to browser_tab_new."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="یک تب جدید باز کن",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_tab_new"

    def test_persian_page_content_intent_recognition(
        self, test_agent_with_browser: JARVISAgent
    ) -> None:
        """Verify: «محتوای این صفحه رو خلاصه کن» maps to browser_get_page_content."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="محتوای این صفحه رو خلاصه کن",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_get_page_content"

    def test_english_headings_intent_recognition(
        self, test_agent_with_browser: JARVISAgent
    ) -> None:
        """Verify: 'Show the page headings' maps to browser_get_headings."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="Show the page headings",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_get_headings"

    def test_persian_links_intent_recognition(self, test_agent_with_browser: JARVISAgent) -> None:
        """Verify: «لینک‌های این صفحه رو استخراج کن» maps to browser_get_links."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="لینک‌های این صفحه رو استخراج کن",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_get_links"

    def test_persian_scroll_intent_recognition(self, test_agent_with_browser: JARVISAgent) -> None:
        """Verify: «صفحه رو اسکرول کن» maps to browser_scroll."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="صفحه رو اسکرول کن",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_scroll"

    def test_english_tab_close_intent_recognition(
        self, test_agent_with_browser: JARVISAgent
    ) -> None:
        """Verify: 'Close this tab' maps to browser_tab_close."""
        plan = test_agent_with_browser.planner.create_plan(
            goal="Close this tab",
            context=test_agent_with_browser._current_context,
            available_tools=[
                t.get_definition()
                for t in test_agent_with_browser.tool_registry.list_tools()
                if hasattr(t, "get_definition")
            ],
        )
        tool_steps = [s for s in plan.steps if s.step_type == StepType.TOOL_CALL]
        assert len(tool_steps) >= 1
        assert tool_steps[0].tool_name == "browser_tab_close"

    # --- 2. End-to-End Execution Flow ---

    def test_end_to_end_search_task_execution(self, test_agent_with_browser: JARVISAgent) -> None:
        """Verify end-to-end execution of a web search query."""
        # Mock browser_service.search_web to return deterministic result
        test_agent_with_browser.browser_service.search_web = MagicMock(
            return_value=SearchResult(
                query="FastAPI tutorial",
                results=[
                    SearchResultItem(
                        title="FastAPI Tutorial",
                        url="https://fastapi.tiangolo.com/tutorial/",
                        snippet="A comprehensive guide to FastAPI.",
                    )
                ],
                total_found=1,
            )
        )

        outcome = test_agent_with_browser.process_agent_task(
            goal="Search the web for FastAPI tutorial"
        )
        assert outcome.status == "completed"
        test_agent_with_browser.browser_service.search_web.assert_called_once()
        assert len(outcome.final_response) > 0

    def test_end_to_end_navigation_security_blocking(
        self, test_agent_with_browser: JARVISAgent
    ) -> None:
        """Verify end-to-end security blocking of forbidden file:// target without crash."""
        outcome = test_agent_with_browser.process_agent_task(goal="Open file:///etc/shadow")
        # Tool execution must have failed due to URLValidationError, and result must state failure truthfully
        assert outcome.status in ("completed", "partial", "failed")
        assert any(
            marker in (outcome.final_response or outcome.error or "").lower()
            for marker in (
                "blocked",
                "error",
                "failed",
                "متأسفانه",
                "انجام نشد",
                "forbidden",
                "unable",
                "unsupported",
            )
        )
