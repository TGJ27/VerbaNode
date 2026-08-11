# v0.6.1 Phase 2: Built-in Plugin Manager

## Purpose

Phase 1 separated built-in capabilities into independent modules. Phase 2 makes those modules visible and manageable without introducing external code loading.

## Runtime flow

```text
Agent tool assignment
        +
Global plugin enabled state
        |
        v
PluginRegistry.schemas / resolve
        |
        v
PluginManager.execute
        |
        v
Execution metrics and health
```

A plugin must be enabled globally and assigned to the active agent before it is included in deterministic routing or LLM tool schemas.

## Persistence

The disabled plugin ID list is stored under the SQLite settings key:

```text
disabled_builtin_plugins
```

No schema migration is required because the existing settings table accepts arbitrary keys.

## API

- `GET /api/plugins`
- `PUT /api/plugins/{plugin_id}`
- `POST /api/plugins/{plugin_id}/reset-metrics`
- `POST /api/plugins/reset-metrics`

All endpoints require the active controller token.

## Metrics

Metrics are process-local and reset after an application restart:

- executions
- errors
- average latency
- last latency
- last error

The enabled/disabled state persists across restarts.

## Phase 3 boundary

Phase 2 does not import third-party code. External folder discovery, manifests, install/remove actions, dependency handling, sandboxing, and hot reload are intentionally deferred.
