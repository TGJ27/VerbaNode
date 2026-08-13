# VerbaNode v0.8.1 — Architecture Hardening

v0.8.1 is a stabilization release on top of the v0.8.0 architecture foundation. It does not add mobile discovery/pairing or robot hardware providers. The goal is to make the existing backend easier to maintain and safer for multiple future clients before new platform features are added.

## API modularization

`app/main.py` is now primarily application composition and lifecycle code. The runtime-heavy endpoint groups have been extracted into dedicated routers:

- `app/api/system.py` — root, health, launcher control, bootstrap, system status, and pipeline status
- `app/api/diagnostics.py` — diagnostics snapshot, self-test, logs, export, and soak testing
- `app/api/audio.py` — device discovery/refresh, audio engine controls, device tests, and conversation runtime settings
- `app/api/ai.py` — AI engine restart, ASR reload/profile test/benchmark, and Kokoro reload
- `app/api/tts.py` — Edge voice catalogue/preview and script TTS preview
- `app/api/runtime_payloads.py` — shared audio-device and hardware payload helpers

The existing routers for authentication, actions, agents, information, scripts, plugins, conversations, models, and backup/restore remain unchanged as the public client-neutral API surface.

## Request correlation and API errors

- Every REST request receives an `X-Request-ID` response header.
- A valid caller-supplied `X-Request-ID` is preserved, allowing a future mobile client to correlate its request with VerbaNode logs.
- Missing or unsafe IDs are replaced with a generated request ID.
- HTTP and validation failures now include a structured `error` object with `code`, `message`, and `request_id`; validation failures also include details.
- The legacy top-level `detail` field is retained so the current browser and older clients continue to work.
- The standard backend log format includes the current request ID.
- PIN login throttling/invalid-PIN responses now use the same structured error metadata while retaining `status` and `retry_after_seconds` compatibility fields.

## Controller policy cleanup

The old takeover approval flow was no longer part of the actual authorization policy, so v0.8.1 removes its dead code:

- removed takeover request storage and timeout handling
- removed `/api/auth/takeover/...` polling/respond routes
- removed takeover request/response schemas
- removed the dashboard waiting loop and approval modal
- removed the unused `force_takeover` field

The policy is now explicit: VerbaNode has one active controller session, and a client that supplies the correct PIN may obtain control immediately. The previous active controller is notified and disconnected.

This is still the temporary LAN controller policy. Trusted-device pairing and revocation are intentionally deferred until the mobile-client phase.

## Action concurrency hardening

The v0.8.0 SQLite action ledger remains the persistent authority. v0.8.1 closes an in-process race window by reserving the action completion future before claiming the action in SQLite. Multiple same-loop callers with the same explicit `action_id` therefore share one leader execution reliably.

Late completion also no longer overwrites an action that has already left `pending`/`running`, protecting interrupted/terminal ledger state from stale workers.

## Browser modularization

The dashboard remains plain browser JavaScript—no framework migration. Diagnostics rendering and refresh logic has moved into `app/static/js/diagnostics.js`, loaded before the main dashboard script. This is the first incremental split of the large `app.js` while keeping existing behavior and deployment unchanged.

## Mobile/discovery scope

Still intentionally **not included** in v0.8.1:

- mobile application
- mDNS/Bonjour LAN discovery
- QR/device pairing
- trusted-device credentials/revocation
- Bluetooth discovery
- cloud relay / Internet remote control
- robot-specific hardware providers

Both the web dashboard and future mobile application should continue to target the same REST and WebSocket contracts.

## Validation status

The clean v0.8.1 source tree passes **178 automated tests**, Python compilation, dashboard JavaScript syntax validation, router duplication checks, and source-helper import checks. A final target-machine test of `run.bat`, `build_windows.bat`, the generated EXE, and the installer is still recommended before publishing the release.
