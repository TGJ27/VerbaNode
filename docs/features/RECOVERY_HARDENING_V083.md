# v0.8.3 Recovery Hardening

v0.8.3 hardens the parts of VerbaNode that protect user state during upgrades, backup creation, and restore. It does not add mobile discovery/pairing or robot-specific providers.

## Numbered migration authority

Schema version 4 moves the remaining legacy column repairs out of `Database.initialize()` and into the numbered migration registry. Migration execution is ordered, validated, and protected by per-migration SQLite savepoints. A database whose schema version is newer than the running VerbaNode build is rejected instead of being silently downgraded.

Schema v4 also establishes durable database identity:

- `PRAGMA application_id` identifies VerbaNode databases.
- `PRAGMA user_version` mirrors the numbered schema version.
- `schema_migrations` records migration version, name, stable fingerprint, and application time.

Before an existing older database is migrated, VerbaNode creates a consistent `pre-migration-*.db` recovery snapshot. Recovery snapshots are retained separately from user-created ZIP backups and pruned to a bounded count.

## Backup format v3

Backup ZIPs now include SHA-256 and byte-size metadata for the SQLite database. Restore verifies both before the database is accepted.

Archive validation also rejects:

- unsupported/newer backup formats
- path traversal entries
- duplicate archive members
- archive symlinks
- oversized manifests/databases/uploads
- invalid SQLite files or failed integrity checks
- databases identified as another application
- inconsistent/newer schema metadata
- manifest/database checksum or size mismatches

Legacy v1/v2 VerbaNode backups remain accepted when they pass database validation.

## SQLite-native snapshots and restore

Database snapshots now use SQLite's backup API rather than copying the main database file after a WAL checkpoint. This creates a transactionally consistent standalone snapshot even when the live database uses WAL.

Restore also uses the SQLite backup API. Before replacement, VerbaNode creates a `pre-restore-*.db` safety snapshot. If replacement or migration fails, the safety snapshot is restored automatically.

## Recovery visibility

`GET /api/backup/status` reports the active backup format, current database schema version, and available automatic recovery snapshots. Recovery snapshots are not exposed as unauthenticated files.

## Deferred scope

Still intentionally deferred: mobile application implementation, mDNS/Bonjour discovery, QR pairing, trusted-device credentials/revocation, cloud relay, and robot-specific hardware providers.
