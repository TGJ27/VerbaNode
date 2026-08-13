# VerbaNode v0.8.4 — Client Readiness

v0.8.4 makes the v0.8 backend contract easier to consume from both the existing dashboard and a future mobile client, while continuing to defer LAN discovery and device pairing until the mobile phase.

## Public compatibility handshake

A new unauthenticated `GET /api/client-info` endpoint exposes only non-secret compatibility metadata: server version/build, REST API version, WebSocket protocol version, PIN/session authentication contract, controller policy, stable endpoint paths, and feature flags.

The endpoint intentionally does not expose the PIN, controller token, agents, conversations, settings, plugin data, or other authenticated state.

## Client-aware controller sessions

Login remains backwards compatible with older request bodies, but clients can now optionally declare `client_type`, `client_version`, and `api_version`. Controller sessions receive a random non-secret `session_id` and retain that metadata for diagnostics/client UX.

Authenticated `GET /api/session` exposes the current sanitized session metadata and server protocol versions. Login and initial WebSocket connection payloads now provide the same compatibility information.

Clients that explicitly request an unsupported REST API version receive a structured `409 incompatible_api_version` response. Clients that omit the field continue to work.

## Stable API and WebSocket compatibility signals

All `/api/*` responses now advertise VerbaNode server/API/WebSocket versions in headers alongside the existing request correlation ID. API responses default to `Cache-Control: no-store`.

WebSocket protocol v1 remains backwards compatible with legacy command objects that omit a protocol field. Explicit unsupported protocol versions now receive a `protocol_error` event and socket close code `4406` instead of being processed ambiguously.

## Browser dashboard modularization

The browser remains framework-free, but its transport/runtime responsibilities are no longer concentrated in the main script. v0.8.4 adds:

- `static/js/runtime.js`
- `static/js/client.js`
- `static/js/browser-ptt.js`

alongside the existing `static/js/diagnostics.js`. The remaining `app.js` falls below 1,800 lines.

The extracted API client also fixes structured-error parsing so error metadata is available after JSON parsing rather than referencing a block-scoped variable.

## Existing v0.8 platform retained

v0.8.4 preserves the recovery-hardening schema/backup format from v0.8.3, capability-provider foundation from v0.8.2, persistent action ledger, request IDs, modular backend routers, WebSocket protocol v1, and the single `run.bat` source workflow.

## Deferred scope

Still intentionally not included:

- mobile app
- mDNS/Bonjour LAN discovery
- QR/device pairing
- trusted-device credentials and revocation
- multi-controller concurrency
- cloud relay / Internet remote control
- robot-specific hardware providers

## Validation

The clean v0.8.4 source tree passes **203 automated tests** and is validated with Python compilation, dashboard JavaScript syntax checks for every split script, duplicate-route checks, patch/full-source equivalence, and ZIP integrity before packaging. Windows source/EXE/installer smoke testing should still be performed on the target machine before publishing the release.
