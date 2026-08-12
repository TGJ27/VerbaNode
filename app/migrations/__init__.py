from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _foundation_v1(_conn: sqlite3.Connection) -> None:
    """Baseline marker for databases created before numbered migrations existed."""


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "numbered_migration_foundation", _foundation_v1),
)
CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version if MIGRATIONS else 0


def apply_migrations(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
    try:
        current = int(row[0]) if row else 0
    except (TypeError, ValueError):
        current = 0

    for migration in MIGRATIONS:
        if migration.version <= current:
            continue
        migration.apply(conn)
        current = migration.version
        conn.execute(
            "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            ("schema_version", str(current), _utc_now()),
        )
    return current


__all__ = ["CURRENT_SCHEMA_VERSION", "MIGRATIONS", "Migration", "apply_migrations"]
