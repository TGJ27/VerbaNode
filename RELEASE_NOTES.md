# VerbaNode v0.12.6 — Release + Mobile Diagnostics Hardening

## Mobile compatibility

- `/api/client-info` publishes a deterministic SHA-256 fingerprint of the complete mobile contract.
- Core CI pins and verifies the fingerprint, so endpoint/schema drift cannot silently change the Android contract.
- The existing authenticated diagnostics snapshot now includes Core/API/WebSocket/mobile-contract compatibility metadata.
- `/api/diagnostics/logs` is explicitly advertised in the mobile contract for Android v0.5.3.

## Diagnostics privacy

- Core's in-memory diagnostics sanitizer now redacts Authorization Bearer values, pairing secrets and device tokens in addition to session tokens, PINs and content patterns.
- The exported diagnostics ZIP remains Core-generated and excludes secrets, database content, conversations, certificates/private keys and model files.

REST API v1, WebSocket protocol v1, mobile contract v1, and database schema v14 are unchanged.
