# VerbaNode v0.8.2 — Capability Foundation

v0.8.2 builds on the v0.8.0 architecture foundation and v0.8.1 hardening work. This release introduces the provider boundary needed for future robot, display, camera, serial, MQTT, filesystem, network, and other controlled capabilities without implementing any specific robot hardware yet.

## Capability provider framework

A new `app/capabilities` package provides:

- `CapabilityProvider` — stable asynchronous provider interface
- `CapabilityRegistry` — duplicate-safe capability/provider registration
- `CapabilityService` — bounded execution, timeout, expiry, cancellation, active-operation tracking, and provider lifecycle
- provider-neutral capability descriptors, requests, and normalized results
- namespaced permission validation

Plugins can now use `PluginContext.gateway.invoke(...)` to request a registered capability. Capability names enforce manifest permissions before execution; for example, `robot.navigate` requires `robot`, `display.show` requires `display`, and `camera.capture` requires `camera`.

External Python plugins are still trusted code. This provider boundary is the supported architecture for first-party physical/service integrations, not an operating-system sandbox.

## Execution limits and cancellation

Capability execution now has configurable:

- global concurrency limit
- per-provider concurrency ceiling
- execution timeout
- cancellation-hook timeout
- provider shutdown timeout
- maximum argument payload size
- default and maximum TTL

Active provider operations are tied to their parent plugin action. Cancelling an active action propagates into its provider operation, and providers can implement their own best-effort hardware/service cancellation hook.

Authenticated APIs added:

- `GET /api/capabilities`
- `POST /api/capabilities/actions/{operation_id}/cancel`
- `POST /api/actions/{action_id}/cancel`

No generic remote capability-execution API is added in this release.

## Persistent action expiry / migration v3

The action ledger advances to schema version 3 and adds `expires_at`. Expired actions become terminal and are not executed after their deadline. Expiry is also considered during stale-action recovery, preventing old physical commands from becoming valid again after a restart.

## Existing 0.8 architecture retained

v0.8.2 retains:

- modular FastAPI routers
- WebSocket protocol v1
- restart-safe SQLite action idempotency
- structured API errors and `X-Request-ID`
- hardened backup/restore
- one source `run.bat`
- existing browser dashboard behavior

## Deferred scope

Still intentionally not included:

- mobile app
- mDNS/Bonjour LAN discovery
- QR/device pairing
- trusted-device credentials and revocation
- cloud relay / Internet remote control
- robot-specific hardware providers

## Validation status

The clean v0.8.2 source tree passes **187 automated tests** and Python compilation in the build environment used to assemble this update. Dashboard JavaScript syntax and Windows target-machine source/EXE/installer smoke tests should still be run before publishing the release.
