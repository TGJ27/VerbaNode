from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import Token
from app.schemas import TypeToTalkCreate, TypeToTalkReorder
from app.state import state

router = APIRouter(tags=["type-to-talk"])


@router.get("/api/type-to-talk")
async def get_type_to_talk(token: Token) -> dict[str, Any]:
    return {"state": state.type_to_talk.state, "items": state.db.list_type_to_talk_transcript(), "defaults": state.type_to_talk.defaults()}


@router.post("/api/type-to-talk")
async def add_type_to_talk(payload: TypeToTalkCreate, token: Token) -> dict[str, Any]:
    if state.type_to_talk.state in {"idle", "paused"}:
        await state.conversation.stop_conversation(stop_tts=True)
        await state.script_queue.stop()
        await state.audio_library.stop()
    item = await state.type_to_talk.add(payload.text, payload.model_dump(exclude={"text"}, exclude_none=True))
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
