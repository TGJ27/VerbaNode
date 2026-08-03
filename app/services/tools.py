from __future__ import annotations

from datetime import datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from app.config import Settings


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_current_time": {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the exact current local date and time in the configured timezone. This tool MUST be used for every current time or date question; never estimate the answer.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_location": {
        "type": "function",
        "function": {
            "name": "get_location",
            "description": "Get the configured physical location of this assistant. This tool MUST be used when the user asks where the robot or 'we' are.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    "get_weather": {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get live current weather for a city. This tool MUST be used for current weather questions. Use the configured location when no city is provided.",
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

    @staticmethod
    def _normalized_text(text: str) -> str:
        text = text.casefold().replace("’", "'")
        text = re.sub(r"[^\w\s'?-]", " ", text, flags=re.UNICODE)
        return re.sub(r"\s+", " ", text).strip(" ?-")

    @staticmethod
    def _strip_conversational_wrappers(text: str) -> str:
        """Remove harmless greetings, wake words, and politeness wrappers.

        Voice input commonly reaches the router as phrases such as
        "hello Ropi, what time is it?".  These wrappers must not force a
        live-data request back through the LLM, but they also must not alter
        the meaningful middle of a sentence.
        """
        value = text.strip()
        leading_patterns = (
            r"^(?:hello|hi|hey|yo|halo|hai)\b\s*",
            r"^good (?:morning|afternoon|evening)\b\s*",
            r"^(?:excuse me|permisi)\b\s*",
            r"^(?:ropi|assistant)\b\s*",
            r"^(?:please|pls|tolong)\b\s*",
        )
        # Repeat because users often combine several wrappers, for example
        # "hello Ropi please ...".
        changed = True
        while changed and value:
            changed = False
            for pattern in leading_patterns:
                updated = re.sub(pattern, "", value, count=1).strip()
                if updated != value:
                    value = updated
                    changed = True
                    break

        trailing_patterns = (
            r"\s+(?:please|pls|tolong)$",
            r"\s+(?:thanks|thank you|makasih|terima kasih)$",
            r"\s+(?:for me|right now|now please)$",
        )
        changed = True
        while changed and value:
            changed = False
            for pattern in trailing_patterns:
                updated = re.sub(pattern, "", value, count=1).strip()
                if updated != value:
                    value = updated
                    changed = True
                    break
        return value

    @staticmethod
    def _tokens_fit(text: str, *, required: set[str], allowed: set[str]) -> bool:
        tokens = [token.replace("'", "") for token in text.split() if token]
        token_set = set(tokens)
        return bool(tokens) and required.issubset(token_set) and token_set.issubset(allowed)

    def match_core_intent(
        self, text: str, enabled: list[str]
    ) -> tuple[str, dict[str, Any]] | None:
        """Route unambiguous built-in requests without relying on a small LLM.

        The matcher is intentionally conservative so normal questions such as
        "What is time complexity?" continue to reach the language model.
        """
        normalized = self._normalized_text(text)
        core = self._strip_conversational_wrappers(normalized)
        enabled_set = set(enabled or [])

        time_exclusions = (
            "time complexity",
            "runtime complexity",
            "response time",
            "processing time",
            "travel time",
            "arrival time",
            "departure time",
            "meeting time",
            "time zone",
            "timezone",
        )
        time_patterns = (
            r"^what time is it(?: now| right now)?$",
            r"^do you know what time it is(?: now| right now)?$",
            r"^(?:what(?:'s| is) )?(?:the )?(?:current |local |exact )?time(?: now)?$",
            r"^(?:can you |could you |would you )?(?:please )?(?:tell|give) me (?:the )?(?:current |local |exact )?time(?: now)?$",
            r"^(?:what(?:'s| is) )?(?:today'?s |the current )?date(?: today)?$",
            r"^(?:what day is it|what date is it|what day is today|what date is today|today'?s date)$",
            r"^(?:sekarang )?jam berapa(?: sekarang)?$",
            r"^(?:sekarang )?pukul berapa(?: sekarang)?$",
            r"^(?:hari ini )?(?:hari apa|tanggal berapa)$",
        )
        fuzzy_time_allowed = {
            "what", "whats", "is", "it", "its", "the", "current", "local",
            "exact", "time", "now", "right", "can", "could", "would", "you",
            "please", "tell", "give", "me", "do", "know", "today",
        }
        fuzzy_date_allowed = {
            "what", "whats", "is", "it", "its", "the", "current", "day",
            "date", "today", "todays", "can", "could", "would", "you", "please",
            "tell", "give", "me", "do", "know",
        }
        is_time_or_date = any(re.fullmatch(pattern, core) for pattern in time_patterns)
        if not is_time_or_date and not any(phrase in core for phrase in time_exclusions):
            is_time_or_date = (
                self._tokens_fit(core, required={"time"}, allowed=fuzzy_time_allowed)
                or self._tokens_fit(core, required={"day"}, allowed=fuzzy_date_allowed)
                or self._tokens_fit(core, required={"date"}, allowed=fuzzy_date_allowed)
            )
        if "get_current_time" in enabled_set and is_time_or_date:
            return "get_current_time", {}

        location_patterns = (
            r"^(?:where are we|where am i|what(?:'s| is) (?:our|the current) location)$",
            r"^(?:where is this robot|where are you located)$",
            r"^(?:sekarang )?kita di ?mana$",
            r"^(?:sekarang )?saya di ?mana$",
            r"^(?:apa|dimana) lokasi(?: kita| saat ini)?$",
        )
        if "get_location" in enabled_set and any(
            re.fullmatch(pattern, core) for pattern in location_patterns
        ):
            return "get_location", {}

        if "get_weather" in enabled_set:
            weather_patterns = (
                r"^(?:what(?:'s| is) |how(?:'s| is) )?(?:the )?(?:current )?weather(?: today)?$",
                r"^(?:what(?:'s| is) )?(?:the )?weather like(?: today)?$",
                r"^(?:current )?weather forecast$",
                r"^(?:bagaimana )?cuaca(?: hari ini| sekarang)?$",
                r"^cuaca(?: hari ini| sekarang)? bagaimana$",
            )
            if any(re.fullmatch(pattern, core) for pattern in weather_patterns):
                return "get_weather", {}

            city_match = re.fullmatch(
                r"(?:what(?:'s| is) |how(?:'s| is) )?(?:the )?(?:current )?weather(?: like)? in (.+)",
                core,
            )
            if city_match:
                return "get_weather", {"location": city_match.group(1).strip()}

        exit_patterns = (
            r"^(?:stop|end|exit|leave) (?:the )?(?:conversation|conversation mode|listening)$",
            r"^(?:stop talking|that'?s all|goodbye|bye ropi)$",
            r"^(?:hentikan|akhiri) (?:percakapan|mode percakapan)$",
            r"^(?:sudah cukup|selesai ropi)$",
        )
        if "handle_exit_intent" in enabled_set and any(
            re.fullmatch(pattern, core) for pattern in exit_patterns
        ):
            return "handle_exit_intent", {}
        return None

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
            try:
                timezone = ZoneInfo(self.settings.default_timezone)
            except Exception:
                timezone = ZoneInfo("Asia/Jakarta")
            now = datetime.now(timezone)
            return {
                "timezone": getattr(timezone, "key", self.settings.default_timezone),
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
