from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.api.deps import Token
from app.schemas import LoginRequest, TakeoverResponse
from app.state import state

LOGGER = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/auth/login")
async def login(payload: LoginRequest, request: Request) -> JSONResponse:
    client_key = request.client.host if request.client else "unknown"
    result = state.controller.login(
        payload.pin,
        payload.client_name,
        payload.force_takeover,
        client_key=client_key,
    )
    if result["status"] == "rate_limited":
        return JSONResponse(result, status_code=429)
    if result["status"] == "invalid_pin":
        return JSONResponse(result, status_code=401)
    old_token = result.pop("old_token", None)
    if old_token:
        await state.events.send(
            old_token,
            "control_revoked",
            {
                "reason": "automatic_takeover",
                "new_client": payload.client_name,
            },
        )
        await state.events.disconnect(old_token)
    return JSONResponse(result)


@router.get("/api/auth/takeover/{request_id}")
async def takeover_status(request_id: str) -> dict[str, Any]:
    return state.controller.pending_status(request_id)


@router.post("/api/auth/takeover/respond")
async def takeover_respond(payload: TakeoverResponse, token: Token) -> dict[str, Any]:
    result = state.controller.respond(token, payload.request_id, payload.approve)
    if result["status"] == "unauthorized":
        raise HTTPException(status_code=401, detail="Controller session is not active")
    if result["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Takeover request not found")
    old_token = result.pop("old_token", None)
    if payload.approve and old_token:
        await state.events.send(old_token, "control_revoked", {"reason": "takeover_approved"})
    return result


@router.post("/api/auth/logout")
async def logout(token: Token) -> dict[str, bool]:
    state.controller.logout(token)
    await state.events.disconnect(token)
    return {"ok": True}


@router.post("/api/auth/ws-ticket")
async def websocket_ticket(token: Token) -> dict[str, Any]:
    ticket = state.controller.create_ws_ticket(token)
    if not ticket:
        raise HTTPException(status_code=401, detail="Controller session is not active")
    return {
        "ticket": ticket,
        "expires_in": state.settings.websocket_ticket_ttl_seconds,
    }


@router.post("/api/heartbeat")
async def heartbeat(token: Token) -> dict[str, Any]:
    return {"ok": True, "active": state.controller.active_info()}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, ticket: str = "") -> None:
    token = state.controller.consume_ws_ticket(ticket)
    if not token:
        await websocket.close(code=4401)
        return
    await state.events.connect(token, websocket)
    await state.events.send(token, "connected", {"mode": state.conversation.mode})
    try:
        while True:
            payload = await websocket.receive_json()
            if not state.controller.validate(token):
                await websocket.send_json({"event": "control_revoked", "data": {}})
                await websocket.close(code=4401)
                return
            command = payload.get("command")
            if command == "heartbeat":
                await websocket.send_json({"event": "heartbeat", "data": {"ok": True}})
            elif command == "ptt_start":
                await state.conversation.start_ptt()
            elif command == "ptt_stop":
                await state.conversation.stop_ptt()
            elif command == "ptt_cancel":
                await state.conversation.cancel_ptt()
            elif command == "browser_ptt_cancel":
                await state.conversation.cancel_browser_ptt()
            elif command == "stop_tts":
                await state.conversation.stop_current_tts()
                await state.events.broadcast("tts_stopped", {"source": "manual"})
    except WebSocketDisconnect:
        await state.events.disconnect(token, websocket)
        if state.conversation.mode == "ptt":
            # A disconnected hold-to-talk controller must not leave the host mic recording.
            await asyncio.sleep(1.0)
            if not state.controller.validate(token, touch=False):
                await state.conversation.cancel_ptt()
    except Exception:
        LOGGER.exception("WebSocket client failed")
        await state.events.disconnect(token, websocket)
