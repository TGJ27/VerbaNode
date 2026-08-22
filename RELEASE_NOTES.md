# VerbaNode v0.9.6 — Type-to-Talk Self-Healing Queue

v0.9.6 fixes the case where an installation can still show:

`Type-to-Talk queue is unavailable: table type_to_talk_queue has no column named error`

even after updating to v0.9.5. The previous fix depended too heavily on migration v9 running once. If the database was already stamped schema v9 while a stale SQLite object remained, reinstalling the same release would not run v9 again.

## What changed

- Added database schema migration v10. It force-rebuilds `type_to_talk_queue` into the canonical five-column schema regardless of the existing v9 queue shape.
- Core now validates and repairs the Type-to-Talk queue on **every startup**, even when schema metadata already says the database is current.
- Send now has a request-time self-heal path. If the queue INSERT hits a SQLite schema error involving `type_to_talk_queue`, Core force-repairs the queue and retries the real INSERT exactly once.
- Queue repair removes every persistent SQLite trigger whose SQL references `type_to_talk_queue`, including triggers attached to another table.
- Queue validation now executes a real INSERT inside a savepoint and rolls it back. This validates trigger execution; the older `EXPLAIN INSERT` check was not sufficient for all persistent-object states.
- Valid queued text is preserved during rebuild. Playback state is reset to `waiting`.
- Existing v0.9.5/v0.9.4 cleanup hardening remains unchanged.

## Upgrade

Fully stop VerbaNode Core, replace the release files, then start it again. Migration v10 runs at startup. If a stale queue object somehow appears after startup, the first Send request can now repair it automatically without another migration bump.

The Android client remains compatible at v0.3.6; no Android code change is required for this Core database fault.
