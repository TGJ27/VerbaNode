# VerbaNode v0.12.4 — Agent Mobile Contract + CI Hardening

## Mobile contract

- Advertises the existing `POST /api/agents/generate-role` operation in the versioned mobile contract for Android v0.5.1.
- Declares its `description` / `model` request fields and `role` / `system_prompt` / `greeting` response fields.
- Mobile contract format remains v1; REST API v1, WebSocket protocol v1, and database schema v14 are unchanged.

## CI reliability

- Makes the mobile-contract regression test validate real FastAPI operations through the generated OpenAPI schema instead of relying on framework-internal route objects.
- Normalizes FastAPI path-converter syntax before comparing manifest paths to OpenAPI paths.
- Updates the Windows CI checkout and Python setup actions to current Node-24-native majors.

No database migration or Knowledge engine change is required.
