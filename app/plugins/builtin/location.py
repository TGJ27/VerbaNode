from __future__ import annotations

import re
from typing import Any

from app.plugins.base import BuiltinPlugin
from app.plugins.context import PluginContext
from app.plugins.matching import normalized_core
from app.plugins.result import PluginResult


class LocationPlugin(BuiltinPlugin):
    id = "get_location"
    name = "Configured location"
    description = "Returns the configured physical location of the assistant."
    category = "Information"
    priority = 20
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Get the configured physical location of this assistant. This tool MUST be used when the user asks where the robot or 'we' are.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
    _patterns = (
        r"^(?:where are we|where are we at|where are we currently|where are we currently at|where are we right now)$",
        r"^(?:where am i|where am i at|where am i currently|where am i right now)$",
        r"^(?:what(?:'s| is) (?:our|the current) location|what location are we at|what is this location)$",
        r"^(?:where is this robot|where are you located|where is this place)$",
        r"^(?:sekarang )?kita (?:ada )?di ?mana$",
        r"^(?:sekarang )?saya (?:ada )?di ?mana$",
        r"^(?:apa|dimana) lokasi(?: kita| saat ini)?$",
    )

    def match(self, context: PluginContext) -> dict[str, Any] | None:
        core = normalized_core(context.text)
        return {} if any(re.fullmatch(pattern, core) for pattern in self._patterns) else None

    async def execute(self, context: PluginContext) -> PluginResult:
        return PluginResult(data={"location": context.settings.default_location})

    def format_result(self, result: dict[str, Any], context: PluginContext) -> str:
        if result.get("error"):
            return str(result["error"])
        location = result.get("location") or context.settings.default_location
        if str(context.metadata.get("language") or "en") == "id":
            return f"Saat ini kita berada di {location}."
        return f"We are currently in {location}."
