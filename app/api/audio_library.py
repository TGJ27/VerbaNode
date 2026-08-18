from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.deps import Token
from app.api.uploads import read_upload_limited
from app.services.audio_library import AudioLibraryError
from app.state import state

router = APIRouter(tags=["audio-library"])


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail="Audio file not found")
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/api/audio-library")
async def list_audio_library(token: Token) -> dict[str, Any]:
    return {
        "items": state.audio_library.list_files(),
        "playing": state.audio_library.playing_name,
        "allowed_extensions": [".mp3", ".wav"],
        "max_upload_bytes": state.settings.audio_library_max_upload_bytes,
    }


@router.post("/api/audio-library/upload")
async def upload_audio(token: Token, file: UploadFile = File(...)) -> dict[str, Any]:
    filename = file.filename or "audio"
    try:
        payload = await read_upload_limited(
            file,
            max_bytes=state.settings.audio_library_max_upload_bytes,
            too_large_message="Audio upload is too large",
        )
        item = state.audio_library.save(filename, payload)
    except AudioLibraryError as exc:
        raise _error(exc) from exc
    await state.events.broadcast("audio_library_changed", {"items": state.audio_library.list_files()})
    return item


@router.post("/api/audio-library/{name:path}/play")
async def play_audio(name: str, token: Token) -> dict[str, bool]:
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()
    try:
        await state.audio_library.play(name)
    except (AudioLibraryError, FileNotFoundError) as exc:
        raise _error(exc) from exc
    return {"ok": True}


@router.post("/api/audio-library/stop")
async def stop_audio(token: Token) -> dict[str, bool]:
    await state.audio_library.stop()
    return {"ok": True}


@router.patch("/api/audio-library/{name:path}")
async def rename_audio(name: str, payload: dict[str, str], token: Token) -> dict[str, Any]:
    new_name = str(payload.get("name") or "").strip()
    if not new_name:
        raise HTTPException(status_code=422, detail="Audio filename is required")
    try:
        item = state.audio_library.rename(name, new_name)
    except (AudioLibraryError, FileNotFoundError) as exc:
        raise _error(exc) from exc
    await state.events.broadcast("audio_library_changed", {"items": state.audio_library.list_files()})
    return item


@router.delete("/api/audio-library/{name:path}")
async def delete_audio(name: str, token: Token) -> dict[str, bool]:
    try:
        deleted = await state.audio_library.delete(name)
    except AudioLibraryError as exc:
        raise _error(exc) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Audio file not found")
    return {"ok": True}
