from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.db_schema import (
    BASE_SCHEMA_SQL,
    TYPE_TO_TALK_COLUMN_SET,
    repair_type_to_talk_queue_schema,
    table_columns,
)
from app.migrations import CURRENT_SCHEMA_VERSION, apply_migrations


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
    )


def test_canonical_base_schema_and_numbered_migrations_build_database() -> None:
    conn = sqlite3.connect(":memory:")
    conn.executescript(BASE_SCHEMA_SQL)
    version = apply_migrations(conn)

    assert version == CURRENT_SCHEMA_VERSION == 10
    assert table_columns(conn, "type_to_talk_queue") == TYPE_TO_TALK_COLUMN_SET
    assert conn.execute("PRAGMA user_version").fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_runtime_repair_uses_canonical_type_to_talk_contract() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE type_to_talk_queue(id INTEGER PRIMARY KEY, text TEXT, error TEXT)"
    )
    conn.execute(
        "INSERT INTO type_to_talk_queue(id,text,error) VALUES(1,'preserve me','legacy')"
    )

    repair_type_to_talk_queue_schema(conn)

    assert table_columns(conn, "type_to_talk_queue") == TYPE_TO_TALK_COLUMN_SET
    assert conn.execute(
        "SELECT id,text,position,status FROM type_to_talk_queue"
    ).fetchall() == [(1, "preserve me", 0, "waiting")]


def test_database_initialization_delegates_schema_contract(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()

    assert db.schema_version() == CURRENT_SCHEMA_VERSION
    with db.connect() as conn:
        assert table_columns(conn, "type_to_talk_queue") == TYPE_TO_TALK_COLUMN_SET
