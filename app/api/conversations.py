from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.deps import Token
from app.api.uploads import read_upload_limited
from app.schemas import ConversationCreate, TextMessageRequest
from app.services.audio import AudioUnavailable, decode_pcm_wav
from app.state import state

router = APIRouter(tags=["conversation"])


@router.post("/api/conversation/start")
async def start_conversation(token: Token) -> dict[str, bool]:
    try:
        await state.conversation.start_conversation()
    except AudioUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/api/conversation/stop")
async def stop_conversation(token: Token) -> dict[str, bool]:
    await state.conversation.stop_conversation(stop_tts=True)
    return {"ok": True}


@router.post("/api/ptt/start")
async def start_ptt(token: Token) -> dict[str, bool]:
    await state.conversation.start_ptt()
    return {"ok": True}


@router.post("/api/ptt/stop")
async def stop_ptt(token: Token) -> dict[str, bool]:
    await state.conversation.stop_ptt()
    return {"ok": True}


@router.post("/api/ptt/cancel")
async def cancel_ptt(token: Token) -> dict[str, bool]:
    await state.conversation.cancel_ptt()
    return {"ok": True}


@router.post("/api/browser-ptt/start")
async def start_browser_ptt(token: Token) -> dict[str, bool]:
    try:
        await state.conversation.start_browser_ptt()
    except AudioUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/api/browser-ptt/audio")
async def browser_ptt_audio(
    token: Token,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    try:
        payload = await read_upload_limited(
            file,
            max_bytes=12 * 1024 * 1024,
            too_large_message="Dashboard microphone recording is too large",
        )
    except HTTPException:
        await state.conversation.cancel_browser_ptt()
        raise
    try:
        samples = decode_pcm_wav(payload, state.settings.sample_rate)
    except AudioUnavailable as exc:
        await state.conversation.cancel_browser_ptt()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    maximum_samples = int(state.settings.max_record_seconds * state.settings.sample_rate)
    if samples.size > maximum_samples:
        samples = samples[:maximum_samples]
    return await state.conversation.submit_browser_ptt(samples)


@router.post("/api/browser-ptt/cancel")
async def cancel_browser_ptt(token: Token) -> dict[str, bool]:
    await state.conversation.cancel_browser_ptt()
    return {"ok": True}


@router.post("/api/chat/send")
async def send_text(payload: TextMessageRequest, token: Token) -> dict[str, Any]:
    return await state.conversation.send_text(payload.text, payload.conversation_id)


@router.post("/api/conversations")
async def create_conversation(payload: ConversationCreate, token: Token) -> dict[str, Any]:
    return await state.conversation.new_chat(payload.title)


@router.get("/api/agents/{agent_id}/conversations")
async def list_conversations(agent_id: int, token: Token) -> list[dict[str, Any]]:
    return state.db.list_conversations(agent_id)


@router.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: int, token: Token) -> dict[str, Any]:
    conversation = state.db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation": conversation,
        "messages": state.db.list_messages(conversation_id, limit=1000),
    }


@router.delete("/api/conversations/{conversation_id}/messages")
async def clear_conversation(conversation_id: int, token: Token) -> dict[str, bool]:
    if not state.db.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    state.db.clear_conversation(conversation_id)
    await state.events.broadcast("conversation_cleared", {"conversation_id": conversation_id})
    return {"ok": True}


@router.post("/api/tts/stop")
async def stop_current_tts(token: Token) -> dict[str, bool]:
    await state.conversation.stop_current_tts()
    await state.events.broadcast("tts_stopped", {"source": "manual"})
    return {"ok": True}
