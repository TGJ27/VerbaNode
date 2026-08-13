from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.api.deps import Token
from app.state import state

router = APIRouter(tags=["actions"])


@router.get("/api/actions")
async def list_actions(
    token: Token,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    return {"actions": state.tools.action_audit(limit), "limit": limit}


@router.get("/api/actions/{action_id}")
async def get_action(action_id: str, token: Token) -> dict[str, Any]:
    action = state.tools.action_status(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return action
