# VerbaNode v0.9.7 — Phase 1 Stability Hardening

v0.9.7 is a focused reliability release for controller transport and diagnostics. It does not change the Type-to-Talk schema or direct-speech behavior introduced in v0.9.6.

## What changed

- **Fail-safe host PTT on WebSocket loss.** A controller token can remain valid for the normal idle timeout after its WebSocket disappears. v0.9.6 incorrectly used token validity to decide whether a dropped hold-to-talk session should be cancelled. v0.9.7 instead checks the live WebSocket slot after a short reconnect grace period.
- **Reconnect-safe PTT cleanup.** If the same controller token reconnects within the grace period, host PTT remains active. If no replacement socket exists, Core cancels PTT and releases the host microphone path.
- **Cleanup on abnormal socket failures.** Unexpected WebSocket handler failures now use the same fail-safe PTT cleanup path.
- **Structured unexpected HTTP errors.** Unhandled server exceptions are logged with the request context and returned as a stable `internal_server_error` JSON envelope. The response includes `X-Request-ID` and does not expose exception details to clients.
- **Regression tests.** Coverage now explicitly verifies dropped PTT sockets, fast same-token reconnect behavior, and request-ID-bearing 500 responses.

## Compatibility

Database schema remains unchanged from v0.9.6. VerbaNode Android v0.3.7 is the coordinated Phase 1 mobile hardening release; older compatible clients can still use the Core API.

## Upgrade

Fully stop VerbaNode Core, replace the release files, and start it again. No database migration is required for v0.9.7.
