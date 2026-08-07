from __future__ import annotations

import re
from typing import Any

from app.plugins.base import BuiltinPlugin
from app.plugins.context import PluginContext
from app.plugins.matching import normalized_core
from app.plugins.result import PluginResult


class StopConversationPlugin(BuiltinPlugin):
    id = "handle_exit_intent"
    name = "Stop conversation intent"
    description = "Stops continuous conversation mode when clearly requested."
    category = "Conversation control"
    priority = 40
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Stop continuous conversation mode when the user asks to end or stop the conversation.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }
    _patterns = (
        r"^(?:stop|end|exit|leave) (?:the )?(?:conversation|conversation mode|listening)$",
        r"^(?:stop talking|that'?s all|goodbye|bye ropi)$",
        r"^(?:hentikan|akhiri) (?:percakapan|mode percakapan)$",
        r"^(?:sudah cukup|selesai ropi)$",
    )

    def match(self, context: PluginContext) -> dict[str, Any] | None:
        core = normalized_core(context.text)
        return {} if any(re.fullmatch(pattern, core) for pattern in self._patterns) else None

    async def execute(self, context: PluginContext) -> PluginResult:
        return PluginResult(
            response="Conversation mode will stop.",
            stop_conversation=True,
        )

    def format_result(self, result: dict[str, Any], context: PluginContext) -> str:
        if result.get("error"):
            return str(result["error"])
        if str(context.metadata.get("language") or "en") == "id":
            return "Mode percakapan akan dihentikan."
        return str(result.get("message") or "Conversation mode will stop.")
