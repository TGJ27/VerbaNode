from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone


VERBANODE_APPLICATION_ID = 0x564E4F44  # ASCII "VNOD"


class MigrationError(RuntimeError):
    """Raised when the on-disk schema cannot be safely upgraded."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    apply: Callable[[sqlite3.Connection], None]

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(f"{self.version}:{self.name}".encode("utf-8")).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _foundation_v1(_conn: sqlite3.Connection) -> None:
    """Baseline marker for databases created before numbered migrations existed."""


def _persistent_action_ledger_v2(conn: sqlite3.Connection) -> None:
    # Avoid executescript() here: it may implicitly commit and would break the
    # per-migration SAVEPOINT used by the migration runner.
    conn.execute(
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
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_ledger_created_at "
        "ON action_ledger(created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_ledger_plugin_created "
        "ON action_ledger(plugin_id, created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_ledger_status "
        "ON action_ledger(status)"
    )


def _capability_action_expiry_v3(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "action_ledger", "expires_at", "TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_action_ledger_expires_at "
        "ON action_ledger(expires_at)"
    )


def _schema_recovery_foundation_v4(conn: sqlite3.Connection) -> None:
    """Normalize legacy columns and establish durable schema identity/history."""
    # These compatibility alterations used to live in Database.initialize().
    # Keeping them here makes numbered migrations the sole schema-upgrade path.
    _add_column_if_missing(conn, "messages", "stt_confidence", "REAL")
    _add_column_if_missing(conn, "messages", "stt_confidence_source", "TEXT")
    _add_column_if_missing(conn, "agents", "max_tokens", "INTEGER NOT NULL DEFAULT 224")
    _add_column_if_missing(conn, "agents", "language", "TEXT NOT NULL DEFAULT 'en'")

    script_columns = {
        "language": "TEXT NOT NULL DEFAULT 'en'",
        "tts_mode": "TEXT NOT NULL DEFAULT 'edge'",
        "edge_voice": "TEXT NOT NULL DEFAULT 'en-US-AriaNeural'",
        "kokoro_voice_id": "INTEGER NOT NULL DEFAULT 0",
        "tts_rate": "REAL NOT NULL DEFAULT 1.0",
        "tts_volume": "REAL NOT NULL DEFAULT 1.0",
    }
    for column, declaration in script_columns.items():
        _add_column_if_missing(conn, "scripts", column, declaration)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.execute(f"PRAGMA application_id={VERBANODE_APPLICATION_ID}")


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "numbered_migration_foundation", _foundation_v1),
    Migration(2, "persistent_action_ledger", _persistent_action_ledger_v2),
    Migration(3, "capability_action_expiry", _capability_action_expiry_v3),
    Migration(4, "schema_recovery_foundation", _schema_recovery_foundation_v4),
)
CURRENT_SCHEMA_VERSION = MIGRATIONS[-1].version if MIGRATIONS else 0


def _validate_registry() -> None:
    versions = [migration.version for migration in MIGRATIONS]
    expected = list(range(1, len(MIGRATIONS) + 1))
    if versions != expected:
        raise MigrationError(
            f"Migration registry must be contiguous and ordered; got {versions}, expected {expected}"
        )
    names = [migration.name for migration in MIGRATIONS]
    if len(names) != len(set(names)):
        raise MigrationError("Migration names must be unique")


def read_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM settings WHERE key='schema_version'").fetchone()
    except sqlite3.DatabaseError:
        return 0
    try:
        return int(row[0]) if row and row[0] is not None else 0
    except (TypeError, ValueError):
        return 0


def schema_state(conn: sqlite3.Connection) -> dict[str, int]:
    stored = read_schema_version(conn)
    user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    application_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
    return {
        "schema_version": stored,
        "user_version": user_version,
        "application_id": application_id,
    }


def _record_history(conn: sqlite3.Connection, through_version: int) -> None:
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "schema_migrations" not in tables:
        return
    now = _utc_now()
    for migration in MIGRATIONS:
        if migration.version > through_version:
            break
        conn.execute(
            """
            INSERT INTO schema_migrations(version,name,fingerprint,applied_at)
            VALUES(?,?,?,?)
            ON CONFLICT(version) DO UPDATE SET
                name=excluded.name,
                fingerprint=excluded.fingerprint
            """,
            (migration.version, migration.name, migration.fingerprint, now),
        )


def apply_migrations(conn: sqlite3.Connection) -> int:
    _validate_registry()
    current = read_schema_version(conn)
    user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if current < 0 or user_version < 0:
        raise MigrationError(
            f"Invalid negative schema metadata: schema_version={current}, user_version={user_version}"
        )
    newer = max(current, user_version)
    if newer > CURRENT_SCHEMA_VERSION:
        raise MigrationError(
            f"Database schema {newer} is newer than this VerbaNode build "
            f"({CURRENT_SCHEMA_VERSION}); refusing to downgrade it"
        )
    # Pre-v0.8.3 databases legitimately have user_version=0. Once non-zero, the
    # SQLite header and settings metadata must agree.
    if current and user_version and current != user_version:
        raise MigrationError(
            f"Database schema metadata is inconsistent: settings={current}, "
            f"user_version={user_version}"
        )

    for migration in MIGRATIONS:
        if migration.version <= current:
            continue
        savepoint = f"migration_v{migration.version}"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            migration.apply(conn)
            current = migration.version
            conn.execute(
                "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                ("schema_version", str(current), _utc_now()),
            )
            conn.execute(f"PRAGMA user_version={current}")
            _record_history(conn, current)
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception as exc:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise MigrationError(
                f"Migration v{migration.version} ({migration.name}) failed"
            ) from exc

    # v4 creates migration history after older migrations may already have run.
    _record_history(conn, current)
    conn.execute(f"PRAGMA user_version={current}")
    if current >= 4:
        conn.execute(f"PRAGMA application_id={VERBANODE_APPLICATION_ID}")
    return current


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "MIGRATIONS",
    "Migration",
    "MigrationError",
    "VERBANODE_APPLICATION_ID",
    "apply_migrations",
    "read_schema_version",
    "schema_state",
]
