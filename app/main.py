from __future__ import annotations

import asyncio
import logging

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from app.api.actions import router as actions_router
from app.api.agents import router as agents_router
from app.api.ai import router as ai_router
from app.api.audio import router as audio_router
from app.api.auth import router as auth_router
from app.api.backup import router as backup_router
from app.api.capabilities import router as capabilities_router
from app.api.conversations import router as conversations_router
from app.api.diagnostics import router as diagnostics_router
from app.api.devices import router as devices_router
from app.api.information import router as information_router
from app.api.models import router as models_router
from app.api.plugins import router as plugins_router
from app.api.scripts import router as scripts_router
from app.api.system import router as system_router
from app.api.tts import router as tts_router
from app.config import ROOT_DIR
from app.http import install_http_hardening, install_request_id_logging
from app.runtime import install_asyncio_exception_filter
from app.services.audio import AudioUnavailable
from app.state import state
from app.version import APP_VERSION

install_request_id_logging()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [req=%(request_id)s] %(name)s - %(message)s",
)
LOGGER = logging.getLogger(__name__)

app = FastAPI(title="VerbaNode Standalone", version=APP_VERSION)
install_http_hardening(app, max_json_body_bytes=state.settings.api_max_json_body_bytes)

STATIC_DIR = ROOT_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Keep the public API client-neutral. The browser dashboard and future mobile
# clients consume the same routers and WebSocket protocol. Explicit registration
# also makes the application composition easy to audit during release reviews.
app.include_router(system_router)
app.include_router(auth_router)
app.include_router(devices_router)
app.include_router(actions_router)
app.include_router(capabilities_router)
app.include_router(agents_router)
app.include_router(information_router)
app.include_router(scripts_router)
app.include_router(plugins_router)
app.include_router(conversations_router)
app.include_router(models_router)
app.include_router(backup_router)
app.include_router(diagnostics_router)
app.include_router(audio_router)
app.include_router(ai_router)
app.include_router(tts_router)


@app.on_event("startup")
async def startup_event() -> None:
    install_asyncio_exception_filter()
    state.diagnostics.install_logging()
    LOGGER.info("Diagnostics recorder initialized for VerbaNode %s", APP_VERSION)
    if state.settings.lan_discovery_enabled:
        await asyncio.to_thread(state.discovery.start)
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
async def disable_ui_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await asyncio.to_thread(state.discovery.stop)
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
