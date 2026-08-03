from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_current_time": {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current local date and time in Jakarta.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_location": {
        "type": "function",
        "function": {
            "name": "get_location",
            "description": "Get the configured physical location of this assistant.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_weather": {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather for a city. Use the configured location when no city is provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City or place name"}
                },
                "required": [],
            },
        },
    },
    "handle_exit_intent": {
        "type": "function",
        "function": {
            "name": "handle_exit_intent",
            "description": "Stop continuous conversation mode when the user asks to end or stop the conversation.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
}


WEATHER_DESCRIPTIONS: dict[int, str] = {
    0: "clear skies",
    1: "mostly clear skies",
    2: "partly cloudy conditions",
    3: "overcast conditions",
    45: "fog",
    48: "freezing fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "moderate rain",
    65: "heavy rain",
    71: "light snow",
    73: "moderate snow",
    75: "heavy snow",
    80: "light rain showers",
    81: "moderate rain showers",
    82: "heavy rain showers",
    95: "a thunderstorm",
    96: "a thunderstorm with light hail",
    99: "a thunderstorm with heavy hail",
}


class ToolService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def schemas(self, enabled: list[str]) -> list[dict[str, Any]]:
        return [TOOL_SCHEMAS[name] for name in enabled if name in TOOL_SCHEMAS]

    def format_result(self, name: str, result: dict[str, Any]) -> str:
        """Return a concise spoken fallback when a model emits no tool follow-up text."""
        if result.get("error"):
            return str(result["error"])
        if name == "get_current_time":
            spoken = result.get("spoken") or result.get("iso") or "the current time"
            timezone = result.get("timezone") or "the configured timezone"
            return f"It is currently {spoken} in the {timezone} timezone."
        if name == "get_location":
            location = result.get("location") or self.settings.default_location
            return f"We are currently in {location}."
        if name == "get_weather":
            location = result.get("location") or self.settings.default_location
            country = result.get("country") or ""
            place = f"{location}, {country}" if country else str(location)
            temperature = result.get("temperature_c")
            feels_like = result.get("feels_like_c")
            humidity = result.get("humidity_percent")
            wind = result.get("wind_kmh")
            code = result.get("weather_code")
            description = WEATHER_DESCRIPTIONS.get(code, "current weather conditions")
            parts = [f"The weather in {place} is {description}"]
            if temperature is not None:
                parts.append(f"with a temperature of {temperature} degrees Celsius")
            if feels_like is not None:
                parts.append(f"and it feels like {feels_like} degrees")
            sentence = " ".join(parts) + "."
            extras: list[str] = []
            if humidity is not None:
                extras.append(f"Humidity is {humidity} percent")
            if wind is not None:
                extras.append(f"wind speed is {wind} kilometers per hour")
            if extras:
                sentence += " " + ", and ".join(extras).capitalize() + "."
            return sentence
        if name == "handle_exit_intent":
            return str(result.get("message") or "Conversation mode will stop.")
        return str(result.get("message") or result)

    async def execute(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}
        if name == "get_current_time":
            now = datetime.now(ZoneInfo("Asia/Jakarta"))
            return {
                "timezone": "Asia/Jakarta",
                "iso": now.isoformat(timespec="seconds"),
                "spoken": now.strftime("%A, %B %d, %Y at %I:%M %p"),
            }
        if name == "get_location":
            return {"location": self.settings.default_location}
        if name == "get_weather":
            return await self._weather(str(arguments.get("location") or self.settings.default_location))
        if name == "handle_exit_intent":
            return {"conversation_should_stop": True, "message": "Conversation mode will stop."}
        return {"error": f"Unknown tool: {name}"}

    async def _weather(self, location: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                geo = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": location, "count": 1, "language": "en", "format": "json"},
                )
                geo.raise_for_status()
                results = geo.json().get("results") or []
                if not results:
                    return {"error": f"Location not found: {location}"}
                place = results[0]
                forecast = await client.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": place["latitude"],
                        "longitude": place["longitude"],
                        "current": "temperature_2m,apparent_temperature,weather_code,relative_humidity_2m,wind_speed_10m",
                        "timezone": "auto",
                    },
                )
                forecast.raise_for_status()
                current = forecast.json().get("current") or {}
                return {
                    "location": place.get("name", location),
                    "country": place.get("country", ""),
                    "temperature_c": current.get("temperature_2m"),
                    "feels_like_c": current.get("apparent_temperature"),
                    "humidity_percent": current.get("relative_humidity_2m"),
                    "wind_kmh": current.get("wind_speed_10m"),
                    "weather_code": current.get("weather_code"),
                }
        except Exception as exc:
            return {"error": f"Weather service unavailable: {exc}"}
