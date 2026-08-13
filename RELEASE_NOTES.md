# VerbaNode v0.8.5 — Stabilization

v0.8.5 closes the v0.8 architecture sequence with a release-quality stabilization pass. It does not add a new product subsystem. Instead, it hardens the shared REST/WebSocket backend, browser client, controller lifecycle, action recovery, source first-run behavior, upload handling, security defaults, and release verification so the next development line can build on a more predictable base.

## Reliable client transport

The browser WebSocket client now uses explicit heartbeat timing advertised by the server, stale-connection detection, bounded exponential reconnect backoff, and session validation before reconnecting. Connection generations prevent stale asynchronous connection attempts from replacing a newer socket.

The server now applies an idle heartbeat timeout to authenticated WebSockets and publishes heartbeat timing in `/api/client-info`, login/session metadata, and the initial connection event. Browser WebSocket origins must match the dashboard host; native/originless clients remain supported for future non-browser clients.

## Controller/session cleanup

Expired controller sessions are now removed consistently when controller state is queried or validated, and any outstanding one-time WebSocket tickets belonging to an expired/logout session are invalidated. This keeps the single-active-controller policy deterministic without carrying stale ticket state forward.

## Action crash recovery

At startup, persistent actions inherited in `pending` or `running` state are reconciled immediately. Actions whose deadline has passed become `expired`; other inherited active actions become `interrupted`. VerbaNode never pretends that process-local work continued through a restart.

Action execution logging now carries action/plugin/status/verification/latency context to make failures easier to correlate with request and capability audit information.

Windows/CI timing edge cases are also hardened: a timeout whose effective deadline was capped by the action TTL is deterministically classified as `expired`, and capability cancellation explicitly invokes the provider cancellation hook even if the operation task is cancelled before it receives its first execution slice. Provider cancellation notifications are de-duplicated per operation.

## Security and bounded input defaults

API responses now carry a baseline browser security policy including CSP, frame denial, content-type protection, referrer policy, permissions policy, and same-origin resource/opener controls.

JSON request bodies are rejected early when their declared size exceeds the configured limit. Browser PTT and ASR benchmark uploads are read incrementally with explicit size bounds instead of using unbounded `UploadFile.read()` calls.

A clean source checkout now seeds `.env` on first run and replaces an unset or placeholder dashboard PIN with a random six-digit PIN, matching the packaged first-run safety model rather than silently relying on the development fallback.

## Dashboard modularization and recovery UX

The framework-free dashboard is split further into dedicated modules for chat, agents, plugins, settings, data recovery, runtime state, client transport, browser PTT, and diagnostics. The remaining `app.js` is below 1,000 lines.

Backup/restore UI now displays recovery/schema status, restore progress, and request IDs when a restore fails. This builds on the v0.8.3 checksum, safety-snapshot, and SQLite-native restore layer.

## Release verification

A new `scripts/release/verify_release.py` command verifies version consistency, Python compilation, dashboard JavaScript syntax, duplicate API routes, clean-tree rules, and optionally the full pytest suite. Windows packaging runs the verifier before PyInstaller, and CI runs the same release checks.

## Existing v0.8 architecture retained

v0.8.5 retains:

- modular FastAPI routers and thin application composition
- REST request correlation IDs and structured errors
- REST API v1 / WebSocket Protocol v1 compatibility contract
- persistent restart-safe action ledger and capability provider boundary
- ordered database migrations with pre-migration recovery snapshots
- backup format v3 with checksum/size verification and rollback recovery
- single root `run.bat` source workflow
- one active authenticated controller at a time

## Deferred scope

Still intentionally not included:

- mobile application
- mDNS/Bonjour or automatic LAN discovery
- QR/device pairing
- trusted-device credentials and revocation
- multi-controller concurrency
- cloud relay / Internet remote control
- robot-specific hardware providers

These remain separate post-v0.8 work so the web dashboard and future mobile application can both use the same stabilized server contracts.

## Validation

The clean v0.8.5 source tree passes **215 automated tests**. The release verifier also checks Python compilation, all dashboard JavaScript files when Node.js is available, duplicate API routes, version consistency, and generated/private-file exclusions for clean-source packaging.

Windows source, packaged EXE, and installer smoke testing should still be performed on the target Windows machine before publishing the release.
