from __future__ import annotations

import re
from typing import Any

import httpx

from app.plugins.base import BuiltinPlugin
from app.plugins.context import PluginContext
from app.plugins.matching import normalized_core
from app.plugins.result import PluginResult


WEATHER_DESCRIPTIONS: dict[int, str] = {
    0: "clear skies", 1: "mostly clear skies", 2: "partly cloudy conditions",
    3: "overcast conditions", 45: "fog", 48: "freezing fog",
    51: "light drizzle", 53: "moderate drizzle", 55: "heavy drizzle",
    61: "light rain", 63: "moderate rain", 65: "heavy rain",
    71: "light snow", 73: "moderate snow", 75: "heavy snow",
    80: "light rain showers", 81: "moderate rain showers",
    82: "heavy rain showers", 95: "a thunderstorm",
    96: "a thunderstorm with light hail", 99: "a thunderstorm with heavy hail",
}
WEATHER_DESCRIPTIONS_ID: dict[int, str] = {
    0: "cerah", 1: "sebagian besar cerah", 2: "berawan sebagian",
    3: "mendung", 45: "berkabut", 48: "kabut beku",
    51: "gerimis ringan", 53: "gerimis sedang", 55: "gerimis lebat",
    61: "hujan ringan", 63: "hujan sedang", 65: "hujan lebat",
    71: "salju ringan", 73: "salju sedang", 75: "salju lebat",
    80: "hujan lokal ringan", 81: "hujan lokal sedang",
    82: "hujan lokal lebat", 95: "badai petir",
    96: "badai petir dengan hujan es ringan", 99: "badai petir dengan hujan es lebat",
}



class WeatherPlugin(BuiltinPlugin):
    id = "get_weather"
    name = "Weather"
    description = "Returns live current weather using Open-Meteo."
    category = "Online information"
    permissions = ("internet",)
    priority = 30
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Get live current weather for a city. This tool MUST be used for current weather questions. Use the configured location when no city is provided.",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City or place name"}
                },
                "required": [],
            },
        },
    }
    _patterns = (
        r"^(?:what(?:'s| is) |how(?:'s| is) )?(?:the )?(?:current )?weather(?: today)?$",
        r"^(?:what(?:'s| is) )?(?:the )?weather like(?: today)?$",
        r"^(?:current )?weather forecast$",
        r"^(?:bagaimana )?cuaca(?: hari ini| sekarang)?$",
        r"^cuaca(?: hari ini| sekarang)? bagaimana$",
        r"^bagaimana cuaca(?: hari ini| sekarang)?$",
        r"^cuaca sekarang seperti apa$",
    )

    def match(self, context: PluginContext) -> dict[str, Any] | None:
        core = normalized_core(context.text)
        if any(re.fullmatch(pattern, core) for pattern in self._patterns):
            return {}
        city_match = re.fullmatch(
            r"(?:what(?:'s| is) |how(?:'s| is) )?(?:the )?(?:current )?weather(?: like)? in (.+)",
            core,
        )
        if city_match:
            return {"location": city_match.group(1).strip()}
        id_city_match = re.fullmatch(
            r"(?:bagaimana )?cuaca(?: hari ini| sekarang)? di (.+?)(?: hari ini| sekarang)?",
            core,
        )
        if not id_city_match:
            id_city_match = re.fullmatch(r"cuaca (.+?)(?: hari ini| sekarang)?", core)
        if id_city_match:
            location = id_city_match.group(1).strip()
            if location not in {"hari ini", "sekarang", "bagaimana"}:
                return {"location": location}
        return None

    async def execute(self, context: PluginContext) -> PluginResult:
        context.require_permission("internet")
        location = str(
            context.arguments.get("location") or context.settings.default_location
        )
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                geo = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": location, "count": 1, "language": "en", "format": "json"},
                )
                geo.raise_for_status()
                results = geo.json().get("results") or []
                if not results:
                    return PluginResult(data={"error": f"Location not found: {location}"})
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
                return PluginResult(data={
                    "location": place.get("name", location),
                    "country": place.get("country", ""),
                    "temperature_c": current.get("temperature_2m"),
                    "feels_like_c": current.get("apparent_temperature"),
                    "humidity_percent": current.get("relative_humidity_2m"),
                    "wind_kmh": current.get("wind_speed_10m"),
                    "weather_code": current.get("weather_code"),
                })
        except Exception as exc:
            return PluginResult(data={"error": f"Weather service unavailable: {exc}"})

    def format_result(self, result: dict[str, Any], context: PluginContext) -> str:
        if result.get("error"):
            return str(result["error"])
        language = str(context.metadata.get("language") or "en")
        location = result.get("location") or context.settings.default_location
        country = result.get("country") or ""
        place = f"{location}, {country}" if country else str(location)
        temperature = result.get("temperature_c")
        feels_like = result.get("feels_like_c")
        humidity = result.get("humidity_percent")
        wind = result.get("wind_kmh")
        if language == "id":
            description = WEATHER_DESCRIPTIONS_ID.get(
                result.get("weather_code"), "kondisi cuaca saat ini"
            )
            sentence = f"Cuaca di {place} saat ini {description}"
            if temperature is not None:
                sentence += f", dengan suhu {temperature} derajat Celsius"
            if feels_like is not None:
                sentence += f" dan terasa seperti {feels_like} derajat"
            sentence += "."
            extras: list[str] = []
            if humidity is not None:
                extras.append(f"Kelembapan {humidity} persen")
            if wind is not None:
                extras.append(f"kecepatan angin {wind} kilometer per jam")
            if extras:
                sentence += " " + ", dan ".join(extras).capitalize() + "."
            return sentence
        description = WEATHER_DESCRIPTIONS.get(
            result.get("weather_code"), "current weather conditions"
        )
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
