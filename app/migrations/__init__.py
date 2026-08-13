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


def _persistent_action_ledger_v2(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS action_ledger (
            action_id TEXT PRIMARY KEY,
            plugin_id TEXT NOT NULL,
            arguments_json TEXT NOT NULL,
            arguments_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            verified INTEGER NOT NULL DEFAULT 0,
            result_json TEXT,
            error TEXT,
            latency_ms REAL,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_action_ledger_created_at
            ON action_ledger(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_action_ledger_plugin_created
            ON action_ledger(plugin_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_action_ledger_status
            ON action_ledger(status);
        """
    )


def _capability_action_expiry_v3(conn: sqlite3.Connection) -> None:
    columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(action_ledger)").fetchall()
    }
    if "expires_at" not in columns:
        conn.execute("ALTER TABLE action_ledger ADD COLUMN expires_at TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_ledger_expires_at "
        "ON action_ledger(expires_at)"
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "numbered_migration_foundation", _foundation_v1),
    Migration(2, "persistent_action_ledger", _persistent_action_ledger_v2),
    Migration(3, "capability_action_expiry", _capability_action_expiry_v3),
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
