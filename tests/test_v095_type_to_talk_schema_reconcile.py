from __future__ import annotations

import sqlite3

from app.migrations import CURRENT_SCHEMA_VERSION, apply_migrations


def _v8_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO settings VALUES('schema_version','8','now')")
    conn.execute("PRAGMA user_version=8")
    conn.commit()
    return conn


def test_v9_removes_legacy_type_to_talk_trigger_that_writes_error_column() -> None:
    conn = _v8_connection()
    conn.execute(
        """
        CREATE TABLE type_to_talk_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'waiting',
            created_at TEXT NOT NULL
        )
        """
    )
    # Reproduces the exact production failure reported by an upgraded install:
    # "table type_to_talk_queue has no column named error".
    conn.execute(
        """
        CREATE TRIGGER legacy_type_to_talk_error AFTER INSERT ON type_to_talk_queue
        BEGIN
            INSERT INTO type_to_talk_queue(text,position,status,created_at,error)
            VALUES('legacy',0,'waiting','now',NULL);
        END
        """
    )
    conn.commit()

    try:
        conn.execute(
            "INSERT INTO type_to_talk_queue(text,position,status,created_at) "
            "VALUES('before',0,'waiting','now')"
        )
    except sqlite3.OperationalError as exc:
        assert "has no column named error" in str(exc)
    else:
        raise AssertionError("legacy trigger should reproduce the reported SQLite failure")
    conn.rollback()

    version = apply_migrations(conn)

    assert version == CURRENT_SCHEMA_VERSION >= 14
    triggers = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='type_to_talk_queue'"
    ).fetchall()
    assert triggers == []

    conn.execute(
        "INSERT INTO type_to_talk_queue(text,position,status,created_at) "
        "VALUES('after',0,'waiting','now')"
    )
    rows = conn.execute("SELECT text,status FROM type_to_talk_queue ORDER BY id").fetchall()
    assert rows == [("after", "waiting")]


def test_v9_rebuilds_malformed_queue_and_preserves_valid_text() -> None:
    conn = _v8_connection()
    conn.execute(
        "CREATE TABLE type_to_talk_queue(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT)"
    )
    conn.execute("INSERT INTO type_to_talk_queue(text) VALUES('keep me')")
    conn.execute("INSERT INTO type_to_talk_queue(text) VALUES('')")

    version = apply_migrations(conn)

    assert version == CURRENT_SCHEMA_VERSION >= 14
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(type_to_talk_queue)").fetchall()
    }
    assert {"id", "text", "position", "status", "created_at"}.issubset(columns)
    rows = conn.execute(
        "SELECT text,position,status,created_at FROM type_to_talk_queue ORDER BY id"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "keep me"
    assert rows[0][1] == 0
    assert rows[0][2] == "waiting"
    assert rows[0][3]
