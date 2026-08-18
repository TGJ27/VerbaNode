from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import Token
from app.schemas import QueueItemUpdate, QueueReorder, QueueSettingsUpdate, ScriptCreate
from app.state import state

router = APIRouter(tags=["scripts", "queue"])


@router.get("/api/scripts")
async def list_scripts(token: Token) -> list[dict[str, Any]]:
    return state.db.list_scripts()


@router.post("/api/scripts")
async def create_script(payload: ScriptCreate, token: Token) -> dict[str, Any]:
    script = state.db.create_script(payload.model_dump())
    await state.events.broadcast("scripts_changed", state.db.list_scripts())
    return script


@router.put("/api/scripts/{script_id}")
async def update_script(script_id: int, payload: ScriptCreate, token: Token) -> dict[str, Any]:
    script = state.db.update_script(script_id, payload.model_dump())
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    await state.events.broadcast("scripts_changed", state.db.list_scripts())
    return script


@router.delete("/api/scripts/{script_id}")
async def delete_script(script_id: int, token: Token) -> dict[str, bool]:
    if not state.db.delete_script(script_id):
        raise HTTPException(status_code=404, detail="Script not found")
    await state.events.broadcast("scripts_changed", state.db.list_scripts())
    await state.script_queue.notify()
    return {"ok": True}


@router.post("/api/scripts/{script_id}/queue")
async def queue_script(script_id: int, token: Token) -> dict[str, Any]:
    script = state.db.get_script(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    if not script.get("enabled"):
        raise HTTPException(status_code=400, detail="Script is disabled")
    return await state.script_queue.add(script_id)


@router.post("/api/scripts/{script_id}/run-now")
async def run_script_now(script_id: int, token: Token) -> dict[str, bool]:
    script = state.db.get_script(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    if not script.get("enabled"):
        raise HTTPException(status_code=400, detail="Script is disabled")
    await state.conversation.stop_conversation(stop_tts=True)
    await state.audio_library.stop()
    asyncio.create_task(state.script_queue.run_now(script_id), name=f"script-now-{script_id}")
    return {"ok": True}


@router.get("/api/queue")
async def get_queue(token: Token) -> dict[str, Any]:
    return {
        "state": state.script_queue.state,
        "loop": state.script_queue.loop_enabled,
        "items": state.db.list_queue(),
    }


@router.put("/api/queue/settings")
async def update_queue_settings(payload: QueueSettingsUpdate, token: Token) -> dict[str, Any]:
    await state.script_queue.set_loop(payload.loop)
    return {"loop": state.script_queue.loop_enabled}


@router.patch("/api/queue/{queue_id}")
async def update_queue_item(queue_id: int, payload: QueueItemUpdate, token: Token) -> dict[str, Any]:
    item = await state.script_queue.set_item_pause(queue_id, payload.pause_after_seconds)
    if item is None:
        raise HTTPException(status_code=404, detail="Queue item not found")
    return item


@router.post("/api/queue/play")
async def play_queue(token: Token) -> dict[str, bool]:
    await state.conversation.stop_conversation(stop_tts=True)
    await state.audio_library.stop()
    await state.script_queue.play()
    return {"ok": True}


@router.post("/api/queue/pause")
async def pause_queue(token: Token) -> dict[str, bool]:
    await state.script_queue.pause()
    return {"ok": True}


@router.post("/api/queue/stop")
async def stop_queue(token: Token) -> dict[str, bool]:
    await state.script_queue.stop()
    return {"ok": True}


@router.delete("/api/queue")
async def clear_queue(token: Token) -> dict[str, bool]:
    await state.script_queue.clear()
    return {"ok": True}


@router.delete("/api/queue/{queue_id}")
async def remove_queue_item(queue_id: int, token: Token) -> dict[str, bool]:
    await state.script_queue.remove(queue_id)
    return {"ok": True}


@router.put("/api/queue/reorder")
async def reorder_queue(payload: QueueReorder, token: Token) -> dict[str, bool]:
    try:
        await state.script_queue.reorder(payload.ordered_ids)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"ok": True}
