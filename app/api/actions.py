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


@router.post("/api/actions/{action_id}/cancel")
async def cancel_action(action_id: str, token: Token) -> dict[str, Any]:
    before = state.tools.action_status(action_id)
    if before is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if before.get("status") not in {"pending", "running"}:
        return {"cancelled": False, "reason": "already_terminal", "action": before}
    action = await state.tools.cancel_action(action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    if action.get("status") in {"pending", "running"}:
        raise HTTPException(
            status_code=409,
            detail="Action is active outside this VerbaNode process and cannot be cancelled here",
        )
    return {"cancelled": action.get("status") == "cancelled", "action": action}
