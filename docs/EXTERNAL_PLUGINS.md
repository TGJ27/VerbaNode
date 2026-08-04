# VerbaNode External Plugins — SDK v1

VerbaNode v0.6.2 loads trusted local Python plugins from the repository's top-level `plugins/` directory. Built-in capabilities remain under `app/plugins/builtin/`; external plugins do not replace or modify those files.

## Folder structure

```text
plugins/
└── my_plugin/
    ├── plugin.json
    ├── plugin.py
    ├── helper.py       # optional; import with `from .helper import ...`
    └── README.md       # optional
```

Folders whose names start with `.` or `_` are ignored.

## Manifest

`plugin.json` must contain:

```json
{
  "id": "my_plugin_tool",
  "name": "My Plugin",
  "version": "1.0.0",
  "author": "Your Name",
  "description": "What the plugin does.",
  "entry": "plugin.py",
  "sdk_version": "1.0",
  "category": "External",
  "priority": 200,
  "permissions": ["internet"]
}
```

Rules:

- `id` starts with a lowercase letter and contains only lowercase letters, numbers, and underscores.
- `entry` must be a `.py` file inside the plugin folder.
- `sdk_version` must use major version `1`.
- `permissions` are displayed to operators but are not technically enforced in v0.6.2.
- IDs must be unique across built-in and external plugins.

## Entry module

The entry module must export `create_plugin()` and return an `app.plugins.Plugin` instance:

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
                "properties": {
                    "value": {"type": "string"}
                },
                "required": ["value"]
            }
        }
    }

    def match(self, context: PluginContext):
        # Optional deterministic routing. Return None when not matched.
        return None

    async def execute(self, context: PluginContext) -> PluginResult:
        value = str(context.arguments.get("value") or "")
        return PluginResult(data={"value": value}, response=value)


def create_plugin() -> Plugin:
    return MyPlugin()
```

The schema's `function.name` must exactly equal the manifest `id`.

## Lifecycle

At startup VerbaNode:

1. Registers built-in plugins.
2. Reads the persisted global disabled-plugin list.
3. Scans `plugins/`.
4. Validates each manifest and entry.
5. Imports the module and calls `create_plugin()`.
6. Registers the plugin in the shared Plugin Registry.

The optional `async def shutdown(self)` or synchronous `shutdown(self)` hook runs before reload, unload, or application shutdown.

## Reload behavior

- **Refresh status** only retrieves current backend state.
- **Reload external** rescans all folders, loads new plugins, reloads changed plugins, and unloads plugins whose folders were removed.
- A card's **Reload** button reloads only that external folder.
- If new code fails during reload, the previous loaded plugin remains available and a separate failed-load card reports the error.
- Changing a plugin ID during reload is rejected; restart after intentionally renaming a plugin folder and manifest.

## Agent assignment

Loading a plugin globally does not automatically grant it to every agent. Open:

```text
Agents → Edit agent → Models & Voice → Tools
```

Select the plugin for each agent that should use it.

## Failure isolation

VerbaNode catches and reports:

- Missing or invalid `plugin.json`
- Unsupported SDK versions
- Unsafe or missing entry files
- Import and factory exceptions
- Duplicate IDs
- Deterministic matcher exceptions
- Execution and result-formatting exceptions
- Shutdown-hook exceptions

These protections are reliability boundaries, not a security sandbox.

## Security

External plugins execute in the VerbaNode Core process and can access anything available to that Python process. Only install code you trust. Review declared permissions and source code before enabling a plugin.

Not included in SDK v1:

- Dependency installation
- Plugin marketplace or automatic updates
- Cryptographic signing
- Process-level sandboxing
- Filesystem, network, shell, camera, microphone, or robot permission enforcement

## Reference plugin

Copy `plugins/example_echo/` as a starting point. Assign `example_echo` to an agent, then test:

```text
Echo external plugins are working.
```
