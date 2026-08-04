from __future__ import annotations

import re

from app.plugins import Plugin, PluginContext, PluginResult


class ExampleEchoPlugin(Plugin):
    schema = {
        "type": "function",
        "function": {
            "name": "example_echo",
            "description": "Repeat text exactly when the user explicitly asks the example echo plugin to echo it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "The text to repeat.",
                    }
                },
                "required": ["text"],
            },
        },
    }

    def match(self, context: PluginContext) -> dict[str, str] | None:
        match = re.match(
            r"^\s*(?:please\s+)?(?:use\s+the\s+example\s+plugin\s+to\s+)?echo\s+(.+?)\s*$",
            context.text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return {"text": match.group(1)}

    async def execute(self, context: PluginContext) -> PluginResult:
        text = str(context.arguments.get("text") or "").strip()
        if not text:
            return PluginResult(data={"error": "No text was supplied to the echo plugin."})
        return PluginResult(data={"text": text}, response=text)

    def format_result(self, result, context: PluginContext) -> str:
        if result.get("error"):
            return str(result["error"])
        return str(result.get("message") or result.get("text") or "")


def create_plugin() -> Plugin:
    return ExampleEchoPlugin()
