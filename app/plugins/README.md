# VerbaNode plugin architecture

VerbaNode uses one registry for built-in capabilities and trusted local external plugins.

```text
Conversation / LLM
        |
        v
ToolService compatibility facade
        |
        v
PluginManager -> PluginRegistry
        |                 |
        v                 v
built-in plugins     external plugins/
```

Each plugin owns its schema, optional deterministic matcher, execution, spoken fallback, metadata, permissions, and lifecycle hook. `ToolService` preserves the original conversation and LLM interface.

Built-in plugins live under `app/plugins/builtin/` and external packages live under the top-level `plugins/` folder.

v0.6.3 hardening adds validation, execution timeout, bounded concurrency, cancellation, failure thresholds, health states, safe replacement reload, and detailed metrics. These are reliability boundaries, not a Python security sandbox.
