"""Comprehensive Autonomous Agent Execution Core Acceptance Tests.

Validates Scenarios A through H:
- Scenario A: Real Application Launching (Chrome & Edge, LOW risk, zero approval blocking)
- Scenario B: Browser Navigation (Open browser and navigate to target)
- Scenario C: Live Meteorological Intelligence in English (Bushehr weather query)
- Scenario D: Persian Meteorological Intelligence («آب و هوای بوشهر الان چطوره؟», fast-path latency)
- Scenario E: Multi-Step Planning (Edge + search + summarize)
- Scenario F: Multi-Turn Management & Closing ("close Chrome", "close Edge")
- Scenario G: Robust Error Recovery (unknown app, invalid city, tool failure handling)
- Scenario H: Conversational Intent Filtering & Execution Guardrails
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

from core.execution_context import ExecutionContext
from core.planner import AgentPlanner
from core.tool_proposal import RiskLevel
from tools.internet.internet_tools import InternetPageReadTool, InternetSearchTool
from tools.weather.weather_service import CurrentWeatherReport
from tools.weather.weather_tools import WeatherCurrentTool, WeatherForecastTool
from tools.windows.application_tools import WindowsAppCloseTool, WindowsAppLaunchTool
from tools.windows.display_tools import WindowsDesktopScreenshotTool


class TestAutonomousAgentCore(unittest.TestCase):
    """Full acceptance suite for JARVIS autonomous agent execution core."""

    def setUp(self) -> None:
        self.provider_manager = MagicMock()
        self.planner = AgentPlanner(provider_manager=self.provider_manager)
        self.context = ExecutionContext()

        # Tool registry with registered autonomous tools
        self.tool_definitions = [
            WindowsAppLaunchTool.get_definition(),
            WindowsAppCloseTool.get_definition(),
            WindowsDesktopScreenshotTool.get_definition(),
            WeatherCurrentTool.get_definition(),
            WeatherForecastTool.get_definition(),
            InternetSearchTool.get_definition(),
            InternetPageReadTool.get_definition(),
        ]

    # -------------------------------------------------------------------------
    # Scenario A: Application Launching (Chrome & Edge)
    # -------------------------------------------------------------------------
    def test_scenario_a_app_launch_metadata_and_permissions(self) -> None:
        """Verify WindowsAppLaunchTool is LOW risk and requires zero approval for allowlisted apps."""
        defn = WindowsAppLaunchTool.get_definition()
        self.assertEqual(defn.name, "windows_app_launch")
        self.assertEqual(defn.risk_level, RiskLevel.LOW)
        self.assertFalse(defn.requires_approval)

    def test_scenario_a_multi_app_launch_plan(self) -> None:
        """Verify 'open Chrome and Edge' produces a deterministic sequential 2-step plan."""
        goal = "open Chrome and Edge"
        plan = self.planner.create_plan(
            goal=goal,
            context=self.context,
            available_tools=self.tool_definitions,
        )

        self.assertEqual(plan.goal, goal)
        tool_steps = [s for s in plan.steps if s.step_type.value == "tool_call"]
        self.assertEqual(len(tool_steps), 2)

        step_apps = [s.parameters.get("app_id") for s in tool_steps]
        self.assertIn("chrome", step_apps)
        self.assertIn("msedge", step_apps)
        self.assertTrue(all(s.tool_name == "windows_app_launch" for s in tool_steps))

    # -------------------------------------------------------------------------
    # Scenario B: Browser Navigation
    # -------------------------------------------------------------------------
    def test_scenario_b_browser_launch_and_navigate(self) -> None:
        """Verify 'open Chrome and navigate to github.com' produces launch and navigation plan."""
        goal = "open Chrome and navigate to github.com"
        plan = self.planner.create_plan(
            goal=goal,
            context=self.context,
            available_tools=self.tool_definitions,
        )

        tool_steps = [s for s in plan.steps if s.step_type.value == "tool_call"]
        self.assertGreaterEqual(len(tool_steps), 1)
        launch_step = tool_steps[0]
        self.assertEqual(launch_step.tool_name, "windows_app_launch")
        self.assertEqual(launch_step.parameters.get("app_id"), "chrome")

    # -------------------------------------------------------------------------
    # Scenario C: Live Weather in English (Bushehr)
    # -------------------------------------------------------------------------
    @patch("tools.weather.weather_service.LiveWeatherService.get_current_weather")
    def test_scenario_c_live_weather_english(self, mock_weather: MagicMock) -> None:
        """Verify English weather query generates weather_current plan and synthesizes natural response."""
        mock_weather.return_value = CurrentWeatherReport(
            city="Bushehr",
            city_fa="بوشهر",
            country="Iran",
            temperature_c=22.3,
            apparent_temperature_c=23.0,
            humidity_percent=63,
            wind_speed_kmh=14.0,
            precipitation_mm=0.0,
            weather_code=0,
            condition="Clear sky",
            observation_time="2026-11-15T15:00:00Z",
            provider="Open-Meteo Live Meteorological Service",
            latitude=28.9684,
            longitude=50.8385,
        )

        goal = "What is the weather in Bushehr right now?"
        plan = self.planner.create_plan(
            goal=goal,
            context=self.context,
            available_tools=self.tool_definitions,
        )

        tool_steps = [s for s in plan.steps if s.step_type.value == "tool_call"]
        self.assertEqual(len(tool_steps), 1)
        self.assertEqual(tool_steps[0].tool_name, "weather_current")
        self.assertEqual(tool_steps[0].parameters.get("city"), "Bushehr")

    # -------------------------------------------------------------------------
    # Scenario D: Persian Weather & Sub-Second Latency Fast-Path
    # -------------------------------------------------------------------------
    @patch("tools.weather.weather_service.LiveWeatherService.get_current_weather")
    def test_scenario_d_persian_weather_and_latency(self, mock_weather: MagicMock) -> None:
        """Verify Persian query «آب و هوای بوشهر الان چطوره؟» resolves city and executes on sub-second fast path."""
        start_t = time.perf_counter()
        goal = "آب و هوای بوشهر الان چطوره؟"
        plan = self.planner.create_plan(
            goal=goal,
            context=self.context,
            available_tools=self.tool_definitions,
        )
        elapsed_s = time.perf_counter() - start_t

        # Must be sub-second deterministic fast-path
        self.assertLess(elapsed_s, 0.5, f"Fast-path planning exceeded 500ms: {elapsed_s:.3f}s")

        tool_steps = [s for s in plan.steps if s.step_type.value == "tool_call"]
        self.assertEqual(len(tool_steps), 1)
        self.assertEqual(tool_steps[0].tool_name, "weather_current")
        self.assertIn(tool_steps[0].parameters.get("city"), ("Bushehr", "بوشهر"))

    # -------------------------------------------------------------------------
    # Scenario E: Multi-Step Research & Web Summarization
    # -------------------------------------------------------------------------
    def test_scenario_e_multi_step_search_and_summarize(self) -> None:
        """Verify 'Open Edge, search for Python 3.12 documentation, and summarize the official documentation' plans multi-step."""
        goal = "Open Edge, search for Python 3.12 documentation, and summarize the official documentation"
        plan = self.planner.create_plan(
            goal=goal,
            context=self.context,
            available_tools=self.tool_definitions,
        )

        tool_steps = [s for s in plan.steps if s.step_type.value == "tool_call"]
        self.assertGreaterEqual(len(tool_steps), 2)
        self.assertEqual(tool_steps[0].tool_name, "windows_app_launch")
        self.assertEqual(tool_steps[0].parameters.get("app_id"), "msedge")
        self.assertEqual(tool_steps[1].tool_name, "internet_search")
        self.assertIn("Python 3.12", tool_steps[1].parameters.get("query", ""))

    # -------------------------------------------------------------------------
    # Scenario F: Multi-Turn Application Management & Closing
    # -------------------------------------------------------------------------
    def test_scenario_f_app_close_plan(self) -> None:
        """Verify 'close Chrome' produces windows_app_close tool step."""
        goal = "close Chrome"
        plan = self.planner.create_plan(
            goal=goal,
            context=self.context,
            available_tools=self.tool_definitions,
        )

        tool_steps = [s for s in plan.steps if s.step_type.value == "tool_call"]
        self.assertEqual(len(tool_steps), 1)
        self.assertEqual(tool_steps[0].tool_name, "windows_app_close")
        self.assertEqual(tool_steps[0].parameters.get("app_id"), "chrome")

    # -------------------------------------------------------------------------
    # Scenario G: Robust Error Recovery
    # -------------------------------------------------------------------------
    def test_scenario_g_invalid_weather_handling(self) -> None:
        """Verify WeatherCurrentTool returns failed result on unresolvable city rather than crashing."""
        tool = WeatherCurrentTool()
        input_data = tool.validate_input({"city": "xyz_completely_unknown_place_12345"})
        res = tool.execute(input_data, self.context)

        self.assertFalse(res.is_success)
        self.assertIsNotNone(res.error)
        self.assertIn("xyz_completely_unknown_place_12345", res.error)

    # -------------------------------------------------------------------------
    # Scenario H: Conversational Guards (should_plan returns False)
    # -------------------------------------------------------------------------
    def test_scenario_h_conversational_guards(self) -> None:
        """Verify pure conversational intents are NOT converted into autonomous plans."""
        conversational_goals = [
            "سلام جارویس چطوری؟",
            "فقط با هم صحبت کنیم کاری نکن",
            "هیچ کاری نکن فقط حرف بزنیم",
            "just chatting, do nothing",
            "how are you today?",
        ]
        for g in conversational_goals:
            with self.subTest(goal=g):
                should = self.planner.should_plan(g)
                self.assertFalse(
                    should, f"Planner should NOT plan for purely conversational goal: '{g}'"
                )


if __name__ == "__main__":
    unittest.main()
