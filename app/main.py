from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import ROOT_DIR
from app.schemas import (
    AgentCreate,
    AgentUpdate,
    AudioDeviceTestRequest,
    ConversationCreate,
    ConversationSettingsUpdate,
    DiagnosticsSoakRequest,
    InfoCreate,
    LoginRequest,
    PluginStateUpdate,
    QueueReorder,
    RoleGenerateRequest,
    ScriptCreate,
    TakeoverResponse,
    TextMessageRequest,
)
from app.services.kokoro_voices import KOKORO_VOICES
from app.services.audio import AudioUnavailable, decode_pcm_wav
from app.services.llm import OllamaUnavailable
from app.version import APP_VERSION, BUILD_LABEL
from app.runtime import install_asyncio_exception_filter
from app.state import state

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
LOGGER = logging.getLogger(__name__)

app = FastAPI(title="VerbaNode Standalone", version=APP_VERSION)
STATIC_DIR = ROOT_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")



@app.on_event("startup")
async def startup_event() -> None:
    install_asyncio_exception_filter()
    state.diagnostics.install_logging()
    LOGGER.info("Diagnostics recorder initialized for VerbaNode %s", APP_VERSION)
    try:
        if state.audio_engine is not None:
            await asyncio.to_thread(state.audio_engine.start)
        await asyncio.to_thread(state.reconcile_audio_devices)
    except AudioUnavailable as exc:
        # Keep the management UI online so the user can inspect settings and
        # retry device operations even when the child process cannot start.
        LOGGER.error("Audio initialization failed: %s", exc)
    try:
        if state.ai_engine is not None:
            await asyncio.to_thread(state.ai_engine.start)
    except Exception as exc:
        # Text chat, Edge TTS, tools, memory, and the management UI remain
        # available even when local model isolation cannot start.
        LOGGER.error("AI Engine initialization failed: %s", exc)


@app.middleware("http")
async def disable_ui_caching(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.on_event("shutdown")
async def shutdown_event() -> None:
    state.diagnostics.shutdown()
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()
    if state.ai_engine is not None:
        await asyncio.to_thread(state.ai_engine.stop)
    await state.tools.shutdown_plugins()
    if state.audio_engine is not None:
        await asyncio.to_thread(state.audio_engine.stop)
    else:
        await asyncio.to_thread(state.recorder.close)
        await asyncio.to_thread(state.player.close)


def require_token(
    x_session_token: Annotated[str | None, Header()] = None,
) -> str:
    if not state.controller.validate(x_session_token):
        raise HTTPException(status_code=401, detail="Controller session is not active")
    return str(x_session_token)


Token = Annotated[str, Depends(require_token)]


@app.get("/")
async def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")




@app.get("/verbanode-local-ca.crt")
async def local_certificate() -> FileResponse:
    certificate = ROOT_DIR / "certs" / "verbanode-local-ca.crt"
    if not certificate.exists():
        raise HTTPException(status_code=404, detail="Local HTTPS certificate has not been generated")
    return FileResponse(
        certificate,
        media_type="application/x-x509-ca-cert",
        filename="verbanode-local-ca.crt",
    )


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "version": app.version, "build": BUILD_LABEL}


# Authentication and single-controller takeover
@app.post("/api/auth/login")
async def login(payload: LoginRequest) -> JSONResponse:
    result = state.controller.login(payload.pin, payload.client_name, payload.force_takeover)
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


@app.get("/api/auth/takeover/{request_id}")
async def takeover_status(request_id: str) -> dict[str, Any]:
    return state.controller.pending_status(request_id)


@app.post("/api/auth/takeover/respond")
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


@app.post("/api/auth/logout")
async def logout(token: Token) -> dict[str, bool]:
    state.controller.logout(token)
    await state.events.disconnect(token)
    return {"ok": True}


@app.post("/api/heartbeat")
async def heartbeat(token: Token) -> dict[str, Any]:
    return {"ok": True, "active": state.controller.active_info()}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = "") -> None:
    if not state.controller.validate(token):
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


# Bootstrap and status
def audio_device_payload() -> dict[str, Any]:
    devices = state.recorder.list_devices()
    inputs = [device for device in devices if device.get("max_input_channels", 0) > 0]
    outputs = [device for device in devices if device.get("max_output_channels", 0) > 0]

    def preferred(devices_to_rank: list[dict[str, Any]], marker: str) -> int | None:
        api_score = {
            "windows wasapi": 100,
            "windows directsound": 75,
            "mme": 55,
            "windows wdm-ks": 40,
        }
        candidates = [
            device
            for device in devices_to_rank
            if marker in str(device.get("name", "")).lower()
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda device: api_score.get(str(device.get("hostapi", "")).lower(), 0),
            reverse=True,
        )
        return int(candidates[0]["id"])

    recommended_input = preferred(inputs, "dji mic")
    recommended_output = preferred(outputs, "jyx")
    for device in inputs:
        device["recommended_input"] = device["id"] == recommended_input
        device["fingerprint"] = state.recorder.device_fingerprint(device, "input")
    for device in outputs:
        device["recommended_output"] = device["id"] == recommended_output
        device["fingerprint"] = state.recorder.device_fingerprint(device, "output")

    return {
        "inputs": inputs,
        "outputs": outputs,
        "recommended_input": recommended_input,
        "recommended_output": recommended_output,
    }


@app.get("/api/bootstrap")
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
        "features": {
            "diagnostics": True,
            "diagnostics_api_version": 1,
            "plugin_manager": True,
            "plugin_manager_api_version": 2,
            "external_plugins": True,
        },
        "kokoro_voices": KOKORO_VOICES,
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


def plugin_payload() -> dict[str, Any]:
    """Return dashboard-safe metadata and runtime metrics for all plugins."""
    usage: Counter[str] = Counter()
    agents = state.db.list_agents()
    for agent in agents:
        usage.update(str(item) for item in agent.get("tools_enabled", []))

    plugins: list[dict[str, Any]] = []
    for item in state.tools.plugin_health():
        plugin = dict(item)
        plugin["agent_count"] = int(usage.get(plugin["id"], 0))
        plugin["agent_total"] = len(agents)
        plugins.append(plugin)

    summary = state.tools.plugin_summary()
    summary["agent_assignments"] = sum(usage.values())
    return {
        "sdk": "verbanode-plugins/1",
        "external_plugins_supported": True,
        "external_plugins_directory": str(state.tools.external_plugins_directory()),
        "plugins": plugins,
        "summary": summary,
    }


def persist_plugin_state() -> None:
    payload = json.dumps(state.tools.disabled_plugin_ids(), separators=(",", ":"))
    state.db.set_setting("disabled_plugins", payload)
    # Retain the Phase 2 key so downgrades still preserve built-in choices.
    state.db.set_setting("disabled_builtin_plugins", payload)


def hardware_status() -> dict[str, Any]:
    try:
        import psutil

        memory = psutil.virtual_memory()
        return {
            "cpu_count": psutil.cpu_count(logical=True),
            "ram_total_gb": round(memory.total / (1024**3), 1),
            "ram_available_gb": round(memory.available / (1024**3), 1),
        }
    except Exception:
        return {}


def _safe_component_health(callback, fallback: dict[str, Any]) -> dict[str, Any]:
    try:
        value = callback()
        return dict(value) if isinstance(value, dict) else fallback
    except Exception as exc:
        return {**fallback, "error": str(exc)}


def diagnostics_snapshot() -> dict[str, Any]:
    runtime = state.db.get_runtime_settings()
    audio_engine = (
        _safe_component_health(state.audio_engine.health, {"alive": False})
        if state.audio_engine is not None
        else {"mode": "in_process", "alive": True, "pid": os.getpid()}
    )
    ai_engine = (
        _safe_component_health(state.ai_engine.health, {"alive": False})
        if state.ai_engine is not None
        else {"mode": "in_process", "alive": True, "pid": os.getpid()}
    )
    audio_input = _safe_component_health(state.recorder.health, {"input_locked": False})
    audio_output = _safe_component_health(state.player.health, {"output_locked": False})
    resources = state.diagnostics.resource_snapshot(
        core_pid=os.getpid(),
        audio_pid=audio_engine.get("pid"),
        ai_pid=ai_engine.get("pid"),
    )
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "environment": state.diagnostics.environment(),
        "resources": resources,
        "mode": state.conversation.mode,
        "queue_state": state.script_queue.state,
        "controller": state.controller.active_info(),
        "runtime_settings": {
            "input_device": runtime.get("input_device"),
            "output_device": runtime.get("output_device"),
            "silence_ms": runtime.get("silence_ms"),
            "max_record_seconds": runtime.get("max_record_seconds"),
            "stt_confidence_threshold": runtime.get("stt_confidence_threshold"),
        },
        "pipeline": state.monitor.snapshot(),
        "audio": {
            "engine": audio_engine,
            "input": audio_input,
            "output": audio_output,
        },
        "ai": {"engine": ai_engine},
        "stt": _safe_component_health(state.stt.status, {}),
        "tts": _safe_component_health(state.tts.status, {}),
        "plugins": plugin_payload(),
    }


def diagnostics_soak_sample() -> dict[str, Any]:
    snapshot = diagnostics_snapshot()
    resources = snapshot.get("resources", {})
    audio_engine = snapshot.get("audio", {}).get("engine", {})
    ai_engine = snapshot.get("ai", {}).get("engine", {})
    pipeline = snapshot.get("pipeline", {})
    return {
        "system": resources.get("system", {}),
        "processes": resources.get("processes", {}),
        "pipeline_state": pipeline.get("state"),
        "pipeline_errors": pipeline.get("counters", {}).get("errors", 0),
        "turns_completed": pipeline.get("counters", {}).get("turns_completed", 0),
        "audio_alive": audio_engine.get("alive"),
        "audio_restart_count": audio_engine.get("restart_count", 0),
        "audio_heartbeat_age_seconds": audio_engine.get("seconds_since_heartbeat"),
        "ai_alive": ai_engine.get("alive"),
        "ai_restart_count": ai_engine.get("restart_count", 0),
        "ai_heartbeat_age_seconds": ai_engine.get("heartbeat_age_seconds"),
        "asr_inflight": ai_engine.get("inflight", {}).get("asr", 0),
        "kokoro_inflight": ai_engine.get("inflight", {}).get("kokoro", 0),
        "input_locked": snapshot.get("audio", {}).get("input", {}).get("input_locked"),
        "output_locked": snapshot.get("audio", {}).get("output", {}).get("output_locked"),
    }


def _diagnostic_check(name: str, status: str, detail: str, duration_ms: int = 0) -> dict[str, Any]:
    return {
        "name": name,
        "status": status,
        "detail": str(detail),
        "duration_ms": max(0, int(duration_ms)),
    }


async def run_diagnostics_self_test() -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    async def measured(name: str, callback, *, warning: bool = False) -> None:
        started = asyncio.get_running_loop().time()
        try:
            detail = await callback()
            status = "warn" if warning else "pass"
        except Exception as exc:
            detail = str(exc)
            status = "fail"
        checks.append(
            _diagnostic_check(
                name,
                status,
                str(detail),
                round((asyncio.get_running_loop().time() - started) * 1000),
            )
        )

    async def database_check() -> str:
        def query() -> str:
            with state.db.connect() as conn:
                value = conn.execute("SELECT 1").fetchone()[0]
            return "SQLite read/write connection is healthy" if value == 1 else "Unexpected SQLite result"
        return await asyncio.to_thread(query)

    async def directories_check() -> str:
        def write_probe() -> str:
            paths = [
                state.settings.db_path.parent,
                state.settings.runtime_audio_dir,
                state.settings.tts_cache_dir,
                state.settings.diagnostics_dir,
            ]
            for directory in paths:
                directory.mkdir(parents=True, exist_ok=True)
                probe = directory / ".verbanode-write-test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
            return f"{len(paths)} runtime directories are writable"
        return await asyncio.to_thread(write_probe)

    async def audio_engine_check() -> str:
        if state.audio_engine is None:
            return "Audio Engine isolation is disabled; compatibility mode is active"
        health = await asyncio.to_thread(state.audio_engine.health)
        if not health.get("alive"):
            raise RuntimeError("Audio Engine process is not alive")
        heartbeat = health.get("seconds_since_heartbeat")
        if heartbeat is not None and float(heartbeat) > 10:
            raise RuntimeError(f"Audio Engine heartbeat is stale ({heartbeat}s)")
        return f"Audio Engine PID {health.get('pid')} is responsive"

    async def audio_devices_check() -> str:
        devices = await asyncio.to_thread(state.recorder.list_devices)
        inputs = sum(1 for device in devices if int(device.get("max_input_channels", 0)) > 0)
        outputs = sum(1 for device in devices if int(device.get("max_output_channels", 0)) > 0)
        if inputs < 1 or outputs < 1:
            raise RuntimeError(f"Found {inputs} input and {outputs} output endpoints")
        return f"Found {inputs} input and {outputs} output endpoints"

    async def ai_engine_check() -> str:
        if state.ai_engine is None:
            return "AI Engine isolation is disabled; compatibility mode is active"
        health = await asyncio.to_thread(state.ai_engine.health)
        if not health.get("alive"):
            raise RuntimeError("AI Engine process is not alive")
        heartbeat = health.get("heartbeat_age_seconds")
        if heartbeat is not None and float(heartbeat) > 10:
            raise RuntimeError(f"AI Engine heartbeat is stale ({heartbeat}s)")
        remote = health.get("remote") or {}
        asr_state = (remote.get("asr") or {}).get("state", "unknown")
        return f"AI Engine PID {health.get('pid')} is responsive; SenseVoice state is {asr_state}"

    async def ollama_check() -> str:
        models = await state.llm.list_models()
        return f"Ollama is reachable with {len(models)} local model(s)"

    async def pipeline_check() -> str:
        pipeline = state.monitor.snapshot()
        if pipeline.get("state") == "error":
            raise RuntimeError(str(pipeline.get("last_error") or "Pipeline is in error state"))
        return f"Pipeline state is {pipeline.get('state', 'unknown')}"

    async def plugin_manager_check() -> str:
        payload = plugin_payload()
        summary = payload["summary"]
        if summary["loaded"] < 1:
            raise RuntimeError("No plugins are loaded")
        failed = [
            item["name"]
            for item in payload["plugins"]
            if item["status"] in {"error", "load_error"}
        ]
        if failed:
            raise RuntimeError("Plugin errors: " + ", ".join(failed))
        return (
            f"{summary['enabled']} of {summary['loaded']} loaded plugins enabled; "
            f"{summary['external']} external"
        )

    await measured("Database", database_check)
    await measured("Runtime directories", directories_check)
    await measured("Audio Engine", audio_engine_check, warning=state.audio_engine is None)
    await measured("Windows audio endpoints", audio_devices_check)
    await measured("AI Engine", ai_engine_check, warning=state.ai_engine is None)
    await measured("Ollama", ollama_check)
    await measured("Plugin Manager", plugin_manager_check)
    await measured("Conversation pipeline", pipeline_check)

    failures = sum(1 for check in checks if check["status"] == "fail")
    warnings = sum(1 for check in checks if check["status"] == "warn")
    overall = "fail" if failures else "warn" if warnings else "pass"
    result = {
        "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "overall": overall,
        "failures": failures,
        "warnings": warnings,
        "checks": checks,
    }
    state.diagnostics.set_last_self_test(result)
    return result


@app.get("/api/status")
async def system_status(token: Token) -> dict[str, Any]:
    runtime = state.db.get_runtime_settings()
    return {
        "mode": state.conversation.mode,
        "tts": state.tts.status(),
        "stt": state.stt.status(),
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


@app.get("/api/pipeline")
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


@app.get("/api/diagnostics")
async def diagnostics_status(token: Token) -> dict[str, Any]:
    snapshot = await asyncio.to_thread(diagnostics_snapshot)
    return {
        "snapshot": snapshot,
        "recent_turns": state.monitor.recent_turns(20),
        "recent_logs": state.diagnostics.logs(limit=80),
        "self_test": state.diagnostics.last_self_test(),
        "soak": state.diagnostics.soak_status(include_samples=False),
    }


@app.post("/api/diagnostics/self-test")
async def diagnostics_self_test(token: Token) -> dict[str, Any]:
    return await run_diagnostics_self_test()


@app.get("/api/diagnostics/logs")
async def diagnostics_logs(
    token: Token,
    limit: int = 200,
    minimum_level: str | None = None,
) -> dict[str, Any]:
    return {
        "entries": state.diagnostics.logs(limit=limit, minimum_level=minimum_level),
        "capacity": state.diagnostics.log_handler.capacity,
    }


@app.delete("/api/diagnostics/logs")
async def clear_diagnostics_logs(token: Token) -> dict[str, bool]:
    state.diagnostics.clear_logs()
    LOGGER.info("Diagnostics log buffer cleared from the dashboard")
    return {"ok": True}


@app.delete("/api/diagnostics/turns")
async def clear_diagnostics_turns(token: Token) -> dict[str, bool]:
    state.monitor.clear_history()
    return {"ok": True}


@app.get("/api/diagnostics/export")
async def export_diagnostics(token: Token) -> FileResponse:
    snapshot = await asyncio.to_thread(diagnostics_snapshot)
    path = await asyncio.to_thread(
        state.diagnostics.create_report,
        snapshot,
        recent_turns=state.monitor.recent_turns(100),
        self_test=state.diagnostics.last_self_test(),
    )
    return FileResponse(path, filename=path.name, media_type="application/zip")


@app.post("/api/diagnostics/soak/start")
async def start_diagnostics_soak(
    payload: DiagnosticsSoakRequest,
    token: Token,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            state.diagnostics.start_soak,
            diagnostics_soak_sample,
            duration_seconds=payload.duration_minutes * 60,
            interval_seconds=payload.interval_seconds,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/diagnostics/soak/stop")
async def stop_diagnostics_soak(token: Token) -> dict[str, Any]:
    return await asyncio.to_thread(state.diagnostics.stop_soak)


@app.get("/api/diagnostics/soak")
async def diagnostics_soak_status(token: Token) -> dict[str, Any]:
    return state.diagnostics.soak_status(include_samples=False)


# Plugins
@app.get("/api/plugins")
async def list_plugins(token: Token) -> dict[str, Any]:
    return plugin_payload()


@app.put("/api/plugins/{plugin_id}")
async def update_plugin_state(
    plugin_id: str,
    payload: PluginStateUpdate,
    token: Token,
) -> dict[str, Any]:
    try:
        state.tools.set_plugin_enabled(plugin_id, payload.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Plugin not found") from exc
    persist_plugin_state()
    result = plugin_payload()
    await state.events.broadcast("plugins_changed", result)
    return result




@app.post("/api/plugins/reload")
async def reload_external_plugins(token: Token) -> dict[str, Any]:
    await state.tools.reload_external_plugins()
    result = plugin_payload()
    await state.events.broadcast("plugins_changed", result)
    return result


@app.post("/api/plugins/{plugin_id}/reload")
async def reload_external_plugin(plugin_id: str, token: Token) -> dict[str, Any]:
    try:
        await state.tools.reload_external_plugins(plugin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="External plugin not found") from exc
    result = plugin_payload()
    await state.events.broadcast("plugins_changed", result)
    return result

@app.post("/api/plugins/reset-metrics")
async def reset_all_plugin_metrics(token: Token) -> dict[str, Any]:
    state.tools.reset_plugin_metrics()
    result = plugin_payload()
    await state.events.broadcast("plugins_changed", result)
    return result


@app.post("/api/plugins/{plugin_id}/reset-metrics")
async def reset_one_plugin_metrics(plugin_id: str, token: Token) -> dict[str, Any]:
    try:
        state.tools.reset_plugin_metrics(plugin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Plugin not found") from exc
    result = plugin_payload()
    await state.events.broadcast("plugins_changed", result)
    return result


# Agents
@app.get("/api/agents")
async def list_agents(token: Token) -> list[dict[str, Any]]:
    return state.db.list_agents()


@app.post("/api/agents")
async def create_agent(payload: AgentCreate, token: Token) -> dict[str, Any]:
    agent = state.db.create_agent(payload.model_dump())
    await state.events.broadcast("agents_changed", state.db.list_agents())
    return agent


@app.put("/api/agents/{agent_id}")
async def update_agent(agent_id: int, payload: AgentUpdate, token: Token) -> dict[str, Any]:
    agent = state.db.update_agent(agent_id, payload.model_dump())
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await state.events.broadcast("agents_changed", state.db.list_agents())
    return agent


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: int, token: Token) -> dict[str, bool]:
    try:
        deleted = state.db.delete_agent(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    await state.events.broadcast("agents_changed", state.db.list_agents())
    return {"ok": True}


@app.post("/api/agents/{agent_id}/activate")
async def activate_agent(agent_id: int, token: Token) -> dict[str, Any]:
    return await state.conversation.switch_agent(agent_id)


@app.post("/api/agents/generate-role")
async def generate_role(payload: RoleGenerateRequest, token: Token) -> dict[str, str]:
    try:
        return await state.llm.generate_role(payload.description, payload.model)
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.delete("/api/agents/{agent_id}/memory")
async def clear_agent_memory(agent_id: int, token: Token) -> dict[str, bool]:
    if not state.db.get_agent(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    state.db.clear_agent_memory(agent_id)
    await state.events.broadcast("memory_updated", {"agent_id": agent_id, "cleared": True})
    return {"ok": True}


@app.get("/api/agents/{agent_id}/backup")
async def backup_agent(agent_id: int, token: Token) -> JSONResponse:
    agent = state.db.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    conversations = state.db.list_conversations(agent_id)
    data = {
        "version": 1,
        "exported_at": datetime.now().isoformat(timespec="seconds"),
        "agent": agent,
        "information": [
            item for item in state.db.list_information() if item["id"] in agent["info_ids"]
        ],
        "conversations": [
            {**conversation, "messages": state.db.list_messages(int(conversation["id"]), limit=100000)}
            for conversation in conversations
        ],
    }
    filename = f"agent-{agent_id}-backup.json"
    return JSONResponse(
        data,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Information
@app.get("/api/information")
async def list_information(token: Token) -> list[dict[str, Any]]:
    return state.db.list_information()


@app.post("/api/information")
async def create_information(payload: InfoCreate, token: Token) -> dict[str, Any]:
    item = state.db.create_information(payload.model_dump())
    await state.events.broadcast("information_changed", state.db.list_information())
    return item


@app.put("/api/information/{info_id}")
async def update_information(info_id: int, payload: InfoCreate, token: Token) -> dict[str, Any]:
    item = state.db.update_information(info_id, payload.model_dump())
    if not item:
        raise HTTPException(status_code=404, detail="Information item not found")
    await state.events.broadcast("information_changed", state.db.list_information())
    return item


@app.delete("/api/information/{info_id}")
async def delete_information(info_id: int, token: Token) -> dict[str, bool]:
    if not state.db.delete_information(info_id):
        raise HTTPException(status_code=404, detail="Information item not found")
    await state.events.broadcast("information_changed", state.db.list_information())
    return {"ok": True}


# Scripts and queue
@app.get("/api/scripts")
async def list_scripts(token: Token) -> list[dict[str, Any]]:
    return state.db.list_scripts()


@app.post("/api/scripts")
async def create_script(payload: ScriptCreate, token: Token) -> dict[str, Any]:
    script = state.db.create_script(payload.model_dump())
    await state.events.broadcast("scripts_changed", state.db.list_scripts())
    return script


@app.put("/api/scripts/{script_id}")
async def update_script(script_id: int, payload: ScriptCreate, token: Token) -> dict[str, Any]:
    script = state.db.update_script(script_id, payload.model_dump())
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    await state.events.broadcast("scripts_changed", state.db.list_scripts())
    return script


@app.delete("/api/scripts/{script_id}")
async def delete_script(script_id: int, token: Token) -> dict[str, bool]:
    if not state.db.delete_script(script_id):
        raise HTTPException(status_code=404, detail="Script not found")
    await state.events.broadcast("scripts_changed", state.db.list_scripts())
    await state.script_queue.notify()
    return {"ok": True}


@app.post("/api/scripts/{script_id}/queue")
async def queue_script(script_id: int, token: Token) -> dict[str, Any]:
    script = state.db.get_script(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    if not script.get("enabled"):
        raise HTTPException(status_code=400, detail="Script is disabled")
    return await state.script_queue.add(script_id)


@app.post("/api/scripts/{script_id}/run-now")
async def run_script_now(script_id: int, token: Token) -> dict[str, bool]:
    script = state.db.get_script(script_id)
    if not script:
        raise HTTPException(status_code=404, detail="Script not found")
    if not script.get("enabled"):
        raise HTTPException(status_code=400, detail="Script is disabled")
    await state.conversation.stop_conversation(stop_tts=True)
    asyncio.create_task(state.script_queue.run_now(script_id), name=f"script-now-{script_id}")
    return {"ok": True}


@app.get("/api/queue")
async def get_queue(token: Token) -> dict[str, Any]:
    return {"state": state.script_queue.state, "items": state.db.list_queue()}


@app.post("/api/queue/play")
async def play_queue(token: Token) -> dict[str, bool]:
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.play()
    return {"ok": True}


@app.post("/api/queue/pause")
async def pause_queue(token: Token) -> dict[str, bool]:
    await state.script_queue.pause()
    return {"ok": True}


@app.post("/api/queue/stop")
async def stop_queue(token: Token) -> dict[str, bool]:
    await state.script_queue.stop()
    return {"ok": True}


@app.delete("/api/queue")
async def clear_queue(token: Token) -> dict[str, bool]:
    await state.script_queue.clear()
    return {"ok": True}


@app.delete("/api/queue/{queue_id}")
async def remove_queue_item(queue_id: int, token: Token) -> dict[str, bool]:
    await state.script_queue.remove(queue_id)
    return {"ok": True}


@app.put("/api/queue/reorder")
async def reorder_queue(payload: QueueReorder, token: Token) -> dict[str, bool]:
    await state.script_queue.reorder(payload.ordered_ids)
    return {"ok": True}


# Conversations and host audio controls
@app.post("/api/conversation/start")
async def start_conversation(token: Token) -> dict[str, bool]:
    try:
        await state.conversation.start_conversation()
    except AudioUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/conversation/stop")
async def stop_conversation(token: Token) -> dict[str, bool]:
    await state.conversation.stop_conversation(stop_tts=True)
    return {"ok": True}


@app.post("/api/ptt/start")
async def start_ptt(token: Token) -> dict[str, bool]:
    await state.conversation.start_ptt()
    return {"ok": True}


@app.post("/api/ptt/stop")
async def stop_ptt(token: Token) -> dict[str, bool]:
    await state.conversation.stop_ptt()
    return {"ok": True}


@app.post("/api/ptt/cancel")
async def cancel_ptt(token: Token) -> dict[str, bool]:
    await state.conversation.cancel_ptt()
    return {"ok": True}




@app.post("/api/browser-ptt/start")
async def start_browser_ptt(token: Token) -> dict[str, bool]:
    try:
        await state.conversation.start_browser_ptt()
    except AudioUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True}


@app.post("/api/browser-ptt/audio")
async def browser_ptt_audio(
    token: Token,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    payload = await file.read()
    if len(payload) > 12 * 1024 * 1024:
        await state.conversation.cancel_browser_ptt()
        raise HTTPException(status_code=413, detail="Dashboard microphone recording is too large")
    try:
        samples = decode_pcm_wav(payload, state.settings.sample_rate)
    except AudioUnavailable as exc:
        await state.conversation.cancel_browser_ptt()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    maximum_samples = int(state.settings.max_record_seconds * state.settings.sample_rate)
    if samples.size > maximum_samples:
        samples = samples[:maximum_samples]
    return await state.conversation.submit_browser_ptt(samples)


@app.post("/api/browser-ptt/cancel")
async def cancel_browser_ptt(token: Token) -> dict[str, bool]:
    await state.conversation.cancel_browser_ptt()
    return {"ok": True}


@app.post("/api/chat/send")
async def send_text(payload: TextMessageRequest, token: Token) -> dict[str, Any]:
    return await state.conversation.send_text(payload.text, payload.conversation_id)


@app.post("/api/conversations")
async def create_conversation(payload: ConversationCreate, token: Token) -> dict[str, Any]:
    return await state.conversation.new_chat(payload.title)


@app.get("/api/agents/{agent_id}/conversations")
async def list_conversations(agent_id: int, token: Token) -> list[dict[str, Any]]:
    return state.db.list_conversations(agent_id)


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: int, token: Token) -> dict[str, Any]:
    conversation = state.db.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {
        "conversation": conversation,
        "messages": state.db.list_messages(conversation_id, limit=1000),
    }


@app.delete("/api/conversations/{conversation_id}/messages")
async def clear_conversation(conversation_id: int, token: Token) -> dict[str, bool]:
    if not state.db.get_conversation(conversation_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    state.db.clear_conversation(conversation_id)
    await state.events.broadcast("conversation_cleared", {"conversation_id": conversation_id})
    return {"ok": True}


@app.post("/api/tts/stop")
async def stop_current_tts(token: Token) -> dict[str, bool]:
    await state.conversation.stop_current_tts()
    await state.events.broadcast("tts_stopped", {"source": "manual"})
    return {"ok": True}


@app.get("/api/audio/devices")
async def audio_devices(token: Token) -> dict[str, Any]:
    return audio_device_payload()


@app.post("/api/audio/refresh")
async def refresh_audio_devices(token: Token) -> dict[str, Any]:
    """Perform a real Windows/PortAudio hot-plug refresh and remap saved devices."""
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()
    try:
        recovery = await asyncio.to_thread(
            state.refresh_audio_devices, "dashboard hot-plug refresh"
        )
        devices = audio_device_payload()
    except AudioUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await state.events.broadcast(
        "audio_devices_refreshed",
        {"devices": devices, "recovery": recovery},
    )
    return {**devices, "recovery": recovery}


@app.post("/api/audio/restart-engine")
async def restart_audio_engine(token: Token) -> dict[str, Any]:
    if state.audio_engine is None:
        raise HTTPException(
            status_code=400,
            detail="Audio Engine process isolation is disabled in .env",
        )
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()
    await asyncio.to_thread(state.audio_engine.restart, "manual dashboard request")
    if not state.audio_engine.process_alive:
        raise HTTPException(status_code=503, detail="Audio Engine could not be restarted")
    await asyncio.to_thread(state.reconcile_audio_devices)
    state.monitor.increment("audio_device_recoveries")
    health = state.audio_engine.health()
    await state.events.broadcast("audio_engine_restarted", health)
    return health


@app.post("/api/ai/restart-engine")
async def restart_ai_engine(token: Token) -> dict[str, Any]:
    if state.ai_engine is None:
        raise HTTPException(
            status_code=400,
            detail="AI Engine process isolation is disabled in .env",
        )
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()
    try:
        await asyncio.to_thread(state.ai_engine.restart, "manual dashboard request")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not state.ai_engine.process_alive:
        raise HTTPException(status_code=503, detail="AI Engine could not be restarted")
    health = state.ai_engine.health()
    await state.events.broadcast("ai_engine_restarted", health)
    return health


@app.post("/api/ai/reload-asr")
async def reload_ai_asr(token: Token) -> dict[str, Any]:
    if state.ai_engine is None:
        raise HTTPException(status_code=400, detail="AI Engine process isolation is disabled")
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()
    try:
        result = await asyncio.to_thread(state.ai_engine.reload_asr)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await state.events.broadcast("ai_model_reloaded", {"provider": "asr", "status": result})
    return {"ok": True, "provider": "asr", "status": result, "engine": state.ai_engine.health()}


@app.post("/api/ai/reload-kokoro")
async def reload_ai_kokoro(token: Token) -> dict[str, Any]:
    if state.ai_engine is None:
        raise HTTPException(status_code=400, detail="AI Engine process isolation is disabled")
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()
    try:
        result = await asyncio.to_thread(state.ai_engine.reload_kokoro)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await state.events.broadcast("ai_model_reloaded", {"provider": "kokoro", "status": result})
    return {"ok": True, "provider": "kokoro", "status": result, "engine": state.ai_engine.health()}


@app.post("/api/audio/test-input")
async def test_input_device(payload: AudioDeviceTestRequest, token: Token) -> dict[str, Any]:
    await state.conversation.stop_conversation(stop_tts=True)
    try:
        result = await asyncio.to_thread(
            state.recorder.test_input,
            payload.input_device,
            1.5,
        )
    except AudioUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result


@app.post("/api/audio/test-output")
async def test_output_device(payload: AudioDeviceTestRequest, token: Token) -> dict[str, Any]:
    await state.conversation.stop_conversation(stop_tts=True)
    state.player.set_output_device(payload.output_device)
    try:
        import numpy as np
        import soundfile as sf

        sample_rate = 44100
        duration = 0.65
        timeline = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        envelope = np.minimum(1.0, timeline / 0.03) * np.minimum(
            1.0, (duration - timeline) / 0.06
        )
        tone = (0.22 * np.sin(2 * np.pi * 660 * timeline) * envelope).astype(np.float32)
        path = state.settings.runtime_audio_dir / "output-device-test.wav"
        sf.write(path, tone, sample_rate, subtype="PCM_16")
        played = await asyncio.to_thread(
            state.player.play_file,
            path,
            1.0,
            payload.output_device,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Could not play through the selected speaker: {exc}",
        ) from exc
    if not played:
        raise HTTPException(status_code=503, detail="Speaker test was cancelled")
    info = state.recorder.device_info(payload.output_device)
    return {
        "ok": True,
        "device_id": payload.output_device,
        "device_name": info["name"] if info else "System default output",
        "hostapi": info["hostapi"] if info else "System default",
    }


@app.post("/api/audio/test-duplex-lock")
async def test_duplex_lock(payload: AudioDeviceTestRequest, token: Token) -> dict[str, Any]:
    """Open output first, then input, and play a tone while both stay active."""
    await state.conversation.stop_conversation(stop_tts=True)
    state.player.set_output_device(payload.output_device)
    try:
        output_info = await asyncio.to_thread(
            state.player.lock_output, payload.output_device
        )
        input_info = await asyncio.to_thread(
            state.recorder.lock_input, payload.input_device
        )
        import numpy as np
        import soundfile as sf

        sample_rate = 44100
        duration = 1.0
        timeline = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
        envelope = np.minimum(1.0, timeline / 0.04) * np.minimum(
            1.0, (duration - timeline) / 0.08
        )
        tone = (0.2 * np.sin(2 * np.pi * 523.25 * timeline) * envelope).astype(np.float32)
        path = state.settings.runtime_audio_dir / "duplex-lock-test.wav"
        sf.write(path, tone, sample_rate, subtype="PCM_16")
        played = await asyncio.to_thread(
            state.player.play_file,
            path,
            1.0,
            payload.output_device,
        )
        if not played:
            raise AudioUnavailable("Duplex lock speaker test was cancelled")
    except Exception as exc:
        await asyncio.to_thread(state.recorder.unlock_input)
        raise HTTPException(
            status_code=503,
            detail=f"Could not keep both selected audio devices locked: {exc}",
        ) from exc
    await state.events.broadcast(
        "audio_lock_changed",
        {"input_locked": True, "output_locked": True},
    )
    # Release the test microphone after validation; conversation mode will lock
    # it again. Keep the selected speaker stream active for subsequent scripts.
    await asyncio.to_thread(state.recorder.unlock_input)
    await state.events.broadcast(
        "audio_lock_changed",
        {"input_locked": False, "output_locked": state.player.output_locked},
    )
    return {
        "ok": True,
        "input": input_info,
        "output": output_info,
        "output_locked": state.player.output_locked,
    }


@app.put("/api/conversation/settings")
async def update_conversation_settings(
    payload: ConversationSettingsUpdate,
    token: Token,
) -> dict[str, Any]:
    previous = state.db.get_runtime_settings()
    values = payload.model_dump()

    available = {device["id"]: device for device in state.recorder.list_devices()}
    selected_input = values.get("input_device")
    selected_output = values.get("output_device")
    if selected_input is not None:
        device = available.get(selected_input)
        if not device or int(device.get("max_input_channels", 0)) <= 0:
            raise HTTPException(status_code=400, detail="Selected microphone is unavailable")
    if selected_output is not None:
        device = available.get(selected_output)
        if not device or int(device.get("max_output_channels", 0)) <= 0:
            raise HTTPException(status_code=400, detail="Selected speaker is unavailable")

    input_info = available.get(selected_input) if selected_input is not None else None
    output_info = available.get(selected_output) if selected_output is not None else None
    values["input_device_fingerprint"] = state.recorder.device_fingerprint(input_info, "input")
    values["output_device_fingerprint"] = state.recorder.device_fingerprint(output_info, "output")

    device_changed = (
        previous.get("input_device") != selected_input
        or previous.get("output_device") != selected_output
        or previous.get("input_device_fingerprint") != values.get("input_device_fingerprint")
        or previous.get("output_device_fingerprint") != values.get("output_device_fingerprint")
    )
    if device_changed:
        await state.conversation.stop_conversation(stop_tts=True)

    for key, value in values.items():
        state.db.set_setting(key, "" if value is None else str(value).lower() if isinstance(value, bool) else str(value))
    updated = state.db.get_runtime_settings()
    if device_changed:
        if state.audio_engine is not None:
            state.audio_engine.configure_input(updated.get("input_device"))
        state.player.set_output_device(updated.get("output_device"))
        state.monitor.increment("audio_device_recoveries")
    await state.events.broadcast("runtime_settings_changed", updated)
    return updated


# Ollama model manager
@app.get("/api/models")
async def list_models(token: Token) -> list[dict[str, Any]]:
    try:
        return await state.llm.list_models()
    except OllamaUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/models/pull/{model:path}")
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


# Backups
@app.get("/api/backup")
async def create_backup(token: Token) -> FileResponse:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_zip = state.settings.backup_dir / f"verbanode-backup-{timestamp}.zip"
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        db_copy = state.db.backup_to(temp_dir / "verbanode.db")
        metadata = {
            "version": 1,
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "database": db_copy.name,
        }
        (temp_dir / "backup.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        with zipfile.ZipFile(backup_zip, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.write(db_copy, db_copy.name)
            archive.write(temp_dir / "backup.json", "backup.json")
    return FileResponse(
        backup_zip,
        filename=backup_zip.name,
        media_type="application/zip",
    )


@app.post("/api/restore")
async def restore_backup(token: Token, file: UploadFile = File(...)) -> dict[str, bool]:
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()
    content = await file.read()
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        zip_path = temp_dir / "upload.zip"
        zip_path.write_bytes(content)
        try:
            with zipfile.ZipFile(zip_path) as archive:
                names = set(archive.namelist())
                database_name = (
                    "verbanode.db" if "verbanode.db" in names
                    else "verbanode_standalone.db" if "verbanode_standalone.db" in names
                    else None
                )
                if database_name is None:
                    raise HTTPException(status_code=400, detail="Backup database is missing")
                archive.extract(database_name, temp_dir)
            restored = temp_dir / database_name
            with sqlite3.connect(restored) as conn:
                result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise HTTPException(status_code=400, detail="Backup database failed integrity check")
            shutil.copy2(restored, state.settings.db_path)
            state.db.initialize()
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="Invalid backup ZIP") from exc
    await state.events.broadcast("reload_required", {"reason": "database_restored"})
    return {"ok": True}
