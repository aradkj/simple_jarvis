"""Unit and integration tests for LiveWeatherService and weather tools."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from core.permissions import PermissionCategory
from core.tool_proposal import RiskLevel
from tools.weather.weather_service import (
    CurrentWeatherReport,
    LiveWeatherService,
    wmo_code_to_condition,
)
from tools.weather.weather_tools import (
    WeatherCurrentInput,
    WeatherCurrentTool,
    WeatherForecastTool,
)


class TestLiveWeatherService(unittest.TestCase):
    """Test suite for LiveWeatherService registry, geocoding, and observations."""

    def setUp(self) -> None:
        self.service = LiveWeatherService()

    def test_known_city_registry_coverage(self) -> None:
        """Verify registry contains major Iranian and global cities in Persian and English."""
        test_cities = [
            ("bushehr", "Bushehr"),
            ("بوشهر", "Bushehr"),
            ("tehran", "Tehran"),
            ("تهران", "Tehran"),
            ("shiraz", "Shiraz"),
            ("شیراز", "Shiraz"),
            ("isfahan", "Isfahan"),
            ("اصفهان", "Isfahan"),
            ("mashhad", "Mashhad"),
            ("مشهد", "Mashhad"),
            ("tabriz", "Tabriz"),
            ("تبریز", "Tabriz"),
            ("ahvaz", "Ahvaz"),
            ("اهواز", "Ahvaz"),
            ("rasht", "Rasht"),
            ("رشت", "Rasht"),
            ("london", "London"),
            ("لندن", "London"),
            ("paris", "Paris"),
            ("پاریس", "Paris"),
            ("new york", "New York"),
            ("نیویورک", "New York"),
            ("dubai", "Dubai"),
            ("دبی", "Dubai"),
            ("istanbul", "Istanbul"),
            ("استانبول", "Istanbul"),
        ]
        for query, expected_name in test_cities:
            with self.subTest(query=query):
                loc = self.service.resolve_location(query)
                self.assertIsNotNone(loc, f"Failed to resolve city query '{query}'")
                self.assertEqual(loc.name, expected_name)
                self.assertIsInstance(loc.latitude, float)
                self.assertIsInstance(loc.longitude, float)

    def test_wmo_code_mapping(self) -> None:
        """Verify WMO meteorological code mapping covers key conditions."""
        self.assertEqual(wmo_code_to_condition(0), "Clear sky")
        self.assertEqual(wmo_code_to_condition(1), "Mainly clear")
        self.assertEqual(wmo_code_to_condition(2), "Partly cloudy")
        self.assertEqual(wmo_code_to_condition(3), "Overcast")
        self.assertEqual(wmo_code_to_condition(45), "Fog")
        self.assertEqual(wmo_code_to_condition(61), "Slight rain")
        self.assertEqual(wmo_code_to_condition(65), "Heavy rain")
        self.assertEqual(wmo_code_to_condition(95), "Thunderstorm")
        self.assertEqual(wmo_code_to_condition(999), "Unknown conditions")

    @patch("urllib.request.urlopen")
    def test_get_current_weather_mocked(self, mock_urlopen: MagicMock) -> None:
        """Test current weather retrieval using mock HTTP response."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"""{
            "latitude": 28.9684,
            "longitude": 50.8385,
            "elevation": 10.0,
            "current": {
                "time": "2026-11-15T14:30",
                "interval": 900,
                "temperature_2m": 22.4,
                "relative_humidity_2m": 64,
                "apparent_temperature": 23.1,
                "weather_code": 0,
                "wind_speed_10m": 12.5,
                "wind_direction_10m": 180,
                "surface_pressure": 1014.2,
                "precipitation": 0.0
            }
        }"""
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        obs = self.service.get_current_weather("بوشهر")
        self.assertIsInstance(obs, CurrentWeatherReport)
        self.assertEqual(obs.city, "Bushehr")
        self.assertEqual(obs.temperature_c, 22.4)
        self.assertEqual(obs.humidity_percent, 64)
        self.assertEqual(obs.apparent_temperature_c, 23.1)
        self.assertEqual(obs.weather_code, 0)
        self.assertEqual(obs.condition, "Clear sky")
        self.assertEqual(obs.wind_speed_kmh, 12.5)
        self.assertIn("Open-Meteo", obs.provider)

    @patch("urllib.request.urlopen")
    def test_get_forecast_mocked(self, mock_urlopen: MagicMock) -> None:
        """Test multi-day forecast retrieval using mock HTTP response."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"""{
            "latitude": 35.6944,
            "longitude": 51.4215,
            "daily": {
                "time": ["2026-11-15", "2026-11-16", "2026-11-17"],
                "weather_code": [0, 2, 61],
                "temperature_2m_max": [18.2, 16.5, 14.0],
                "temperature_2m_min": [8.1, 7.0, 5.5],
                "precipitation_sum": [0, 0.2, 4.5],
                "wind_speed_10m_max": [10.2, 14.1, 19.5]
            }
        }"""
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        forecast = self.service.get_forecast("تهران", days=3)
        self.assertIsInstance(forecast, dict)
        self.assertEqual(forecast["city"], "Tehran")
        self.assertEqual(forecast["forecast_days"], 3)
        day1 = forecast["forecast"][0]
        self.assertEqual(day1["date"], "2026-11-15")
        self.assertEqual(day1["max_temp_c"], 18.2)
        self.assertEqual(day1["min_temp_c"], 8.1)
        self.assertEqual(day1["condition"], "Clear sky")


class TestWeatherTools(unittest.TestCase):
    """Test suite for WeatherCurrentTool and WeatherForecastTool."""

    def setUp(self) -> None:
        self.current_tool = WeatherCurrentTool()
        self.forecast_tool = WeatherForecastTool()
        self.mock_context = MagicMock()
        self.mock_context.is_cancelled.return_value = False

    def test_tool_metadata(self) -> None:
        """Verify tool metadata, risk level, and schema."""
        self.assertEqual(self.current_tool.name, "weather_current")
        self.assertEqual(self.current_tool.category, PermissionCategory.READ_ONLY)
        def_current = self.current_tool.get_definition()
        self.assertEqual(def_current.risk_level, RiskLevel.LOW)
        self.assertFalse(def_current.requires_approval)

        self.assertEqual(self.forecast_tool.name, "weather_forecast")
        self.assertEqual(self.forecast_tool.category, PermissionCategory.READ_ONLY)
        def_forecast = self.forecast_tool.get_definition()
        self.assertEqual(def_forecast.risk_level, RiskLevel.LOW)
        self.assertFalse(def_forecast.requires_approval)

    @patch("tools.weather.weather_service.LiveWeatherService.get_current_weather")
    def test_current_tool_execution(self, mock_get_current: MagicMock) -> None:
        """Test WeatherCurrentTool execution returns structured data."""
        mock_get_current.return_value = CurrentWeatherReport(
            city="Bushehr",
            city_fa="بوشهر",
            country="Iran",
            temperature_c=22.4,
            apparent_temperature_c=23.1,
            humidity_percent=64,
            wind_speed_kmh=12.5,
            precipitation_mm=0.0,
            weather_code=0,
            condition="Clear sky",
            observation_time="2026-11-15T14:30:00Z",
            provider="Open-Meteo Live Meteorological Service",
            latitude=28.9684,
            longitude=50.8385,
        )

        params = WeatherCurrentInput(city="بوشهر")
        res = self.current_tool.execute(params, self.mock_context)
        self.assertTrue(res.is_success)
        self.assertEqual(res.data["city"], "Bushehr")
        self.assertEqual(res.data["temperature_c"], 22.4)
        self.assertEqual(res.data["condition"], "Clear sky")
        self.assertEqual(res.data["humidity_percent"], 64)


if __name__ == "__main__":
    unittest.main()
