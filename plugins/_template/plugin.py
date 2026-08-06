from app.plugins import Plugin, PluginContext, PluginResult


class TemplatePlugin(Plugin):
    schema = {
        "type": "function",
        "function": {
            "name": "replace_with_plugin_id",
            "description": "Describe when the agent should call this plugin.",
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "string",
                        "description": "Example input value.",
                    }
                },
                "required": ["value"],
            },
        },
    }

    def match(self, context: PluginContext):
        # Optional deterministic routing. Return a dictionary of arguments when
        # the user text clearly belongs to this plugin; otherwise return None.
        return None

    async def execute(self, context: PluginContext) -> PluginResult:
        value = str(context.arguments.get("value") or "")
        return PluginResult(data={"value": value}, response=value)


def create_plugin() -> Plugin:
    return TemplatePlugin()
