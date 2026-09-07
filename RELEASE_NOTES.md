# VerbaNode v0.12.2 — Mobile Contract Hardening

v0.12.2 adds an explicit, machine-readable Core ↔ Android compatibility contract while preserving the existing REST API v1 and WebSocket protocol v1 behavior.

## Mobile contract manifest

- `/api/client-info` now publishes a versioned `mobile_contract` manifest for Android clients.
- The manifest declares the supported API range, WebSocket protocol, session header, WebSocket paths, and the complete mobile REST operation set.
- The current manifest contains 108 method/path operation specifications, including dynamic endpoint templates.
- Critical auth, trusted-device, pairing, bootstrap, and WebSocket request/response field requirements are advertised explicitly.
- WebSocket close codes for unauthorized sessions, rejected origins, unsupported protocols, and heartbeat timeouts are part of the advertised contract.

## Contract regression protection

- Core tests verify that every advertised mobile operation resolves to a real FastAPI route with the same HTTP method.
- Critical request field sets are checked against the authoritative Pydantic models.
- Client-info integration is tested so the published manifest cannot silently disappear.
- Android can reject incompatible Core changes before sending credentials or opening a long-lived WebSocket session.

## Compatibility

- REST API remains version 1.
- WebSocket protocol remains version 1.
- Database schema remains v14; no migration is required from v0.12.1.
- Existing clients that ignore the new `mobile_contract` field remain compatible.
- VerbaNode Android v0.4.7+ uses this manifest as a required compatibility boundary.
- Hybrid RAG Phase 7 and Windows audio-recovery behavior remain unchanged.
