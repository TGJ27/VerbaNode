# v0.8.1 Architecture Hardening

v0.8.1 continues the architecture-first v0.8.x line. It deliberately avoids mobile discovery/pairing and robot hardware implementation while strengthening the common backend that those future clients will use.

## Application boundary

`app/main.py` owns FastAPI construction, router registration, startup/shutdown, static mounting, and UI cache policy. Product/runtime endpoints live under `app/api/`.

```text
Web Dashboard ─┐
               ├── REST + WebSocket v1 ── VerbaNode Core ── Services / Plugins / Actions
Future Mobile ─┘
```

No mobile-specific backend path is introduced.

## REST request identity

Every HTTP request has a request ID. Clients may provide a safe `X-Request-ID`; otherwise VerbaNode creates one. The same ID is returned in the response and injected into Python log records.

Error responses preserve the historical `detail` field and add:

```json
{
  "detail": "Example failure",
  "error": {
    "code": "http_409",
    "message": "Example failure",
    "request_id": "..."
  }
}
```

This keeps the existing dashboard compatible while giving future clients a stable machine-readable envelope.

## Controller policy

One active controller session exists at a time. Correct PIN authentication is the authorization boundary; a newly authenticated controller replaces the previous session. The obsolete approval/polling takeover flow has been removed rather than kept as a second conflicting policy.

Pairing, trusted devices, credential revocation, and discovery are deferred until the mobile phase.

## Action identity

SQLite remains the cross-process/restart action authority. Within one event loop, the first caller now reserves an in-flight completion future before the database claim so concurrent callers cannot both become leaders for one explicit action ID.

Ledger completion only updates actions that are still active (`pending` or `running`), preventing late workers from rewriting terminal/interrupted state.

## Browser structure

The dashboard remains framework-free. Diagnostics logic is the first large UI domain moved out of `app.js` into `app/static/js/diagnostics.js`. Future v0.8.x work can continue this incremental split without a frontend rewrite.
