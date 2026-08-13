# VerbaNode v0.8.3 — Recovery Hardening

v0.8.3 focuses on database durability, upgrade safety, backup verification, and recovery. It builds on the v0.8.0 architecture foundation, v0.8.1 modularization, and v0.8.2 capability-provider foundation without expanding into mobile pairing/discovery or robot-specific hardware.

## Migration schema v4

The remaining ad-hoc legacy column upgrades have been moved into numbered migration v4. The migration registry is validated for ordered, contiguous versions and each migration runs under its own SQLite savepoint.

Databases now carry three coordinated forms of schema identity:

- the existing `settings.schema_version`
- SQLite `PRAGMA user_version`
- a `schema_migrations` history table containing version, name, fingerprint, and timestamp

VerbaNode also sets a dedicated SQLite `application_id`. A database claiming a schema newer than the running build is rejected rather than being modified by an older release.

Before an existing older database is upgraded, VerbaNode automatically creates a `pre-migration-*.db` recovery snapshot. Automatic pre-migration/pre-restore snapshots have bounded retention.

## Backup format v3

New ZIP backups record the database byte size and SHA-256 digest in `backup.json`. Restore verifies those values before accepting the database.

Restore validation now rejects unsafe ZIP paths, duplicate members, symlinks, oversized payloads, invalid SQLite databases, failed integrity checks, foreign application IDs, inconsistent schema metadata, and unsupported/newer backup formats. Existing v1/v2 VerbaNode backups remain supported when they validate successfully.

## SQLite-native backup and restore

Database snapshots now use SQLite's online backup API instead of filesystem-copying the WAL-backed database. Restore uses the same SQLite mechanism, creating a pre-restore safety snapshot first and automatically rolling back to it if replacement/migration fails.

Authenticated `GET /api/backup/status` exposes backup-format/schema status and the inventory of automatic recovery snapshots.

## Existing v0.8 platform retained

v0.8.3 retains the modular REST routers, WebSocket protocol v1, persistent action ledger/idempotency, structured API errors and request IDs, capability provider boundary, TTL/expiry, cancellation, and the single source `run.bat` workflow.

## Deferred scope

Still intentionally not included:

- mobile app
- mDNS/Bonjour LAN discovery
- QR/device pairing
- trusted-device credentials and revocation
- cloud relay / Internet remote control
- robot-specific hardware providers

## Validation

The clean v0.8.3 source tree passes **197 automated tests** and is validated with Python compilation, dashboard JavaScript syntax checks, duplicate-route checks, patch/full-source equivalence, and ZIP integrity before packaging. Windows source/EXE/installer smoke testing should still be performed on the target machine before publishing the release.
