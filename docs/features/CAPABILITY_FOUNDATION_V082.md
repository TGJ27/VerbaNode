# v0.8.2 Capability Foundation

v0.8.2 establishes the provider boundary that future physical and service capabilities will use. It deliberately does **not** implement robot hardware, mobile pairing, LAN discovery, or cloud control.

## Provider architecture

New provider-neutral modules live under `app/capabilities/`:

- `models.py` — capability descriptors, requests, and normalized results
- `permissions.py` — namespaced capability validation and manifest-permission mapping
- `provider.py` — the `CapabilityProvider` interface
- `registry.py` — duplicate-safe provider/capability registration
- `service.py` — bounded execution, timeout, expiry, cancellation, lifecycle, and active-operation tracking

A plugin can request a provider operation through `PluginContext.gateway.invoke(...)`. For example, `robot.navigate` requires the plugin to declare the `robot` permission. `display.show` requires `display`; `camera.capture` requires `camera`; `filesystem.read.*` and `filesystem.write.*` map to their corresponding filesystem permissions.

The gateway remains an application-level boundary, not a Python sandbox. External plugins are still trusted local Python code and can technically bypass the gateway if they directly access OS resources. Future first-party physical integrations should use providers exclusively.

## Execution limits and expiry

Capability provider execution has independent controls for:

- global concurrent operations
- per-provider concurrent operations
- provider/default timeouts
- maximum serialized argument size
- default request TTL
- maximum request TTL
- cancellation-hook timeout
- provider shutdown timeout

A request that expires before or during execution returns an `expired` terminal result and is not automatically retried.

## Action ledger schema v3

The persistent action ledger now stores `expires_at`. Expired plugin actions are terminal and replay as expired instead of being executed after a restart or late retry. This is particularly important for physical commands where a stale instruction may no longer be safe or relevant.

## Cancellation

Authenticated clients can request cancellation of a currently active plugin action through `POST /api/actions/{action_id}/cancel`. Cancellation propagates into active capability-provider operations associated with that parent action. Providers can implement a best-effort `cancel(operation_id)` hook for hardware/service-specific stop behavior.

The capability API also exposes cancellation for an individual currently active provider operation.

## Public capability metadata

`GET /api/capabilities` returns provider metadata, registered operations, configured execution limits, and active operations. No generic remote execute endpoint is added in v0.8.2; actual user-facing capability APIs should remain intentional and domain-specific.

## Deferred scope

Still intentionally deferred:

- robot-specific hardware providers
- mobile application
- mDNS/Bonjour discovery
- QR pairing and trusted-device credentials
- device revocation UI
- cloud relay / Internet remote control

The goal is to make those later features additive rather than requiring another backend redesign.
