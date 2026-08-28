from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import Settings
from app.db import Database
from app.migrations import CURRENT_SCHEMA_VERSION, MIGRATIONS, read_schema_version


def _database(tmp_path: Path) -> Database:
    settings = Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
        knowledge_path=tmp_path / "knowledge",
        open_browser=False,
    )
    db = Database(settings)
    db.initialize()
    return db


def test_canonical_base_schema_and_numbered_migrations_build_database(tmp_path: Path) -> None:
    """Schema assertions must follow the migration registry, not a stale literal."""
    db = _database(tmp_path)
    assert db.schema_version() == CURRENT_SCHEMA_VERSION
    assert CURRENT_SCHEMA_VERSION == MIGRATIONS[-1].version
    assert [migration.version for migration in MIGRATIONS] == list(
        range(1, CURRENT_SCHEMA_VERSION + 1)
    )


def test_current_schema_version_is_persisted_in_settings(tmp_path: Path) -> None:
    db = _database(tmp_path)
    with sqlite3.connect(db.path) as conn:
        assert read_schema_version(conn) == CURRENT_SCHEMA_VERSION


def test_current_schema_contains_knowledge_engine_tables(tmp_path: Path) -> None:
    db = _database(tmp_path)
    with sqlite3.connect(db.path) as conn:
        tables = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
            ).fetchall()
        }
    assert {
        "knowledge_libraries",
        "knowledge_documents",
        "knowledge_ingestion_jobs",
        "knowledge_parent_blocks",
        "knowledge_chunks",
        "knowledge_table_rows",
        "knowledge_vector_records",
        "knowledge_index_metadata",
        "agent_knowledge_libraries",
    } <= tables
