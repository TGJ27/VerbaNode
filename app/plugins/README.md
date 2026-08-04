# VerbaNode internal plugin architecture

Version 0.6.1 Phase 2 keeps capabilities internal and statically registered, then exposes them through a persistent Plugin Manager.

```text
Conversation / LLM
        |
        v
ToolService compatibility facade
        |
        v
PluginManager -> PluginRegistry -> built-in capability plugin
        |
        v
Authenticated Plugin Manager API and dashboard
```

Each capability owns its schema, deterministic matching, execution, direct spoken fallback, metadata, permissions, and runtime metrics. The existing `ToolService` public API remains compatible.

Built-in capabilities currently included:

- `get_current_time`
- `get_location`
- `get_weather`
- `handle_exit_intent`

Global plugin state is stored as a list of disabled IDs in the existing SQLite settings table. Per-agent tool assignments are preserved independently.

External discovery, installation, manifests, dependencies, third-party execution, and hot reload are deliberately reserved for Phase 3.
