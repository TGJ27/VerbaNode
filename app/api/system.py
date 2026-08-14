from __future__ import annotations

import os
import socket
import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import FileResponse

from app.api.client_contract import client_info_payload, feature_manifest
from app.api.deps import Token
from app.api.plugins import plugin_payload
from app.api.runtime_payloads import audio_device_payload, hardware_status
from app.config import ROOT_DIR
from app.paths import CERT_DIR
from app.process_control import request_shutdown
from app.services.kokoro_voices import KOKORO_VOICES
from app.services.llm import OllamaUnavailable
from app.state import state
from app.version import APP_VERSION, BUILD_LABEL

router = APIRouter()
STATIC_DIR = ROOT_DIR / "app" / "static"

@router.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")




@router.get("/verbanode-local-ca.crt")
async def local_certificate() -> FileResponse:
    certificate = CERT_DIR / "verbanode-local-ca.crt"
    if not certificate.exists():
        raise HTTPException(status_code=404, detail="Local HTTPS certificate has not been generated")
    return FileResponse(
        certificate,
        media_type="application/x-x509-ca-cert",
        filename="verbanode-local-ca.crt",
    )


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "version": APP_VERSION, "build": BUILD_LABEL}


@router.post("/internal/launcher/shutdown")
async def launcher_shutdown(
    request: Request,
    x_verbanode_launcher_token: Annotated[
        str | None, Header(alias="X-VerbaNode-Launcher-Token")
    ] = None,
) -> dict[str, str]:
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1"}:
        raise HTTPException(status_code=403, detail="Local launcher access only")

    expected = os.environ.get("VERBANODE_LAUNCHER_SHUTDOWN_TOKEN", "")
    supplied = x_verbanode_launcher_token or ""
    if not expected or not supplied or not secrets.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Invalid launcher token")

    request_shutdown()
    return {"status": "shutting_down"}


@router.get("/health/launcher")
async def launcher_health() -> dict[str, Any]:
    """Sanitized local launcher status that does not expose controller data."""
    audio_health = state.audio_engine.health() if state.audio_engine is not None else None
    ai_health = state.ai_engine.health() if state.ai_engine is not None else None
    return {
        "status": "ok",
        "version": APP_VERSION,
        "build": BUILD_LABEL,
        "audio_engine": {
            "enabled": state.audio_engine is not None,
            "alive": bool(audio_health and audio_health.get("alive")),
            "pid": audio_health.get("pid") if audio_health else None,
        },
        "ai_engine": {
            "enabled": state.ai_engine is not None,
            "alive": bool(ai_health and ai_health.get("alive")),
            "pid": ai_health.get("pid") if ai_health else None,
        },
    }



@router.get("/api/client-info")
async def client_info() -> dict[str, Any]:
    """Public compatibility metadata for browser, CLI, and future mobile clients."""
    return client_info_payload(instance_id=state.devices.instance_id(), instance_name=socket.gethostname().strip() or "VerbaNode")

@router.get("/api/bootstrap")
async def bootstrap(token: Token) -> dict[str, Any]:
    agent = state.conversation.active_agent()
    conversation = state.conversation.active_conversation(int(agent["id"]))
    try:
        models = await state.llm.list_models()
        ollama_error = None
    except OllamaUnavailable as exc:
        models = []
        ollama_error = str(exc)
    return {
        "version": APP_VERSION,
        "build": BUILD_LABEL,
        "features": feature_manifest(),
        "kokoro_voices": KOKORO_VOICES,
        "edge_voices": state.tts.edge.cached_voice_payload(),
        "agents": state.db.list_agents(),
        "active_agent": agent,
        "conversation": conversation,
        "conversations": state.db.list_conversations(int(agent["id"])),
        "messages": state.db.list_messages(int(conversation["id"])),
        "information": state.db.list_information(),
        "scripts": state.db.list_scripts(),
        "queue": state.db.list_queue(),
        "queue_state": state.script_queue.state,
        "runtime_settings": state.db.get_runtime_settings(),
        "audio_devices": audio_device_payload(),
        "audio": {
            "input_device": state.db.get_runtime_settings().get("input_device"),
            "output_device": state.db.get_runtime_settings().get("output_device"),
            "input_locked": state.recorder.input_locked,
            "output_locked": state.player.output_locked,
            "mode": "isolated_audio_engine" if state.audio_engine is not None else "persistent_duplex_lock",
            "engine": state.audio_engine.health() if state.audio_engine is not None else None,
        },
        "ai": {
            "mode": "isolated_ai_engine" if state.ai_engine is not None else "in_process_models",
            "engine": state.ai_engine.health() if state.ai_engine is not None else None,
        },
        "mode": state.conversation.mode,
        "tts": state.tts.status(),
        "stt": state.stt.status(),
        "models": models,
        "ollama_error": ollama_error,
        "hardware": hardware_status(),
        "pipeline": state.monitor.snapshot(),
        "plugins": plugin_payload(),
        "audio_health": {
            "input": state.recorder.health(),
            "output": state.player.health(),
        },
    }

@router.get("/api/status")
async def system_status(token: Token) -> dict[str, Any]:
    runtime = state.db.get_runtime_settings()
    return {
        "mode": state.conversation.mode,
        "tts": state.tts.status(),
        "stt": state.stt.status(),
        "active_agent": state.conversation.active_agent(),
        "queue_state": state.script_queue.state,
        "controller": state.controller.active_info(),
        "hardware": hardware_status(),
        "audio": {
            "input_device": runtime.get("input_device"),
            "output_device": runtime.get("output_device"),
            "input_locked": state.recorder.input_locked,
            "output_locked": state.player.output_locked,
            "mode": "isolated_audio_engine" if state.audio_engine is not None else "persistent_duplex_lock",
            "engine": state.audio_engine.health() if state.audio_engine is not None else None,
        },
        "ai": {
            "mode": "isolated_ai_engine" if state.ai_engine is not None else "in_process_models",
            "engine": state.ai_engine.health() if state.ai_engine is not None else None,
        },
        "pipeline": state.monitor.snapshot(),
        "plugins": plugin_payload(),
        "audio_health": {
            "input": state.recorder.health(),
            "output": state.player.health(),
        },
    }


@router.get("/api/pipeline")
async def pipeline_status(token: Token) -> dict[str, Any]:
    return {
        "pipeline": state.monitor.snapshot(),
        "recent_turns": state.monitor.recent_turns(20),
        "audio": {
            "input": state.recorder.health(),
            "output": state.player.health(),
            "engine": state.audio_engine.health() if state.audio_engine is not None else None,
        },
        "ai": {
            "engine": state.ai_engine.health() if state.ai_engine is not None else None,
        },
        "stt": state.stt.status(),
        "tts": state.tts.status(),
    }

