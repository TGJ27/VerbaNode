from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import Token
from app.migrations import CURRENT_SCHEMA_VERSION
from app.services.backup import (
    BACKUP_FORMAT_VERSION,
    BackupError,
    MAX_BACKUP_UPLOAD_BYTES,
    create_backup_archive,
    recovery_backups,
    validate_backup_archive,
)
from app.state import state
from app.version import APP_VERSION

router = APIRouter(tags=["backup"])
_RESTORE_LOCK = asyncio.Lock()


def _http_error(exc: BackupError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=str(exc))


@router.get("/api/backup/status")
async def backup_status(token: Token) -> dict[str, object]:
    return {
        "format_version": BACKUP_FORMAT_VERSION,
        "schema_version": state.db.schema_version(),
        "current_schema_version": CURRENT_SCHEMA_VERSION,
        "recovery_backups": recovery_backups(state.settings.backup_dir),
    }


@router.get("/api/backup")
async def create_backup(token: Token) -> FileResponse:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_zip = state.settings.backup_dir / f"verbanode-backup-{timestamp}.zip"
    backup_zip.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        db_copy = state.db.backup_to(temp_dir / "verbanode.db")
        create_backup_archive(
            db_copy,
            backup_zip,
            app_version=APP_VERSION,
            schema_version=state.db.schema_version(),
        )
    return FileResponse(backup_zip, filename=backup_zip.name, media_type="application/zip")


async def _stream_upload(file: UploadFile, destination: Path) -> int:
    total = 0
    try:
        with destination.open("wb") as handle:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_BACKUP_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Backup upload is too large")
                handle.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return total


@router.post("/api/restore")
async def restore_backup(token: Token, file: UploadFile = File(...)) -> dict[str, object]:
    async with _RESTORE_LOCK:
        return await _restore_backup_locked(file)


async def _restore_backup_locked(file: UploadFile) -> dict[str, object]:
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        zip_path = temp_dir / "upload.zip"
        await _stream_upload(file, zip_path)
        try:
            validated = validate_backup_archive(zip_path, temp_dir)
        except BackupError as exc:
            raise _http_error(exc) from exc

        state.settings.backup_dir.mkdir(parents=True, exist_ok=True)
        safety_path = state.settings.backup_dir / (
            f"pre-restore-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')}.db"
        )
        try:
            state.db.restore_from(validated.database_path, safety_path=safety_path)
            state.db.prune_recovery_backups()
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    "Restore failed during database replacement or migration; "
                    "the pre-restore safety backup was restored"
                ),
            ) from exc

    await state.events.broadcast("reload_required", {"reason": "database_restored"})
    return {
        "ok": True,
        "schema_version": state.db.schema_version(),
        "restored_sha256": validated.sha256,
        "safety_backup": safety_path.name,
    }
