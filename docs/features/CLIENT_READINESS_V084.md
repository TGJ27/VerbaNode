# v0.8.4 Client Readiness

v0.8.4 prepares VerbaNode's existing LAN API for more than one UI implementation without adding the mobile application, device discovery, or pairing yet. The browser dashboard remains the reference client, but it now consumes the same explicit compatibility contract that a future native mobile client can use.

## Public client contract

`GET /api/client-info` is intentionally available before authentication. It contains no controller token, PIN, user data, agents, conversations, or runtime secrets. It reports only compatibility metadata:

- VerbaNode server version/build
- REST API version and minimum supported version
- request-ID header name
- PIN/session authentication mode
- session header name
- single-active-controller policy
- WebSocket endpoint/protocol version/ticket requirement
- stable bootstrap/status/heartbeat/session endpoint paths
- feature flags, including explicit `mobile_pairing=false` and `lan_discovery=false`

This gives a future mobile client a deterministic handshake after the user manually supplies the VerbaNode address.

## Client metadata and session identity

Login remains backwards compatible with older clients that only send `pin` and `client_name`. v0.8.4 additionally accepts optional:

- `client_type`
- `client_version`
- `api_version`

Successful sessions receive a random non-secret `session_id`. Authenticated `/api/session`, heartbeat/controller status, login responses, and the initial WebSocket `connected` event can expose sanitized client metadata without exposing the session token.

A client that explicitly requests an unsupported REST API version is rejected with `409 incompatible_api_version` plus the public client contract. Older clients that omit `api_version` remain supported.

## Compatibility response headers

All `/api/*` responses include:

- `X-Request-ID`
- `X-VerbaNode-Version`
- `X-VerbaNode-API-Version`
- `X-VerbaNode-WebSocket-Protocol`
- `Cache-Control: no-store` unless an endpoint already supplied a cache policy

These headers let clients/logs identify the exact server contract even for error responses.

## WebSocket protocol guard

Protocol-v1 commands continue to use the v0.8 envelope. Legacy command payloads without an explicit protocol field remain accepted. If a client explicitly sends a different protocol version, VerbaNode sends a `protocol_error` event and closes that socket with application close code `4406` instead of silently misinterpreting the command.

## Browser modularization

The dashboard remains framework-free. The previous `app.js` is split incrementally into ordered classic scripts:

- `static/js/runtime.js` — client constants, shared state, selectors, UI/storage utilities
- `static/js/client.js` — REST client, login/session lifecycle, WebSocket transport
- `static/js/browser-ptt.js` — browser microphone capture/upload
- `static/js/diagnostics.js` — diagnostics UI
- `static/app.js` — product UI/rendering/event binding that has not yet been split

This reduces `app.js` from roughly 2,243 lines in v0.8.3 to under 1,800 lines while avoiding a framework rewrite.

The split also fixes a dashboard error-handling bug where a parsed error payload was scoped inside a `try` block but referenced afterward when constructing structured error metadata.

## Deliberately deferred

v0.8.4 does **not** implement:

- mobile application UI
- mDNS/Bonjour discovery
- subnet scanning
- QR pairing
- trusted-device credentials
- device revocation
- cloud relay / Internet remote control
- multi-controller concurrency

The current controller policy remains one authenticated active controller at a time. A web browser or future mobile app can be the controller, but v0.8.4 does not change that security/ownership model.
