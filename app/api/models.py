from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import Token
from app.services.llm import OllamaUnavailable
from app.state import state

router = APIRouter(tags=["models"])


@router.get("/api/models")
async def list_models(token: Token) -> list[dict[str, Any]]:
    try:
        return await state.llm.list_models()
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/api/models/pull/{model:path}")
async def pull_model(model: str, token: Token) -> dict[str, bool]:
    async def worker() -> None:
        async def status(message: str) -> None:
            await state.events.broadcast("model_pull", {"model": model, "status": message})

        try:
            await state.llm.pull_model(model, status)
            await state.events.broadcast("models_changed", await state.llm.list_models())
        except Exception as exc:
            await state.events.broadcast("error", {"message": str(exc), "source": "model_pull"})

    asyncio.create_task(worker(), name=f"ollama-pull-{model}")
    return {"ok": True}
