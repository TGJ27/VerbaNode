from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import Token
from app.state import state

router = APIRouter(tags=["capabilities"])


@router.get("/api/capabilities")
async def capability_status(token: Token) -> dict[str, Any]:
    """Describe registered providers and currently active provider operations."""
    return state.tools.capability_status()


@router.post("/api/capabilities/actions/{operation_id}/cancel")
async def cancel_capability_operation(
    operation_id: str,
    token: Token,
) -> dict[str, Any]:
    cancelled = await state.tools.cancel_capability_operation(operation_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="Active capability operation not found")
    return {"operation_id": operation_id, "cancelled": True}


__all__ = ["router"]
