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



def _script_queue_controls_v6(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "script_queue", "pause_after_seconds", "REAL NOT NULL DEFAULT 0")


def _trusted_devices_v5(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS trusted_devices (
            device_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            device_type TEXT NOT NULL,
            credential_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_seen_at TEXT,
            revoked_at TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_trusted_devices_revoked "
        "ON trusted_devices(revoked_at)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_trusted_devices_last_seen "
        "ON trusted_devices(last_seen_at DESC)"
    )



def _type_to_talk_queue_v7(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS type_to_talk_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'waiting',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_type_to_talk_queue_position "
        "ON type_to_talk_queue(position,id)"
    )


def _type_to_talk_integrity_repair_v8(conn: sqlite3.Connection) -> None:
    """Self-heal the direct-speech queue for upgraded/inconsistent databases."""
    _type_to_talk_queue_v7(conn)
    # A process terminated during playback can leave an item marked playing.
    # Requeue it during migration so the next manager startup sees valid state.
    conn.execute(
        "UPDATE type_to_talk_queue SET status='waiting' WHERE status='playing'"
    )


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _type_to_talk_related_triggers(conn: sqlite3.Connection) -> list[str]:
    """Return every persistent trigger that touches the direct-speech queue.

    A legacy trigger does not have to be *attached* to type_to_talk_queue to
    break inserts into it; a trigger on another table can still reference the
    queue in its body.  Inspect the trigger SQL, not just tbl_name.
    """
    rows = conn.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL"
    ).fetchall()
    return [
        str(row[0])
        for row in rows
        if "type_to_talk_queue" in str(row[1] or "").lower()
    ]


def _read_type_to_talk_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "type_to_talk_queue" not in tables:
        return []

    columns = _columns(conn, "type_to_talk_queue")
    if "text" not in columns:
        return []

    wanted = [name for name in ("id", "text", "position", "status", "created_at") if name in columns]
    sql = "SELECT " + ",".join(_quote_identifier(name) for name in wanted) + " FROM type_to_talk_queue"
    try:
        rows = conn.execute(sql).fetchall()
    except sqlite3.DatabaseError:
        return []

    result: list[dict[str, object]] = []
    for row in rows:
        values = dict(zip(wanted, row))
        text = str(values.get("text") or "").strip()
        if not text:
            continue
        result.append(values)
    return result


def repair_type_to_talk_queue_schema(
    conn: sqlite3.Connection, *, force_rebuild: bool = False
) -> None:
    """Make the Type-to-Talk queue match the canonical production schema.

    This helper is intentionally usable both by numbered migrations and at
    runtime.  The runtime path matters because a database may already be marked
    at the current schema version while still containing a stale trigger/object
    from an interrupted or hand-copied upgrade.
    """
    required = {"id", "text", "position", "status", "created_at"}
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    exists = "type_to_talk_queue" in tables
    columns = _columns(conn, "type_to_talk_queue") if exists else set()
    trigger_names = _type_to_talk_related_triggers(conn)

    # Any trigger touching this application-managed queue is unsupported. Drop
    # it before rebuilding so even cross-table legacy triggers cannot re-break
    # the new queue.
    for trigger_name in trigger_names:
        conn.execute(f"DROP TRIGGER IF EXISTS {_quote_identifier(trigger_name)}")

    rebuild = force_rebuild or not exists or columns != required or bool(trigger_names)
    if rebuild:
        preserved = _read_type_to_talk_rows(conn) if exists else []
        conn.execute("DROP TABLE IF EXISTS type_to_talk_queue")
        _type_to_talk_queue_v7(conn)

        now = _utc_now()
        normalized: list[tuple[int | None, str, int, str, str]] = []
        for order, item in enumerate(preserved):
            raw_id = item.get("id")
            try:
                item_id = int(raw_id) if raw_id is not None and int(raw_id) > 0 else None
            except (TypeError, ValueError):
                item_id = None
            text = str(item.get("text") or "").strip()
            created_at = str(item.get("created_at") or now)
            # Playback cannot safely resume across a schema repair/restart.
            normalized.append((item_id, text, order, "waiting", created_at))

        for item_id, text, position, status, created_at in normalized:
            if item_id is None:
                conn.execute(
                    "INSERT INTO type_to_talk_queue(text,position,status,created_at) VALUES(?,?,?,?)",
                    (text, position, status, created_at),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO type_to_talk_queue(id,text,position,status,created_at) VALUES(?,?,?,?,?)",
                    (item_id, text, position, status, created_at),
                )
    else:
        conn.execute(
            "UPDATE type_to_talk_queue SET status='waiting' "
            "WHERE status NOT IN ('waiting','playing') OR status='playing'"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_type_to_talk_queue_position "
            "ON type_to_talk_queue(position,id)"
        )

    # Execute a real insert inside a savepoint, then roll it back. EXPLAIN alone
    # is not sufficient assurance for every legacy trigger/schema combination.
    conn.execute("SAVEPOINT type_to_talk_schema_probe")
    try:
        conn.execute(
            "INSERT INTO type_to_talk_queue(text,position,status,created_at) "
            "VALUES('schema-probe',2147483647,'waiting','probe')"
        )
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT type_to_talk_schema_probe")
        conn.execute("RELEASE SAVEPOINT type_to_talk_schema_probe")


def _type_to_talk_schema_reconcile_v9(conn: sqlite3.Connection) -> None:
    """Normalize legacy Type-to-Talk database objects introduced before v0.9.5."""
    repair_type_to_talk_queue_schema(conn)


def _type_to_talk_force_rebuild_v10(conn: sqlite3.Connection) -> None:
    """Force one canonical rebuild for databases already stamped schema v9.

    v0.9.5 could leave an affected installation marked v9, which prevents v9
    from ever running again.  v10 deliberately rebuilds the queue regardless of
    the stored v9 metadata and validates it with a real rolled-back INSERT.
    """
    repair_type_to_talk_queue_schema(conn, force_rebuild=True)


def _knowledge_engine_foundation_v11(conn: sqlite3.Connection) -> None:
    """Create the local-first Knowledge Engine metadata foundation.

    Phase 1 deliberately stores only canonical metadata and content blocks.
    Parsing, OCR, embeddings, vector indexes, BM25 population, and RAG prompt
    integration are introduced by later phases. Keeping the relational model
    independent of any embedding/vector provider lets a future remote backend
    reuse the same public API contract.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_libraries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE UNIQUE,
            description TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            library_id INTEGER NOT NULL REFERENCES knowledge_libraries(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            source_name TEXT NOT NULL,
            source_type TEXT NOT NULL DEFAULT 'unknown',
            mime_type TEXT,
            storage_key TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT,
            status TEXT NOT NULL DEFAULT 'registered',
            error TEXT,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            indexed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_documents_library ON knowledge_documents(library_id,id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_documents_status ON knowledge_documents(status,updated_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_documents_sha256 ON knowledge_documents(sha256)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_ingestion_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            job_type TEXT NOT NULL DEFAULT 'ingest',
            status TEXT NOT NULL DEFAULT 'queued',
            stage TEXT NOT NULL DEFAULT 'queued',
            progress REAL NOT NULL DEFAULT 0.0,
            attempts INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            queued_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_jobs_status ON knowledge_ingestion_jobs(status,queued_at,id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_jobs_document ON knowledge_ingestion_jobs(document_id,id DESC)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_parent_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            parent_block_id INTEGER REFERENCES knowledge_parent_blocks(id) ON DELETE SET NULL,
            block_type TEXT NOT NULL DEFAULT 'section',
            ordinal INTEGER NOT NULL DEFAULT 0,
            heading_path TEXT NOT NULL DEFAULT '',
            page_start INTEGER,
            page_end INTEGER,
            text TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_parent_document ON knowledge_parent_blocks(document_id,ordinal,id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_parent_parent ON knowledge_parent_blocks(parent_block_id,id)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            document_id INTEGER NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            parent_block_id INTEGER REFERENCES knowledge_parent_blocks(id) ON DELETE SET NULL,
            ordinal INTEGER NOT NULL DEFAULT 0,
            content_type TEXT NOT NULL DEFAULT 'text',
            text TEXT NOT NULL DEFAULT '',
            token_count INTEGER NOT NULL DEFAULT 0,
            page_start INTEGER,
            page_end INTEGER,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            lexical_status TEXT NOT NULL DEFAULT 'pending',
            vector_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_document ON knowledge_chunks(document_id,ordinal,id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_parent ON knowledge_chunks(parent_block_id,ordinal,id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_index_state ON knowledge_chunks(lexical_status,vector_status,id)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS agent_knowledge_libraries (
            agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            library_id INTEGER NOT NULL REFERENCES knowledge_libraries(id) ON DELETE CASCADE,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            PRIMARY KEY(agent_id,library_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_knowledge_library ON agent_knowledge_libraries(library_id,agent_id)"
    )


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "numbered_migration_foundation", _foundation_v1),
    Migration(2, "persistent_action_ledger", _persistent_action_ledger_v2),
    Migration(3, "capability_action_expiry", _capability_action_expiry_v3),
    Migration(4, "schema_recovery_foundation", _schema_recovery_foundation_v4),
    Migration(5, "trusted_mobile_devices", _trusted_devices_v5),
    Migration(6, "script_queue_controls", _script_queue_controls_v6),
    Migration(7, "type_to_talk_queue", _type_to_talk_queue_v7),
    Migration(8, "type_to_talk_integrity_repair", _type_to_talk_integrity_repair_v8),
    Migration(9, "type_to_talk_schema_reconcile", _type_to_talk_schema_reconcile_v9),
    Migration(10, "type_to_talk_force_rebuild", _type_to_talk_force_rebuild_v10),
    Migration(11, "knowledge_engine_foundation", _knowledge_engine_foundation_v11),
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
    "repair_type_to_talk_queue_schema",
    "schema_state",
]
