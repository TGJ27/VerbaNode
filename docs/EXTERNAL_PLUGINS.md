# VerbaNode External Plugins — SDK v1

VerbaNode v0.6.3 loads trusted local Python plugins from the repository's top-level `plugins/` directory. Built-in capabilities remain under `app/plugins/builtin/`.

## Folder structure

```text
plugins/
└── my_plugin/
    ├── plugin.json
    ├── plugin.py
    ├── helper.py       # optional; import with `from .helper import ...`
    └── README.md       # optional
```

Folders beginning with `.` or `_` are ignored. Copy `plugins/_template/` for a clean starting point.

## Entry contract

The entry module exports `create_plugin()` and returns an `app.plugins.Plugin` instance. The schema `function.name` must exactly match the manifest ID.

```python
from app.plugins import Plugin, PluginContext, PluginResult


class MyPlugin(Plugin):
    schema = {
        "type": "function",
        "function": {
            "name": "my_plugin_tool",
            "description": "Perform the plugin action.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
        },
    }

    async def execute(self, context: PluginContext) -> PluginResult:
        value = str(context.arguments.get("value") or "")
        return PluginResult(data={"value": value}, response=value)


def create_plugin() -> Plugin:
    return MyPlugin()
```

## Runtime hardening

- Plugin calls time out after `VERBANODE_PLUGIN_EXECUTION_TIMEOUT_SECONDS`.
- Execution concurrency is bounded by `VERBANODE_PLUGIN_MAX_CONCURRENT_EXECUTIONS`.
- After `VERBANODE_PLUGIN_FAILURE_THRESHOLD` consecutive failures, a plugin becomes `Unhealthy` and is removed from deterministic and LLM tool routing.
- Use **Recover**, **Repair / reload**, or disable and re-enable the plugin after fixing the cause.
- Stopping a conversation cancels active plugin coroutines.
- Reload validates the new package first. If validation or import fails, the previous working version remains registered and the reload error is shown on its card.
- Removing a plugin folder and pressing **Reload external** unloads it safely.

## States

`Healthy`, `Disabled`, `Loading`, `Reloading`, `Unhealthy`, `Invalid package`, `Incompatible`, and `Load failed`.

## Security

These controls isolate common failures but do not sandbox Python code. Only install plugins you trust. See `docs/PLUGIN_SECURITY.md` and `docs/PLUGIN_MANIFEST.md`.
