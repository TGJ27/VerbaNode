# VerbaNode v0.9.9 — Phase 3 Structural Hardening

v0.9.9 is a behavior-preserving structural release built on the Phase 1/2 reliability work. It reduces schema ownership duplication and makes future database changes easier to reason about without introducing a new on-disk migration.

## Structural changes

- Added `app/db_schema.py` as the canonical home for the base SQLite schema and application-managed Type-to-Talk queue contract.
- `Database.initialize()` now delegates base schema creation and startup reconciliation instead of embedding a large SQL block and queue-specific repair logic directly in `db.py`.
- Numbered migrations now reuse the same Type-to-Talk creation/repair functions as startup and request-time recovery. This removes the previous parallel schema definitions that contributed to the v0.9.3–v0.9.6 repair complexity.
- Centralized table-column inspection and the production-shaped Type-to-Talk INSERT validation in the schema module.
- Added structural regression coverage proving a fresh database and malformed legacy Type-to-Talk queue converge on the same canonical schema.

## Compatibility

- Database schema remains **v10**. There is no new database migration in this release because the on-disk schema is unchanged.
- Existing v0.9.8 databases and clients remain compatible.
- VerbaNode Android v0.4.0 is the coordinated Phase 3 mobile release.

## Upgrade

Fully stop VerbaNode Core, replace the release files, and start it again. Normal startup schema reconciliation will run, but no schema-version upgrade is required.
