from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import Token
from app.schemas import InfoCreate
from app.state import state

router = APIRouter(tags=["information"])


@router.get("/api/information")
async def list_information(token: Token) -> list[dict[str, Any]]:
    return state.db.list_information()


@router.post("/api/information")
async def create_information(payload: InfoCreate, token: Token) -> dict[str, Any]:
    item = state.db.create_information(payload.model_dump())
    await state.events.broadcast("information_changed", state.db.list_information())
    return item


@router.put("/api/information/{info_id}")
async def update_information(info_id: int, payload: InfoCreate, token: Token) -> dict[str, Any]:
    item = state.db.update_information(info_id, payload.model_dump())
    if not item:
        raise HTTPException(status_code=404, detail="Information item not found")
    await state.events.broadcast("information_changed", state.db.list_information())
    return item


@router.delete("/api/information/{info_id}")
async def delete_information(info_id: int, token: Token) -> dict[str, bool]:
    if not state.db.delete_information(info_id):
        raise HTTPException(status_code=404, detail="Information item not found")
    await state.events.broadcast("information_changed", state.db.list_information())
    return {"ok": True}
