# VerbaNode v0.9.8 — Phase 2 Coordinated Hardening

v0.9.8 keeps the v0.9.7 controller/PTT and structured request-ID protections and fixes a concrete Audio Library file-identity bug exposed by duplicate/legacy filenames.

## Fixed

- **Audio Library delete “file not found”.** Duplicate uploads are intentionally stored as names such as `clip (2).mp3`. Older code listed that exact filename but sanitized it again when play/rename/delete was requested, turning it into a different path and producing a false 404. Existing library items are now resolved by their exact listed basename.
- **Legacy filename compatibility.** Compatible existing files containing non-path characters that the current upload sanitizer would replace can now be played, renamed, or deleted by the exact name shown in the dashboard/mobile app.
- **Idempotent DELETE.** Deleting an item that has already disappeared returns a successful deletion result (`deleted: false`) so stale clients can refresh rather than remaining stuck behind an “Audio file not found” error.

## Regression coverage

Tests now verify duplicate collision names, compatible legacy names, and idempotent missing-item deletion. No database migration is required.

## Compatibility

VerbaNode Android v0.3.9 is the coordinated Phase 2 mobile hardening release. Older API-compatible clients continue to work.

## Upgrade

Fully stop VerbaNode Core, replace the release files, and start it again. No database migration is required for v0.9.8.
