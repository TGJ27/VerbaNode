from __future__ import annotations

from datetime import datetime, timedelta, timezone as fixed_timezone
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.plugins.base import BuiltinPlugin
from app.plugins.context import PluginContext
from app.plugins.matching import normalized_core, tokens_fit
from app.plugins.result import PluginResult


class CurrentTimePlugin(BuiltinPlugin):
    id = "get_current_time"
    name = "Current time"
    description = "Returns the exact current date and time in the configured timezone."
    category = "Information"
    priority = 10
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Get the exact current local date and time in the configured timezone. This tool MUST be used for every current time or date question; never estimate the answer.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }

    _exclusions = (
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
    _patterns = (
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
    _fuzzy_time_allowed = {
        "what", "whats", "is", "it", "its", "the", "current", "local",
        "exact", "time", "now", "right", "can", "could", "would", "you",
        "please", "tell", "give", "me", "do", "know", "today",
    }
    _fuzzy_date_allowed = {
        "what", "whats", "is", "it", "its", "the", "current", "day",
        "date", "today", "todays", "can", "could", "would", "you", "please",
        "tell", "give", "me", "do", "know",
    }

    def match(self, context: PluginContext) -> dict[str, Any] | None:
        core = normalized_core(context.text)
        matched = any(re.fullmatch(pattern, core) for pattern in self._patterns)
        if not matched and not any(phrase in core for phrase in self._exclusions):
            matched = (
                tokens_fit(core, required={"time"}, allowed=self._fuzzy_time_allowed)
                or tokens_fit(core, required={"day"}, allowed=self._fuzzy_date_allowed)
                or tokens_fit(core, required={"date"}, allowed=self._fuzzy_date_allowed)
            )
        return {} if matched else None

    async def execute(self, context: PluginContext) -> PluginResult:
        configured_name = context.settings.default_timezone
        try:
            timezone = ZoneInfo(configured_name)
        except ZoneInfoNotFoundError:
            if configured_name == "Asia/Jakarta":
                timezone = fixed_timezone(timedelta(hours=7), name="Asia/Jakarta")
            else:
                timezone = datetime.now().astimezone().tzinfo or fixed_timezone.utc
        now = datetime.now(timezone)
        return PluginResult(data={
            "timezone": getattr(timezone, "key", configured_name),
            "iso": now.isoformat(timespec="seconds"),
            "spoken": now.strftime("%A, %B %d, %Y at %I:%M %p"),
        })

    def format_result(self, result: dict[str, Any], context: PluginContext) -> str:
        if result.get("error"):
            return str(result["error"])
        spoken = result.get("spoken") or result.get("iso") or "the current time"
        timezone = result.get("timezone") or "the configured timezone"
        return f"It is currently {spoken} in the {timezone} timezone."
