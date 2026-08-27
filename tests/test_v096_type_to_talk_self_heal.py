from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.migrations import CURRENT_SCHEMA_VERSION, apply_migrations


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
        open_browser=False,
    )


def _install_legacy_error_trigger(path: Path) -> None:
    conn = sqlite3.connect(path)
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
    conn.close()


def test_v10_runs_for_database_already_stamped_v9_and_removes_error_trigger() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO settings VALUES('schema_version','9','now')")
    conn.execute("PRAGMA user_version=9")
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

    version = apply_migrations(conn)

    assert version == CURRENT_SCHEMA_VERSION == 11
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 11
    assert conn.execute(
        "SELECT name FROM sqlite_master WHERE type='trigger' AND sql LIKE '%type_to_talk_queue%'"
    ).fetchall() == []
    conn.execute(
        "INSERT INTO type_to_talk_queue(text,position,status,created_at) VALUES('works',0,'waiting','now')"
    )
    assert conn.execute("SELECT text FROM type_to_talk_queue").fetchall() == [("works",)]


def test_database_initialize_repairs_queue_even_when_schema_metadata_is_current(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()
    assert db.schema_version() == CURRENT_SCHEMA_VERSION == 11

    _install_legacy_error_trigger(settings.db_path)

    # No migration is pending. initialize() must still repair queue health.
    reopened = Database(settings)
    reopened.initialize()
    item = reopened.add_type_to_talk("startup self-heal")

    assert item["text"] == "startup self-heal"
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND sql LIKE '%type_to_talk_queue%'"
        ).fetchall() == []


def test_send_repairs_exact_error_at_runtime_and_retries_without_restart(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()

    _install_legacy_error_trigger(settings.db_path)

    # Prove the fixture reproduces the user's exact error before the Database
    # request-time retry path handles it.
    conn = sqlite3.connect(settings.db_path)
    try:
        conn.execute(
            "INSERT INTO type_to_talk_queue(text,position,status,created_at) VALUES('raw',0,'waiting','now')"
        )
    except sqlite3.OperationalError as exc:
        assert "table type_to_talk_queue has no column named error" in str(exc)
        conn.rollback()
    else:
        raise AssertionError("legacy trigger should reproduce the reported failure")
    finally:
        conn.close()

    item = db.add_type_to_talk("runtime self-heal")

    assert item["text"] == "runtime self-heal"
    assert [row["text"] for row in db.list_type_to_talk_queue()] == ["runtime self-heal"]
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND sql LIKE '%type_to_talk_queue%'"
        ).fetchall() == []


def test_repair_removes_cross_table_trigger_that_references_queue(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()

    conn = sqlite3.connect(settings.db_path)
    conn.execute("CREATE TABLE legacy_source(id INTEGER PRIMARY KEY)")
    conn.execute(
        """
        CREATE TRIGGER legacy_cross_table AFTER INSERT ON legacy_source
        BEGIN
            INSERT INTO type_to_talk_queue(text,position,status,created_at,error)
            VALUES('legacy',0,'waiting','now',NULL);
        END
        """
    )
    conn.commit()
    conn.close()

    db.repair_type_to_talk_queue(force_rebuild=True)

    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND sql LIKE '%type_to_talk_queue%'"
        ).fetchall() == []
