from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.migrations import (
    CURRENT_SCHEMA_VERSION,
    MIGRATIONS,
    MigrationError,
    VERBANODE_APPLICATION_ID,
)
from app.services.backup import (
    BACKUP_FORMAT_VERSION,
    BackupError,
    create_backup_archive,
    sha256_path,
    validate_backup_archive,
)
from app.version import APP_VERSION, BUILD_LABEL


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
        open_browser=False,
    )


def test_v083_metadata_schema_identity_and_history(tmp_path: Path) -> None:
    assert APP_VERSION == "0.10.1"
    assert BUILD_LABEL == "local-mobile"
    assert CURRENT_SCHEMA_VERSION == 12
    assert BACKUP_FORMAT_VERSION == 3

    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()

    assert db.get_setting("schema_version") == "12"
    with sqlite3.connect(settings.db_path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
        assert conn.execute("PRAGMA application_id").fetchone()[0] == VERBANODE_APPLICATION_ID
        history = conn.execute(
            "SELECT version,name,fingerprint FROM schema_migrations ORDER BY version"
        ).fetchall()

    assert [row[0] for row in history] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
    assert [row[1] for row in history] == [migration.name for migration in MIGRATIONS]
    assert all(len(row[2]) == 64 for row in history)


def test_v4_normalizes_legacy_schema_and_creates_pre_migration_snapshot(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()

    # Simulate a v0.8.2 database that is missing two columns previously repaired
    # by ad-hoc logic in Database.initialize(). Migration v4 now owns that work.
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("ALTER TABLE messages DROP COLUMN stt_confidence_source")
        conn.execute("ALTER TABLE scripts DROP COLUMN tts_volume")
        conn.execute("DROP TABLE schema_migrations")
        conn.execute(
            "UPDATE settings SET value='3' WHERE key='schema_version'"
        )
        conn.execute("PRAGMA user_version=3")
        conn.execute("PRAGMA application_id=0")
        conn.commit()

    db.initialize()

    with sqlite3.connect(settings.db_path) as conn:
        message_columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        script_columns = {row[1] for row in conn.execute("PRAGMA table_info(scripts)")}
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 12
    assert "stt_confidence_source" in message_columns
    assert "tts_volume" in script_columns

    snapshots = list(settings.backup_dir.glob("pre-migration-v3-to-v12-*.db"))
    assert len(snapshots) == 1
    with sqlite3.connect(snapshots[0]) as conn:
        assert conn.execute(
            "SELECT value FROM settings WHERE key='schema_version'"
        ).fetchone()[0] == "3"
        old_message_columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    assert "stt_confidence_source" not in old_message_columns


def test_migration_refuses_newer_database_schema(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("UPDATE settings SET value='999' WHERE key='schema_version'")
        conn.execute("PRAGMA user_version=999")
        conn.commit()

    with pytest.raises(MigrationError, match="newer than this VerbaNode build"):
        db.initialize()


def test_backup_v3_manifest_has_size_and_checksum_and_validates(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()
    db.set_setting("test_backup_marker", "before")

    snapshot = db.backup_to(tmp_path / "snapshot.db")
    archive_path = tmp_path / "backup.zip"
    manifest = create_backup_archive(
        snapshot,
        archive_path,
        app_version=APP_VERSION,
        schema_version=db.schema_version(),
    )

    assert manifest["format_version"] == 3
    database_meta = manifest["database"]
    assert isinstance(database_meta, dict)
    assert database_meta["size_bytes"] == snapshot.stat().st_size
    assert database_meta["sha256"] == sha256_path(snapshot)

    validated = validate_backup_archive(archive_path, tmp_path / "extract")
    assert validated.schema_version == 12
    assert validated.sha256 == database_meta["sha256"]
    assert validated.size_bytes == database_meta["size_bytes"]


def test_backup_checksum_tampering_is_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()
    snapshot = db.backup_to(tmp_path / "snapshot.db")
    archive_path = tmp_path / "tampered.zip"
    manifest = create_backup_archive(
        snapshot,
        archive_path,
        app_version=APP_VERSION,
        schema_version=db.schema_version(),
    )
    assert isinstance(manifest["database"], dict)
    manifest["database"]["sha256"] = "0" * 64

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(snapshot, "verbanode.db")
        archive.writestr("backup.json", json.dumps(manifest))

    with pytest.raises(BackupError, match="checksum verification failed"):
        validate_backup_archive(archive_path, tmp_path / "extract")


def test_backup_archive_path_traversal_is_rejected(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("../verbanode.db", b"not-a-db")
    with pytest.raises(BackupError, match="unsafe archive path"):
        validate_backup_archive(archive_path, tmp_path / "extract")


def test_restore_uses_safety_snapshot_and_sqlite_backup_api(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()
    db.set_setting("restore_marker", "wanted")
    wanted = db.backup_to(tmp_path / "wanted.db")

    db.set_setting("restore_marker", "current-before-restore")
    safety = settings.backup_dir / "pre-restore-test.db"
    db.restore_from(wanted, safety_path=safety)

    assert db.get_setting("restore_marker") == "wanted"
    assert safety.is_file()
    with sqlite3.connect(safety) as conn:
        value = conn.execute(
            "SELECT value FROM settings WHERE key='restore_marker'"
        ).fetchone()[0]
    assert value == "current-before-restore"


def test_recovery_backup_retention_prunes_oldest(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    settings.recovery_backup_retention_count = 2
    db = Database(settings)
    db.initialize()
    for index in range(4):
        path = settings.backup_dir / f"pre-restore-{index}.db"
        path.write_bytes(str(index).encode())
        # Ensure deterministic ordering independent of filesystem timestamp resolution.
        path.touch()
        import os
        os.utime(path, (1000 + index, 1000 + index))

    db.prune_recovery_backups()
    remaining = sorted(path.name for path in settings.backup_dir.glob("pre-*.db"))
    assert remaining == ["pre-restore-2.db", "pre-restore-3.db"]


def test_existing_foreign_database_is_not_claimed_as_verbanode(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("CREATE TABLE unrelated(id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO unrelated(id) VALUES(1)")
        conn.commit()

    with pytest.raises(MigrationError, match="does not look like a VerbaNode database"):
        Database(settings).initialize()

    with sqlite3.connect(settings.db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert tables == {"unrelated"}


def test_backup_v3_requires_integrity_metadata(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()
    snapshot = db.backup_to(tmp_path / "snapshot.db")
    archive_path = tmp_path / "missing-integrity.zip"
    manifest = {
        "format_version": 3,
        "product": "VerbaNode",
        "schema_version": 4,
        "database": {"name": "verbanode.db"},
    }
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(snapshot, "verbanode.db")
        archive.writestr("backup.json", json.dumps(manifest))

    with pytest.raises(BackupError, match="integrity metadata is incomplete"):
        validate_backup_archive(archive_path, tmp_path / "extract")
