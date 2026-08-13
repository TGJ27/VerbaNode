# v0.8.5 Stabilization

v0.8.5 is the release-quality pass that closes the v0.8 architecture sequence. It intentionally avoids a new major user-facing subsystem and concentrates on predictable client transport, session cleanup, crash recovery, bounded inputs, safer defaults, frontend separation, and repeatable release checks.

## Client transport contract

REST remains API v1 and WebSocket remains Protocol v1. The server advertises heartbeat timing in the public client contract and authenticated session/connection metadata.

Browser clients must use a WebSocket `Origin` matching the dashboard `Host`. Native clients that do not send a browser Origin remain valid, which keeps the backend usable by a future mobile application without weakening browser cross-origin protections.

The dashboard transport performs:

1. public client-contract load;
2. stored-session validation;
3. one-time WebSocket ticket acquisition;
4. heartbeat transmission and watchdog checks;
5. bounded exponential reconnect;
6. session validation before reconnect;
7. explicit stop behavior for protocol/origin incompatibility.

## Controller lifecycle

VerbaNode still permits one active authenticated controller. Idle session expiration is now applied consistently when validating or inspecting controller state. Expiring or logging out a controller also removes its outstanding one-time WebSocket tickets.

No trusted-device pairing semantics are introduced in this release.

## Persistent action reconciliation

Action records are durable, but their executing tasks are process-local. On process startup VerbaNode therefore reconciles any inherited active action:

- past-deadline `pending` / `running` -> `expired`;
- other inherited `pending` / `running` -> `interrupted`.

This prevents stale `running` rows from implying that work survived a process restart.

## Input and browser security baseline

v0.8.5 adds a default browser security header set and a configurable JSON body limit. File-based speech uploads use bounded streaming reads. Backup uploads continue to use the stricter backup-specific bounded validation from v0.8.3.

Clean source first run now creates `.env` from `.env.example` when needed and replaces blank/placeholder PIN values with a generated six-digit PIN.

## Dashboard modules

The browser remains framework-free. Responsibilities are divided among:

- `static/js/runtime.js`
- `static/js/client.js`
- `static/js/browser-ptt.js`
- `static/js/diagnostics.js`
- `static/js/chat.js`
- `static/js/agents.js`
- `static/js/plugins.js`
- `static/js/settings.js`
- `static/js/data-recovery.js`
- `static/app.js` for remaining orchestration/UI handlers

This preserves the existing web client while reducing coupling before another client implementation is introduced.

## Release gate

Run the lightweight release gate with:

```powershell
python scripts/release/verify_release.py
```

For the complete local gate:

```powershell
python scripts/release/verify_release.py --full --clean-tree
```

The verifier checks version consistency, Python compilation, JavaScript syntax when Node.js is installed, route duplication, clean-source exclusions, and optionally the complete pytest suite.

## Deferred after v0.8

v0.8.5 does not implement the mobile application, LAN discovery, QR pairing, trusted-device credentials, cloud relay, multi-controller ownership, or robot-specific providers. Those should build on the stabilized API/WebSocket/session/action contracts rather than changing them during this release.
