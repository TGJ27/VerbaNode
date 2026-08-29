from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.api.deps import Token
from app.schemas import InfoCreate

router = APIRouter(tags=["information-compat"])


def _retired() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_410_GONE,
        detail=(
            "Legacy Information was retired in VerbaNode v0.11.1. "
            "Use Knowledge Libraries under /api/knowledge instead."
        ),
    )


@router.get("/api/information")
async def list_information(token: Token) -> list[dict[str, Any]]:
    """Compatibility response for older Android/web clients.

    The old data model is gone; returning an empty list keeps older clients from
    failing their bootstrap/read path while making it impossible to accidentally
    stream or edit legacy rows.
    """
    return []


@router.post("/api/information")
async def create_information(payload: InfoCreate, token: Token) -> dict[str, Any]:
    raise _retired()


@router.put("/api/information/{info_id}")
async def update_information(info_id: int, payload: InfoCreate, token: Token) -> dict[str, Any]:
    raise _retired()


@router.delete("/api/information/{info_id}")
async def delete_information(info_id: int, token: Token) -> dict[str, bool]:
    raise _retired()
