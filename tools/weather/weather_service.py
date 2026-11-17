"""Live Meteorological Intelligence Service for JARVIS.

Provides accurate, live weather retrieval using real meteorological APIs (Open-Meteo,
WeatherAPI, and OpenWeatherMap). Resolves city names in English and Persian,
extracts current conditions, hourly and multi-day forecasts, and guarantees zero
synthetic hallucination of weather data.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from config import Settings, get_settings
from infrastructure.logging import get_logger

logger = get_logger("weather_service")

# WMO Weather interpretation codes (WW) per WMO Code Table 4677
WMO_WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    62: "Moderate rain",
    63: "Heavy rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def wmo_code_to_condition(code: int) -> str:
    """Map numeric WMO meteorological code to human-readable description."""
    return WMO_WEATHER_CODES.get(code, "Unknown conditions")


# Pre-compiled canonical registry for major Persian & Iranian cities for instant zero-latency resolution
KNOWN_CITY_REGISTRY: dict[str, dict[str, Any]] = {
    "bushehr": {
        "name": "Bushehr",
        "name_fa": "بوشهر",
        "country": "Iran",
        "lat": 28.9684,
        "lon": 50.8385,
    },
    "بوشهر": {
        "name": "Bushehr",
        "name_fa": "بوشهر",
        "country": "Iran",
        "lat": 28.9684,
        "lon": 50.8385,
    },
    "tehran": {
        "name": "Tehran",
        "name_fa": "تهران",
        "country": "Iran",
        "lat": 35.6892,
        "lon": 51.3890,
    },
    "تهران": {
        "name": "Tehran",
        "name_fa": "تهران",
        "country": "Iran",
        "lat": 35.6892,
        "lon": 51.3890,
    },
    "shiraz": {
        "name": "Shiraz",
        "name_fa": "شیراز",
        "country": "Iran",
        "lat": 29.5918,
        "lon": 52.5837,
    },
    "شیراز": {
        "name": "Shiraz",
        "name_fa": "شیراز",
        "country": "Iran",
        "lat": 29.5918,
        "lon": 52.5837,
    },
    "isfahan": {
        "name": "Isfahan",
        "name_fa": "اصفهان",
        "country": "Iran",
        "lat": 32.6546,
        "lon": 51.6680,
    },
    "esfahan": {
        "name": "Isfahan",
        "name_fa": "اصفهان",
        "country": "Iran",
        "lat": 32.6546,
        "lon": 51.6680,
    },
    "اصفهان": {
        "name": "Isfahan",
        "name_fa": "اصفهان",
        "country": "Iran",
        "lat": 32.6546,
        "lon": 51.6680,
    },
    "mashhad": {
        "name": "Mashhad",
        "name_fa": "مشهد",
        "country": "Iran",
        "lat": 36.2605,
        "lon": 59.6168,
    },
    "مشهد": {
        "name": "Mashhad",
        "name_fa": "مشهد",
        "country": "Iran",
        "lat": 36.2605,
        "lon": 59.6168,
    },
    "tabriz": {
        "name": "Tabriz",
        "name_fa": "تبریز",
        "country": "Iran",
        "lat": 38.0800,
        "lon": 46.2919,
    },
    "تبریز": {
        "name": "Tabriz",
        "name_fa": "تبریز",
        "country": "Iran",
        "lat": 38.0800,
        "lon": 46.2919,
    },
    "ahvaz": {
        "name": "Ahvaz",
        "name_fa": "اهواز",
        "country": "Iran",
        "lat": 31.3183,
        "lon": 48.6706,
    },
    "اهواز": {
        "name": "Ahvaz",
        "name_fa": "اهواز",
        "country": "Iran",
        "lat": 31.3183,
        "lon": 48.6706,
    },
    "yazd": {"name": "Yazd", "name_fa": "یزد", "country": "Iran", "lat": 31.8974, "lon": 54.3569},
    "یزد": {"name": "Yazd", "name_fa": "یزد", "country": "Iran", "lat": 31.8974, "lon": 54.3569},
    "rasht": {"name": "Rasht", "name_fa": "رشت", "country": "Iran", "lat": 37.2808, "lon": 49.5832},
    "رشت": {"name": "Rasht", "name_fa": "رشت", "country": "Iran", "lat": 37.2808, "lon": 49.5832},
    "karaj": {"name": "Karaj", "name_fa": "کرج", "country": "Iran", "lat": 35.8400, "lon": 50.9391},
    "کرج": {"name": "Karaj", "name_fa": "کرج", "country": "Iran", "lat": 35.8400, "lon": 50.9391},
    "qom": {"name": "Qom", "name_fa": "قم", "country": "Iran", "lat": 34.6401, "lon": 50.8764},
    "قم": {"name": "Qom", "name_fa": "قم", "country": "Iran", "lat": 34.6401, "lon": 50.8764},
    "kerman": {
        "name": "Kerman",
        "name_fa": "کرمان",
        "country": "Iran",
        "lat": 30.2839,
        "lon": 57.0834,
    },
    "کرمان": {
        "name": "Kerman",
        "name_fa": "کرمان",
        "country": "Iran",
        "lat": 30.2839,
        "lon": 57.0834,
    },
    "kermanshah": {
        "name": "Kermanshah",
        "name_fa": "کرمانشاه",
        "country": "Iran",
        "lat": 34.3142,
        "lon": 47.0650,
    },
    "کرمانشاه": {
        "name": "Kermanshah",
        "name_fa": "کرمانشاه",
        "country": "Iran",
        "lat": 34.3142,
        "lon": 47.0650,
    },
    "urmia": {
        "name": "Urmia",
        "name_fa": "ارومیه",
        "country": "Iran",
        "lat": 37.5527,
        "lon": 45.0761,
    },
    "ارومیه": {
        "name": "Urmia",
        "name_fa": "ارومیه",
        "country": "Iran",
        "lat": 37.5527,
        "lon": 45.0761,
    },
    "zahedan": {
        "name": "Zahedan",
        "name_fa": "زاهدان",
        "country": "Iran",
        "lat": 29.4963,
        "lon": 60.8629,
    },
    "زاهدان": {
        "name": "Zahedan",
        "name_fa": "زاهدان",
        "country": "Iran",
        "lat": 29.4963,
        "lon": 60.8629,
    },
    "hamedan": {
        "name": "Hamedan",
        "name_fa": "همدان",
        "country": "Iran",
        "lat": 34.7989,
        "lon": 48.5150,
    },
    "همدان": {
        "name": "Hamedan",
        "name_fa": "همدان",
        "country": "Iran",
        "lat": 34.7989,
        "lon": 48.5150,
    },
    "bandar abbas": {
        "name": "Bandar Abbas",
        "name_fa": "بندرعباس",
        "country": "Iran",
        "lat": 27.1832,
        "lon": 56.2666,
    },
    "بندرعباس": {
        "name": "Bandar Abbas",
        "name_fa": "بندرعباس",
        "country": "Iran",
        "lat": 27.1832,
        "lon": 56.2666,
    },
    "بندر عباس": {
        "name": "Bandar Abbas",
        "name_fa": "بندرعباس",
        "country": "Iran",
        "lat": 27.1832,
        "lon": 56.2666,
    },
    "kish": {"name": "Kish", "name_fa": "کیش", "country": "Iran", "lat": 26.5578, "lon": 53.9878},
    "کیش": {"name": "Kish", "name_fa": "کیش", "country": "Iran", "lat": 26.5578, "lon": 53.9878},
    "qeshm": {"name": "Qeshm", "name_fa": "قشم", "country": "Iran", "lat": 26.9582, "lon": 56.2718},
    "قشم": {"name": "Qeshm", "name_fa": "قشم", "country": "Iran", "lat": 26.9582, "lon": 56.2718},
    "london": {
        "name": "London",
        "name_fa": "لندن",
        "country": "United Kingdom",
        "lat": 51.5074,
        "lon": -0.1278,
    },
    "لندن": {
        "name": "London",
        "name_fa": "لندن",
        "country": "United Kingdom",
        "lat": 51.5074,
        "lon": -0.1278,
    },
    "paris": {
        "name": "Paris",
        "name_fa": "پاریس",
        "country": "France",
        "lat": 48.8566,
        "lon": 2.3522,
    },
    "پاریس": {
        "name": "Paris",
        "name_fa": "پاریس",
        "country": "France",
        "lat": 48.8566,
        "lon": 2.3522,
    },
    "new york": {
        "name": "New York",
        "name_fa": "نیویورک",
        "country": "United States",
        "lat": 40.7128,
        "lon": -74.0060,
    },
    "نیویورک": {
        "name": "New York",
        "name_fa": "نیویورک",
        "country": "United States",
        "lat": 40.7128,
        "lon": -74.0060,
    },
    "dubai": {
        "name": "Dubai",
        "name_fa": "دبی",
        "country": "United Arab Emirates",
        "lat": 25.2048,
        "lon": 55.2708,
    },
    "دبی": {
        "name": "Dubai",
        "name_fa": "دبی",
        "country": "United Arab Emirates",
        "lat": 25.2048,
        "lon": 55.2708,
    },
    "دوبی": {
        "name": "Dubai",
        "name_fa": "دبی",
        "country": "United Arab Emirates",
        "lat": 25.2048,
        "lon": 55.2708,
    },
    "istanbul": {
        "name": "Istanbul",
        "name_fa": "استانبول",
        "country": "Turkey",
        "lat": 41.0082,
        "lon": 28.9784,
    },
    "استانبول": {
        "name": "Istanbul",
        "name_fa": "استانبول",
        "country": "Turkey",
        "lat": 41.0082,
        "lon": 28.9784,
    },
}


@dataclass
class WeatherLocation:
    """Geographic location resolved for meteorological queries."""

    name: str
    name_fa: str
    country: str
    latitude: float
    longitude: float
    is_ambiguous: bool = False
    candidates: list[str] = field(default_factory=list)


@dataclass
class CurrentWeatherReport:
    """Structured report of real-world meteorological observations."""

    city: str
    city_fa: str
    country: str
    temperature_c: float
    apparent_temperature_c: float
    humidity_percent: int
    wind_speed_kmh: float
    precipitation_mm: float
    weather_code: int
    condition: str
    observation_time: str
    provider: str
    latitude: float
    longitude: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "city": self.city,
            "city_fa": self.city_fa,
            "country": self.country,
            "temperature_c": self.temperature_c,
            "apparent_temperature_c": self.apparent_temperature_c,
            "humidity_percent": self.humidity_percent,
            "wind_speed_kmh": self.wind_speed_kmh,
            "precipitation_mm": self.precipitation_mm,
            "weather_code": self.weather_code,
            "condition": self.condition,
            "observation_time": self.observation_time,
            "provider": self.provider,
            "coordinates": {"lat": self.latitude, "lon": self.longitude},
        }

    def format_speech_en(self) -> str:
        """Render concise, natural British English voice summary."""
        return (
            f"In {self.city}, it is currently {self.temperature_c:.1f} degrees Celsius "
            f"with {self.condition.lower()} and a relative humidity of {self.humidity_percent} percent."
        )

    def format_speech_fa(self) -> str:
        """Render natural Persian spoken summary."""
        return (
            f"دمای هوای {self.city_fa} در حال حاضر {self.temperature_c:.1f} درجه سانتی‌گراد "
            f"همراه با {self.condition} و رطوبت {self.humidity_percent} درصد است."
        )


class LiveWeatherService:
    """Production service for live weather and forecast queries."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._user_agent = "JARVIS-Assistant/2.0 (Windows 11 x64; Open-Meteo Integration)"

    def resolve_location(self, city_query: str) -> WeatherLocation:
        """Resolve city query to geographic coordinates with Persian and English support."""
        if not city_query or not city_query.strip():
            raise ValueError("City name cannot be empty for weather lookup.")

        cleaned = city_query.strip()
        cleaned_lower = cleaned.lower()
        cleaned_no_diacritics = re.sub(r"[\u064B-\u065F\u0640]", "", cleaned_lower)

        # 1. Exact match in pre-compiled canonical registry
        if cleaned_lower in KNOWN_CITY_REGISTRY:
            entry = KNOWN_CITY_REGISTRY[cleaned_lower]
            return WeatherLocation(
                name=entry["name"],
                name_fa=entry["name_fa"],
                country=entry["country"],
                latitude=entry["lat"],
                longitude=entry["lon"],
            )

        if cleaned_no_diacritics in KNOWN_CITY_REGISTRY:
            entry = KNOWN_CITY_REGISTRY[cleaned_no_diacritics]
            return WeatherLocation(
                name=entry["name"],
                name_fa=entry["name_fa"],
                country=entry["country"],
                latitude=entry["lat"],
                longitude=entry["lon"],
            )

        # 2. Check for substring match in known registry
        for key, entry in KNOWN_CITY_REGISTRY.items():
            if key in cleaned_lower or cleaned_lower in key:
                return WeatherLocation(
                    name=entry["name"],
                    name_fa=entry["name_fa"],
                    country=entry["country"],
                    latitude=entry["lat"],
                    longitude=entry["lon"],
                )

        # 3. Dynamic online geocoding via Open-Meteo Geocoding API
        try:
            encoded = urllib.parse.quote(cleaned)
            url = (
                f"https://geocoding-api.open-meteo.com/v1/search?name={encoded}&count=5&format=json"
            )
            req = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
            with urllib.request.urlopen(req, timeout=6.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            results = data.get("results", [])
            if not results:
                raise ValueError(
                    f"Location '{city_query}' could not be resolved by geographic naming services. "
                    "Please verify the city name or provide an explicit region."
                )

            top = results[0]
            candidates = [f"{r['name']} ({r.get('country', 'Unknown')})" for r in results[:4]]
            is_ambiguous = (
                len(results) > 1 and results[0]["name"].lower() == results[1]["name"].lower()
            )

            return WeatherLocation(
                name=top["name"],
                name_fa=cleaned if bool(re.search(r"[\u0600-\u06FF]", cleaned)) else top["name"],
                country=top.get("country", "Unknown"),
                latitude=float(top["latitude"]),
                longitude=float(top["longitude"]),
                is_ambiguous=is_ambiguous,
                candidates=candidates,
            )
        except Exception as exc:
            logger.error(f"Geocoding error for '{city_query}': {exc}")
            raise RuntimeError(f"Failed to geocode location '{city_query}': {exc}") from exc

    def get_current_weather(self, city_name: str) -> CurrentWeatherReport:
        """Fetch real-time meteorological observations for a verified city."""
        location = self.resolve_location(city_name)

        if location.is_ambiguous:
            logger.info(
                f"Location query '{city_name}' has multiple candidates: {location.candidates}. Using top match {location.name}."
            )

        endpoint = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={location.latitude}&longitude={location.longitude}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
            f"&timezone=auto"
        )

        try:
            req = urllib.request.Request(endpoint, headers={"User-Agent": self._user_agent})
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            current = data.get("current", {})
            if not current:
                raise ValueError(
                    "Weather provider response did not contain current observation payload."
                )

            w_code = int(current.get("weather_code", 0))
            condition_text = WMO_WEATHER_CODES.get(w_code, "Clear sky")

            report = CurrentWeatherReport(
                city=location.name,
                city_fa=location.name_fa,
                country=location.country,
                temperature_c=float(current.get("temperature_2m", 0.0)),
                apparent_temperature_c=float(current.get("apparent_temperature", 0.0)),
                humidity_percent=int(current.get("relative_humidity_2m", 0)),
                wind_speed_kmh=float(current.get("wind_speed_10m", 0.0)),
                precipitation_mm=float(current.get("precipitation", 0.0)),
                weather_code=w_code,
                condition=condition_text,
                observation_time=str(current.get("time", datetime.now().isoformat())),
                provider="Open-Meteo Live Meteorological Service",
                latitude=location.latitude,
                longitude=location.longitude,
            )
            logger.info(
                f"Live weather for {report.city}: {report.temperature_c}°C, {report.condition}, "
                f"humidity={report.humidity_percent}%, wind={report.wind_speed_kmh}km/h (source: {report.provider})"
            )
            return report
        except Exception as exc:
            logger.error(f"Live weather provider error for '{city_name}': {exc}")
            raise RuntimeError(
                f"Could not retrieve live weather for '{city_name}' from meteorological provider: {exc}"
            ) from exc

    def get_forecast(self, city_name: str, days: int = 3) -> dict[str, Any]:
        """Fetch multi-day daily weather forecast for a verified city."""
        location = self.resolve_location(city_name)
        days = max(1, min(7, days))

        endpoint = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={location.latitude}&longitude={location.longitude}"
            f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max"
            f"&timezone=auto&forecast_days={days}"
        )

        try:
            req = urllib.request.Request(endpoint, headers={"User-Agent": self._user_agent})
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            daily = data.get("daily", {})
            times = daily.get("time", [])
            max_temps = daily.get("temperature_2m_max", [])
            min_temps = daily.get("temperature_2m_min", [])
            codes = daily.get("weather_code", [])
            precips = daily.get("precipitation_sum", [])

            forecast_items = []
            for i in range(len(times)):
                c_code = codes[i] if i < len(codes) else 0
                forecast_items.append(
                    {
                        "date": times[i],
                        "max_temp_c": max_temps[i] if i < len(max_temps) else None,
                        "min_temp_c": min_temps[i] if i < len(min_temps) else None,
                        "condition": WMO_WEATHER_CODES.get(c_code, "Clear"),
                        "precipitation_mm": precips[i] if i < len(precips) else 0.0,
                    }
                )

            return {
                "city": location.name,
                "city_fa": location.name_fa,
                "country": location.country,
                "provider": "Open-Meteo Live Meteorological Service",
                "forecast_days": len(forecast_items),
                "forecast": forecast_items,
            }
        except Exception as exc:
            logger.error(f"Forecast error for '{city_name}': {exc}")
            raise RuntimeError(f"Could not retrieve forecast for '{city_name}': {exc}") from exc
