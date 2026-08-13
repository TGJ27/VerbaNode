from __future__ import annotations

import asyncio
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import Token
from app.migrations import CURRENT_SCHEMA_VERSION
from app.state import state
from app.version import APP_VERSION

router = APIRouter(tags=["backup"])

MAX_BACKUP_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_BACKUP_DATABASE_BYTES = 1024 * 1024 * 1024
MAX_BACKUP_MANIFEST_BYTES = 64 * 1024
BACKUP_FORMAT_VERSION = 2
_RESTORE_LOCK = asyncio.Lock()


@router.get("/api/backup")
async def create_backup(token: Token) -> FileResponse:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_zip = state.settings.backup_dir / f"verbanode-backup-{timestamp}.zip"
    backup_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        db_copy = state.db.backup_to(temp_dir / "verbanode.db")
        metadata = {
            "format_version": BACKUP_FORMAT_VERSION,
            "product": "VerbaNode",
            "app_version": APP_VERSION,
            "schema_version": CURRENT_SCHEMA_VERSION,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "database": db_copy.name,
        }
        (temp_dir / "backup.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        with zipfile.ZipFile(backup_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(db_copy, db_copy.name)
            archive.write(temp_dir / "backup.json", "backup.json")
    return FileResponse(backup_zip, filename=backup_zip.name, media_type="application/zip")


async def _stream_upload(file: UploadFile, destination: Path) -> int:
    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_BACKUP_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="Backup upload is too large")
            handle.write(chunk)
    return total


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, object]:
    try:
        manifest_info = archive.getinfo("backup.json")
    except KeyError:
        return {"format_version": 1}
    if manifest_info.file_size > MAX_BACKUP_MANIFEST_BYTES:
        raise HTTPException(status_code=413, detail="Backup manifest is too large")
    try:
        raw = archive.read(manifest_info)
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail="Backup manifest is invalid") from exc
    if not isinstance(manifest, dict):
        raise HTTPException(status_code=400, detail="Backup manifest is invalid")
    product = manifest.get("product")
    if product is not None and product != "VerbaNode":
        raise HTTPException(status_code=400, detail="Backup belongs to a different product")
    try:
        schema_version = int(manifest.get("schema_version", 0) or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Backup schema version is invalid") from exc
    if schema_version > CURRENT_SCHEMA_VERSION:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Backup schema {schema_version} is newer than this VerbaNode "
                f"installation ({CURRENT_SCHEMA_VERSION})"
            ),
        )
    return manifest


def _database_member(archive: zipfile.ZipFile, manifest: dict[str, object]) -> zipfile.ZipInfo:
    preferred = str(manifest.get("database") or "")
    candidates = [preferred, "verbanode.db", "verbanode_standalone.db"]
    for name in candidates:
        if not name:
            continue
        try:
            info = archive.getinfo(name)
        except KeyError:
            continue
        if info.is_dir():
            continue
        if info.file_size > MAX_BACKUP_DATABASE_BYTES:
            raise HTTPException(status_code=413, detail="Backup database is too large")
        return info
    raise HTTPException(status_code=400, detail="Backup database is missing")


def _validate_database(restored: Path) -> int:
    with sqlite3.connect(restored) as conn:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise HTTPException(status_code=400, detail="Backup database failed integrity check")
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"settings", "agents"}.issubset(tables):
            raise HTTPException(status_code=400, detail="Backup is not a VerbaNode database")
        schema_version = 0
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key='schema_version'"
            ).fetchone()
            schema_version = int(row[0]) if row and row[0] is not None else 0
        except (sqlite3.DatabaseError, TypeError, ValueError):
            schema_version = 0
        if schema_version > CURRENT_SCHEMA_VERSION:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Backup database schema {schema_version} is newer than this "
                    f"VerbaNode installation ({CURRENT_SCHEMA_VERSION})"
                ),
            )
        return schema_version


@router.post("/api/restore")
async def restore_backup(token: Token, file: UploadFile = File(...)) -> dict[str, bool]:
    async with _RESTORE_LOCK:
        return await _restore_backup_locked(file)


async def _restore_backup_locked(file: UploadFile) -> dict[str, bool]:
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        zip_path = temp_dir / "upload.zip"
        await _stream_upload(file, zip_path)
        try:
            with zipfile.ZipFile(zip_path) as archive:
                manifest = _read_manifest(archive)
                member = _database_member(archive, manifest)
                restored = temp_dir / "restored.db"
                with archive.open(member, "r") as source, restored.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="Invalid backup ZIP") from exc

        restored_schema = _validate_database(restored)
        manifest_schema = int(manifest.get("schema_version", 0) or 0)
        if manifest_schema and restored_schema and manifest_schema != restored_schema:
            raise HTTPException(
                status_code=400,
                detail="Backup manifest schema does not match the database",
            )

        state.settings.backup_dir.mkdir(parents=True, exist_ok=True)
        safety_path = state.settings.backup_dir / (
            f"pre-restore-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
        )
        state.db.backup_to(safety_path)

        destination = Path(state.settings.db_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        staged = destination.with_name(destination.name + ".restore.tmp")
        shutil.copy2(restored, staged)
        try:
            os.replace(staged, destination)
            state.db.initialize()
        except Exception as exc:
            try:
                shutil.copy2(safety_path, destination)
                state.db.initialize()
            except Exception:
                pass
            raise HTTPException(
                status_code=500,
                detail="Restore failed during database migration; the safety backup was restored",
            ) from exc
        finally:
            staged.unlink(missing_ok=True)

    await state.events.broadcast("reload_required", {"reason": "database_restored"})
    return {"ok": True}
