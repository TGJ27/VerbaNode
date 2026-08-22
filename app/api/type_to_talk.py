from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from fastapi import APIRouter, HTTPException

from app.api.deps import Token
from app.schemas import TypeToTalkCreate, TypeToTalkReorder, TypeToTalkSettingsUpdate
from app.services.type_to_talk_settings import get_type_to_talk_settings, save_type_to_talk_settings
from app.state import state

router = APIRouter(tags=["type-to-talk"])
LOGGER = logging.getLogger(__name__)


async def _best_effort_cleanup(label: str, operation: Callable[[], Awaitable[Any]]) -> None:
    """Interrupt competing playback without making direct speech depend on cleanup.

    Type-to-Talk is a control-plane request: stale/restarting audio subsystems may
    fail while being stopped, but that must not reject newly submitted text.
    Each cleanup operation is therefore isolated and logged independently.
    """
    try:
        await operation()
    except Exception:
        LOGGER.warning("Type-to-Talk cleanup failed: %s", label, exc_info=True)



@router.get("/api/type-to-talk")
async def get_type_to_talk(token: Token) -> dict[str, Any]:
    return {"state": state.type_to_talk.state, "items": state.db.list_type_to_talk_queue(), "settings": get_type_to_talk_settings(state.db)}


@router.patch("/api/type-to-talk/settings")
async def update_type_to_talk_settings(payload: TypeToTalkSettingsUpdate, token: Token) -> dict[str, Any]:
    settings = save_type_to_talk_settings(state.db, payload.model_dump())
    await state.events.broadcast("type_to_talk_settings", {"settings": settings})
    return settings


@router.post("/api/type-to-talk")
async def add_type_to_talk(payload: TypeToTalkCreate, token: Token) -> dict[str, Any]:
    supplied_settings = {
        key: value
        for key, value in payload.model_dump(exclude={"text"}).items()
        if value is not None
    }
    if supplied_settings:
        settings = get_type_to_talk_settings(state.db)
        settings.update(supplied_settings)
        save_type_to_talk_settings(state.db, settings)
    if state.type_to_talk.state in {"idle", "paused"}:
        # Direct speech must win the audio handoff, but accepting the text must
        # not depend on every competing subsystem shutting down perfectly. A
        # restarting Audio Engine, stale script worker, or audio-library task can
        # legitimately fail during cleanup. Isolate those failures so they are
        # logged instead of escaping as HTTP 500 to web/mobile clients.
        if state.conversation.is_conversation_running:
            await _best_effort_cleanup(
                "conversation",
                lambda: state.conversation.stop_conversation(stop_tts=True),
            )
        else:
            if getattr(state.conversation, "_ptt_active", False):
                await _best_effort_cleanup("host PTT", state.conversation.cancel_ptt)
            if getattr(state.conversation, "_browser_ptt_active", False):
                await _best_effort_cleanup(
                    "browser PTT", state.conversation.cancel_browser_ptt
                )
            await _best_effort_cleanup(
                "current TTS", state.conversation.stop_current_tts
            )
        await _best_effort_cleanup("script queue", state.script_queue.stop)
        await _best_effort_cleanup("audio library", state.audio_library.stop)
    try:
        item = await state.type_to_talk.add(payload.text)
    except Exception as exc:
        LOGGER.exception("Type-to-Talk queue rejected submitted text")
        raise HTTPException(
            status_code=503,
            detail=f"Type-to-Talk queue is unavailable: {exc}",
        ) from exc
    return item


@router.post("/api/type-to-talk/play")
async def play_type_to_talk(token: Token) -> dict[str, bool]:
    await state.type_to_talk.play()
    return {"ok": True}


@router.post("/api/type-to-talk/stop")
async def stop_type_to_talk(token: Token) -> dict[str, bool]:
    await state.type_to_talk.stop()
    return {"ok": True}


@router.delete("/api/type-to-talk")
async def clear_type_to_talk(token: Token) -> dict[str, bool]:
    await state.type_to_talk.clear()
    return {"ok": True}


@router.delete("/api/type-to-talk/{item_id}")
async def remove_type_to_talk(item_id: int, token: Token) -> dict[str, bool]:
    await state.type_to_talk.remove(item_id)
    return {"ok": True}


@router.put("/api/type-to-talk/reorder")
async def reorder_type_to_talk(payload: TypeToTalkReorder, token: Token) -> dict[str, bool]:
    try:
        await state.type_to_talk.reorder(payload.ordered_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}
