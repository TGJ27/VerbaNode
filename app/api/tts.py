from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import Token
from app.schemas import EdgeVoicePreviewRequest, ScriptTtsPreviewRequest
from app.state import state

router = APIRouter()

@router.get("/api/tts/edge-voices")
async def list_edge_voices(token: Token, refresh: bool = False) -> dict[str, Any]:
    return await state.tts.edge_voice_catalog(refresh=refresh)


@router.post("/api/tts/edge-voice-preview")
async def preview_edge_voice(
    payload: EdgeVoicePreviewRequest,
    token: Token,
) -> dict[str, Any]:
    await state.conversation.stop_conversation(stop_tts=True)
    try:
        played = await asyncio.to_thread(
            state.tts.preview_edge_voice_blocking,
            voice=payload.voice,
            text=payload.text,
            rate=payload.rate,
            volume=payload.volume,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Edge voice preview failed: {exc}") from exc
    if not played:
        raise HTTPException(status_code=503, detail="Edge voice preview was cancelled")
    return {"ok": True, "voice": payload.voice}


@router.post("/api/tts/script-preview")
async def preview_script_tts(
    payload: ScriptTtsPreviewRequest,
    token: Token,
) -> dict[str, Any]:
    await state.conversation.stop_conversation(stop_tts=True)
    agent_like = payload.model_dump()
    speech_id = state.tts.begin_speech()
    try:
        played = await asyncio.to_thread(
            state.tts.speak_blocking,
            payload.text,
            agent_like,
            speech_id,
            use_cache=False,
            cache_namespace="script-preview",
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Script voice preview failed: {exc}") from exc
    if not played:
        raise HTTPException(status_code=503, detail="Script voice preview was cancelled")
    return {
        "ok": True,
        "language": payload.language,
        "tts_mode": payload.tts_mode,
        "edge_voice": payload.edge_voice,
        "kokoro_voice_id": payload.kokoro_voice_id,
    }
