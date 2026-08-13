from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.api.deps import Token
from app.api.plugins import plugin_payload
from app.schemas import DiagnosticsSoakRequest
from app.state import state

LOGGER = logging.getLogger(__name__)
router = APIRouter()

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
        return f"AI Engine PID {health.get('pid')} is responsive; active ASR state is {asr_state}"

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
            if item["status"] in {"error", "load_error", "invalid", "incompatible", "unhealthy"}
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


@router.get("/api/diagnostics")
async def diagnostics_status(token: Token) -> dict[str, Any]:
    snapshot = await asyncio.to_thread(diagnostics_snapshot)
    return {
        "snapshot": snapshot,
        "recent_turns": state.monitor.recent_turns(20),
        "recent_logs": state.diagnostics.logs(limit=80),
        "self_test": state.diagnostics.last_self_test(),
        "soak": state.diagnostics.soak_status(include_samples=False),
    }


@router.post("/api/diagnostics/self-test")
async def diagnostics_self_test(token: Token) -> dict[str, Any]:
    return await run_diagnostics_self_test()


@router.get("/api/diagnostics/logs")
async def diagnostics_logs(
    token: Token,
    limit: int = 200,
    minimum_level: str | None = None,
) -> dict[str, Any]:
    return {
        "entries": state.diagnostics.logs(limit=limit, minimum_level=minimum_level),
        "capacity": state.diagnostics.log_handler.capacity,
    }


@router.delete("/api/diagnostics/logs")
async def clear_diagnostics_logs(token: Token) -> dict[str, bool]:
    state.diagnostics.clear_logs()
    LOGGER.info("Diagnostics log buffer cleared from the dashboard")
    return {"ok": True}


@router.delete("/api/diagnostics/turns")
async def clear_diagnostics_turns(token: Token) -> dict[str, bool]:
    state.monitor.clear_history()
    return {"ok": True}


@router.get("/api/diagnostics/export")
async def export_diagnostics(token: Token) -> FileResponse:
    snapshot = await asyncio.to_thread(diagnostics_snapshot)
    path = await asyncio.to_thread(
        state.diagnostics.create_report,
        snapshot,
        recent_turns=state.monitor.recent_turns(100),
        self_test=state.diagnostics.last_self_test(),
    )
    return FileResponse(path, filename=path.name, media_type="application/zip")


@router.post("/api/diagnostics/soak/start")
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


@router.post("/api/diagnostics/soak/stop")
async def stop_diagnostics_soak(token: Token) -> dict[str, Any]:
    return await asyncio.to_thread(state.diagnostics.stop_soak)


@router.get("/api/diagnostics/soak")
async def diagnostics_soak_status(token: Token) -> dict[str, Any]:
    return state.diagnostics.soak_status(include_samples=False)


