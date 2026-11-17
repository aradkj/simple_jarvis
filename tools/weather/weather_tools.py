"""Weather Tools for JARVIS Autonomous Agent.

Provides live weather and forecast capabilities backed by real meteorological services.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel, ToolDefinition
from tools.base import BaseTool, ToolResult
from tools.weather.weather_service import LiveWeatherService

if TYPE_CHECKING:
    from core.execution_context import ExecutionContext


class WeatherCurrentInput(BaseModel):
    """Input parameters for current weather retrieval."""

    city: str = Field(
        description="Name of the city (in English or Persian, e.g. 'Bushehr', 'بوشهر', 'Tehran', 'تهران')"
    )


class WeatherForecastInput(BaseModel):
    """Input parameters for weather forecast retrieval."""

    city: str = Field(description="Name of the city (in English or Persian)")
    days: int = Field(default=3, description="Number of forecast days (1 to 7)")


class WeatherCurrentTool(BaseTool):
    """Retrieve verified live meteorological observations for a specified city."""

    name = "weather_current"
    description = (
        "Retrieve live real-world weather observations (temperature, apparent temperature, humidity, "
        "wind speed, conditions, and observation timestamp) for any city in English or Persian (e.g. 'Bushehr', 'بوشهر')."
    )
    category = PermissionCategory.READ_ONLY
    input_schema = WeatherCurrentInput

    def __init__(self, service: LiveWeatherService | None = None) -> None:
        super().__init__()
        self.service = service or LiveWeatherService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Weather query cancelled by user")

        assert isinstance(params, WeatherCurrentInput)
        try:
            report = self.service.get_current_weather(params.city)
            return ToolResult.success(
                data=report.to_dict(),
                speech_summary_en=report.format_speech_en(),
                speech_summary_fa=report.format_speech_fa(),
                source=report.provider,
                timestamp=report.observation_time,
            )
        except Exception as exc:
            return ToolResult.failed(f"Failed to retrieve live weather for '{params.city}': {exc}")

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
                    "city": {
                        "type": "string",
                        "description": "Name of the city in English or Persian (e.g. 'Bushehr', 'بوشهر', 'Tehran', 'تهران')",
                    }
                },
                "required": ["city"],
            },
            requires_approval=False,
        )


class WeatherForecastTool(BaseTool):
    """Retrieve multi-day weather forecast for a specified city."""

    name = "weather_forecast"
    description = "Retrieve verified multi-day weather forecast (daily temperatures, precipitation, conditions) for a city."
    category = PermissionCategory.READ_ONLY
    input_schema = WeatherForecastInput

    def __init__(self, service: LiveWeatherService | None = None) -> None:
        super().__init__()
        self.service = service or LiveWeatherService()

    def execute(self, params: BaseModel, context: ExecutionContext) -> ToolResult:
        if context.is_cancelled():
            return ToolResult.cancelled("Forecast query cancelled by user")

        assert isinstance(params, WeatherForecastInput)
        try:
            res = self.service.get_forecast(params.city, days=params.days)
            return ToolResult.success(data=res)
        except Exception as exc:
            return ToolResult.failed(f"Failed to retrieve forecast for '{params.city}': {exc}")

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
                    "city": {"type": "string", "description": "City name in English or Persian"},
                    "days": {
                        "type": "integer",
                        "description": "Number of days (1 to 7)",
                        "default": 3,
                    },
                },
                "required": ["city"],
            },
            requires_approval=False,
        )
