# v0.7.7 Pre-Major Hardening

v0.7.7 prepares VerbaNode for the next major capability-development phase without adding robot-specific physical actions yet. The release focuses on conversation UX, authentication, verified plugin/action semantics, database migration structure, and reproducible Windows release builds.

## Strict chat Auto-scroll

The Conversation header includes a persistent Auto-scroll toggle.

- **ON:** the message viewport is pinned to the newest content and user scrolling is disabled.
- **OFF:** normal scrolling is enabled and incoming messages do not change the current viewport.
- While OFF, new content increments a floating **New messages** control. Clicking it jumps to the newest content without changing the Auto-scroll preference.
- The preference is stored in browser local storage.

The Conversation header also shows compact active-agent context for language, STT, TTS, and LLM configuration.

## Controller authentication

PIN login failures are tracked per client and use bounded lockout/backoff. The long-lived controller session token is no longer placed in the WebSocket URL. Instead:

1. the authenticated browser requests a short-lived WebSocket ticket over HTTPS;
2. the ticket is used once to establish the WebSocket;
3. the ticket is consumed and cannot be replayed.

## Verified plugin actions

`PluginResult` now has action-oriented fields in addition to the existing data/response contract:

- success
- status
- action ID
- error code
- verified state

Successful plugin executions expose `_action` metadata. Explicit action IDs provide an idempotency foundation so a repeated request with the same ID can return the already-verified result instead of repeating the operation.

This matters for future physical capabilities where retrying an action such as navigation must not accidentally execute it twice.

## Capability gateway

`PluginContext` exposes a `CapabilityGateway` that validates declared permissions before using supported capability services. This is the intended boundary for future robot, display, camera, serial, MQTT, filesystem, and similar integrations.

The gateway is **not a Python security sandbox**. External plugins remain trusted local code. Its purpose is to define the supported permission-checked service path before powerful physical capabilities are added.

## Action audit

Capability/tool executions can be recorded as JSONL audit entries containing action ID, plugin/tool identity, state, timing, and error information. An authenticated API endpoint exposes recent action activity for diagnostics.

Audit logs may contain operational details and should be treated as sensitive runtime data.

## Numbered database migrations

The database now has a numbered migration foundation under:

```text
app/migrations/
```

Existing legacy compatibility migrations remain in place. New schema changes can advance `schema_version` in a deterministic order, with installer-triggered database backup remaining the safety layer before upgrade migrations.

## Release-build isolation

Windows packaging now defaults to a separate `verbanode-build` Conda environment. Packaging dependencies are pinned, and the application version is centralized in `app/version.py`. This reduces the chance that creating a Windows EXE modifies the developer environment or produces materially different builds over time.

## CI correctness checks

CI now combines:

- Ruff high-signal correctness checks
- Python compilation
- dashboard JavaScript syntax validation
- the full pytest regression suite

The initial Ruff configuration intentionally focuses on correctness issues such as duplicate definitions/keys and undefined names instead of forcing a broad formatting rewrite immediately before the next major version.
