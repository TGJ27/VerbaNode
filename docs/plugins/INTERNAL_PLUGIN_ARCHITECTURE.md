# v0.6.0 Phase 1: Internal plugin architecture

This refactor moves each built-in capability into an independent module without
changing the dashboard, agent configuration, tool names, prompts, APIs, or
conversation behavior.

## Runtime flow

```text
ConversationManager / OllamaService
              |
              v
         ToolService
     compatibility facade
              |
              v
         PluginManager
              |
              v
         PluginRegistry
              |
   +----------+----------+----------+----------------+
   |                     |          |                |
Current time          Location    Weather    Stop conversation
```

## Compatibility

The following public methods are unchanged:

- `ToolService.schemas(enabled)`
- `ToolService.match_core_intent(text, enabled)`
- `ToolService.execute(name, arguments)`
- `ToolService.format_result(name, result)`

The existing tool identifiers are unchanged, so no database migration is
required.

## Scope

Included in Phase 1:

- Built-in plugin base and context models
- Ordered plugin registry
- Plugin manager and execution metrics
- Separate time, location, weather, and stop-conversation modules
- Backwards-compatible `ToolService` facade
- Unit tests and documentation

Not included yet:

- External plugin discovery
- Plugin manifests
- Enable/disable UI
- Installation or hot reload
- Third-party SDK guarantees
