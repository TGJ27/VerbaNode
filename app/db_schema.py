from __future__ import annotations

import sqlite3
from datetime import datetime, timezone


BASE_SCHEMA_SQL = r"""
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#6c63ff',
    avatar TEXT NOT NULL DEFAULT 'VA',
    role TEXT NOT NULL,
    system_prompt TEXT NOT NULL,
    greeting TEXT NOT NULL,
    llm_model TEXT NOT NULL,
    temperature REAL NOT NULL DEFAULT 0.4,
    top_p REAL NOT NULL DEFAULT 0.9,
    max_tokens INTEGER NOT NULL DEFAULT 224,
    context_size INTEGER NOT NULL DEFAULT 4096,
    language TEXT NOT NULL DEFAULT 'en',
    tts_mode TEXT NOT NULL DEFAULT 'edge_fallback',
    edge_voice TEXT NOT NULL DEFAULT 'en-US-AriaNeural',
    kokoro_voice_id INTEGER NOT NULL DEFAULT 0,
    tts_rate REAL NOT NULL DEFAULT 1.0,
    tts_volume REAL NOT NULL DEFAULT 1.0,
    stt_model TEXT NOT NULL DEFAULT 'iic/SenseVoiceSmall',
    tools_enabled TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS information (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_information (
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    info_id INTEGER NOT NULL REFERENCES information(id) ON DELETE CASCADE,
    PRIMARY KEY(agent_id, info_id)
);

CREATE TABLE IF NOT EXISTS scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    language TEXT NOT NULL DEFAULT 'en',
    tts_mode TEXT NOT NULL DEFAULT 'edge',
    edge_voice TEXT NOT NULL DEFAULT 'en-US-AriaNeural',
    kokoro_voice_id INTEGER NOT NULL DEFAULT 0,
    tts_rate REAL NOT NULL DEFAULT 1.0,
    tts_volume REAL NOT NULL DEFAULT 1.0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS script_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'waiting',
    pause_after_seconds REAL NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'chat',
    stt_confidence REAL,
    stt_confidence_source TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
CREATE INDEX IF NOT EXISTS idx_conversations_agent ON conversations(agent_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    through_message_id INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(agent_id, conversation_id)
);
"""

TYPE_TO_TALK_TABLE = "type_to_talk_queue"
TYPE_TO_TALK_COLUMNS: tuple[str, ...] = (
    "id",
    "text",
    "position",
    "status",
    "created_at",
)
TYPE_TO_TALK_COLUMN_SET = frozenset(TYPE_TO_TALK_COLUMNS)
TYPE_TO_TALK_INDEX = "idx_type_to_talk_queue_position"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    """Return SQLite column names for a trusted application table name."""
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def create_type_to_talk_queue(conn: sqlite3.Connection) -> None:
    """Create the canonical direct-speech queue and its ordering index."""
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


def _related_type_to_talk_triggers(conn: sqlite3.Connection) -> list[str]:
    """Return persistent triggers whose SQL touches the direct-speech queue."""
    rows = conn.execute(
        "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL"
    ).fetchall()
    return [
        str(row[0])
        for row in rows
        if TYPE_TO_TALK_TABLE in str(row[1] or "").lower()
    ]


def _read_type_to_talk_rows(conn: sqlite3.Connection) -> list[dict[str, object]]:
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if TYPE_TO_TALK_TABLE not in tables:
        return []

    columns = table_columns(conn, TYPE_TO_TALK_TABLE)
    if "text" not in columns:
        return []

    wanted = [name for name in TYPE_TO_TALK_COLUMNS if name in columns]
    sql = (
        "SELECT "
        + ",".join(_quote_identifier(name) for name in wanted)
        + f" FROM {TYPE_TO_TALK_TABLE}"
    )
    try:
        rows = conn.execute(sql).fetchall()
    except sqlite3.DatabaseError:
        return []

    result: list[dict[str, object]] = []
    for row in rows:
        values = dict(zip(wanted, row))
        text = str(values.get("text") or "").strip()
        if text:
            result.append(values)
    return result


def validate_type_to_talk_queue(conn: sqlite3.Connection) -> None:
    """Execute the production INSERT shape without leaving a probe row behind."""
    conn.execute("SAVEPOINT type_to_talk_schema_probe")
    try:
        conn.execute(
            "INSERT INTO type_to_talk_queue(text,position,status,created_at) "
            "VALUES('schema-probe',2147483647,'waiting','probe')"
        )
    finally:
        conn.execute("ROLLBACK TO SAVEPOINT type_to_talk_schema_probe")
        conn.execute("RELEASE SAVEPOINT type_to_talk_schema_probe")


def repair_type_to_talk_queue_schema(
    conn: sqlite3.Connection, *, force_rebuild: bool = False
) -> None:
    """Reconcile direct-speech SQLite objects with the canonical schema contract.

    This is deliberately independent of migration metadata. It can run during
    startup and at request time, which protects hand-copied or interrupted
    installations whose schema version is current but whose SQLite objects are not.
    """
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    exists = TYPE_TO_TALK_TABLE in tables
    columns = table_columns(conn, TYPE_TO_TALK_TABLE) if exists else set()
    trigger_names = _related_type_to_talk_triggers(conn)

    for trigger_name in trigger_names:
        conn.execute(f"DROP TRIGGER IF EXISTS {_quote_identifier(trigger_name)}")

    rebuild = (
        force_rebuild
        or not exists
        or columns != TYPE_TO_TALK_COLUMN_SET
        or bool(trigger_names)
    )
    if rebuild:
        preserved = _read_type_to_talk_rows(conn) if exists else []
        conn.execute(f"DROP TABLE IF EXISTS {TYPE_TO_TALK_TABLE}")
        create_type_to_talk_queue(conn)

        now = _utc_now()
        for order, item in enumerate(preserved):
            raw_id = item.get("id")
            try:
                item_id = int(raw_id) if raw_id is not None and int(raw_id) > 0 else None
            except (TypeError, ValueError):
                item_id = None
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            created_at = str(item.get("created_at") or now)
            if item_id is None:
                conn.execute(
                    "INSERT INTO type_to_talk_queue(text,position,status,created_at) "
                    "VALUES(?,?,?,?)",
                    (text, order, "waiting", created_at),
                )
            else:
                conn.execute(
                    "INSERT OR IGNORE INTO type_to_talk_queue"
                    "(id,text,position,status,created_at) VALUES(?,?,?,?,?)",
                    (item_id, text, order, "waiting", created_at),
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

    validate_type_to_talk_queue(conn)


def reconcile_runtime_schema(conn: sqlite3.Connection) -> None:
    """Run non-versioned health repairs that must remain safe on every startup."""
    repair_type_to_talk_queue_schema(conn)


__all__ = [
    "BASE_SCHEMA_SQL",
    "TYPE_TO_TALK_COLUMNS",
    "TYPE_TO_TALK_COLUMN_SET",
    "TYPE_TO_TALK_INDEX",
    "TYPE_TO_TALK_TABLE",
    "create_type_to_talk_queue",
    "reconcile_runtime_schema",
    "repair_type_to_talk_queue_schema",
    "table_columns",
    "validate_type_to_talk_queue",
]
