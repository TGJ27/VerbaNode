from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from app.api.client_contract import client_info_payload
from app.api.deps import Token
from app.api.protocol import API_VERSION, MIN_API_VERSION, PROTOCOL_VERSION, event_envelope, parse_command
from app.http import api_error_response
from app.schemas import LoginRequest
from app.state import state
from app.version import APP_VERSION

LOGGER = logging.getLogger(__name__)
router = APIRouter()


@router.post("/api/auth/login")
async def login(payload: LoginRequest, request: Request) -> JSONResponse:
    if payload.api_version is not None and not (MIN_API_VERSION <= payload.api_version <= API_VERSION):
        return api_error_response(
            request,
            status_code=409,
            code="incompatible_api_version",
            message=f"Client API version {payload.api_version} is not supported",
            extra={
                "supported_api_versions": list(range(MIN_API_VERSION, API_VERSION + 1)),
                "client_info": client_info_payload(),
            },
        )

    client_key = request.client.host if request.client else "unknown"
    result = state.controller.login(
        payload.pin,
        payload.client_name,
        client_key=client_key,
        client_type=payload.client_type,
        client_version=payload.client_version,
        api_version=payload.api_version,
    )
    if result["status"] == "rate_limited":
        retry = int(result.get("retry_after_seconds") or 1)
        return api_error_response(
            request,
            status_code=429,
            code="auth_rate_limited",
            message="Too many PIN attempts",
            extra={"status": "rate_limited", "retry_after_seconds": retry},
        )
    if result["status"] == "invalid_pin":
        extra = {"status": "invalid_pin"}
        if result.get("retry_after_seconds"):
            extra["retry_after_seconds"] = int(result["retry_after_seconds"])
        return api_error_response(
            request,
            status_code=401,
            code="invalid_pin",
            message="Incorrect PIN",
            extra=extra,
        )
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
    result.update(
        {
            "server_version": APP_VERSION,
            "api_version": API_VERSION,
            "websocket_protocol_version": PROTOCOL_VERSION,
            "session": state.controller.active_info(),
        }
    )
    return JSONResponse(result)


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


@router.get("/api/session")
async def session_info(token: Token) -> dict[str, Any]:
    return {
        "authenticated": True,
        "session": state.controller.active_info(),
        "server_version": APP_VERSION,
        "api_version": API_VERSION,
        "websocket_protocol_version": PROTOCOL_VERSION,
    }


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, ticket: str = "") -> None:
    token = state.controller.consume_ws_ticket(ticket)
    if not token:
        await websocket.close(code=4401)
        return
    await state.events.connect(token, websocket)
    await state.events.send(
        token,
        "connected",
        {
            "mode": state.conversation.mode,
            "server_version": APP_VERSION,
            "api_version": API_VERSION,
            "websocket_protocol_version": PROTOCOL_VERSION,
            "session": state.controller.active_info(),
        },
    )
    try:
        while True:
            payload = await websocket.receive_json()
            request_id = str(payload.get("request_id")) if isinstance(payload, dict) and payload.get("request_id") else None
            supplied_protocol = payload.get("protocol") if isinstance(payload, dict) else None
            if supplied_protocol is not None and supplied_protocol != PROTOCOL_VERSION:
                await websocket.send_json(
                    event_envelope(
                        "protocol_error",
                        {
                            "message": f"WebSocket protocol {supplied_protocol} is not supported",
                            "supported_protocol_version": PROTOCOL_VERSION,
                        },
                        request_id=request_id,
                    )
                )
                await websocket.close(code=4406)
                return
            command, _command_data, request_id = parse_command(payload)
            if not state.controller.validate(token):
                await websocket.send_json(event_envelope("control_revoked", {}, request_id=request_id))
                await websocket.close(code=4401)
                return
            if command == "heartbeat":
                await websocket.send_json(event_envelope("heartbeat", {"ok": True}, request_id=request_id))
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
