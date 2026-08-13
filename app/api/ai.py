from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.deps import Token
from app.api.uploads import read_upload_limited
from app.services.audio import AudioUnavailable, decode_pcm_wav
from app.state import state

LOGGER = logging.getLogger(__name__)
router = APIRouter()

@router.post("/api/ai/restart-engine")
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


@router.post("/api/ai/reload-asr")
async def reload_ai_asr(token: Token) -> dict[str, Any]:
    if state.ai_engine is None:
        raise HTTPException(status_code=400, detail="AI Engine process isolation is disabled")
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()
    try:
        active_agent = state.conversation.active_agent()
        result = await asyncio.to_thread(
            state.ai_engine.reload_asr,
            str(active_agent.get("stt_model") or state.settings.funasr_model),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    await state.events.broadcast("ai_model_reloaded", {"provider": "asr", "status": result})
    return {"ok": True, "provider": "asr", "status": result, "engine": state.ai_engine.health()}


@router.post("/api/ai/test-language-profile")
async def test_active_language_profile(token: Token) -> dict[str, Any]:
    """Warm the active agent's ASR and play a language-matched Edge sample.

    This is intentionally non-destructive: it does not record microphone audio
    and does not add a chat message. It verifies the selected recognizer can be
    loaded and that the configured Edge voice can produce host playback.
    """
    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()
    agent = state.conversation.active_agent()
    language = str(agent.get("language") or "en").lower()
    model_name = str(agent.get("stt_model") or state.settings.funasr_model)
    if language == "id":
        if model_name not in {"Whisper-base", "Whisper-small"}:
            raise HTTPException(status_code=400, detail="Indonesian agents require Whisper Base or Whisper Small")
        voice = str(agent.get("edge_voice") or "id-ID-GadisNeural")
        if not voice.lower().startswith("id-"):
            raise HTTPException(status_code=400, detail="Indonesian agents require an Indonesian Edge voice")
        preview_text = "Halo. Profil Bahasa Indonesia VerbaNode siap digunakan."
    else:
        if model_name != "iic/SenseVoiceSmall":
            raise HTTPException(status_code=400, detail="English agents require SenseVoiceSmall")
        voice = str(agent.get("edge_voice") or "en-US-AriaNeural")
        if voice.lower().startswith("id-"):
            raise HTTPException(status_code=400, detail="English agents require an English Edge voice")
        preview_text = "Hello. The English VerbaNode voice profile is ready."

    try:
        if state.ai_engine is not None:
            current = state.stt.status()
            if not current.get("loaded") or str(current.get("model")) != model_name:
                asr_status = await asyncio.to_thread(state.ai_engine.reload_asr, model_name)
            else:
                asr_status = current
        else:
            reload_model = getattr(state.stt, "reload_model", None)
            if reload_model is None:
                raise RuntimeError("The configured ASR service cannot reload models")
            asr_status = await asyncio.to_thread(reload_model, model_name)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ASR profile test failed: {exc}") from exc

    try:
        played = await asyncio.to_thread(
            state.tts.preview_edge_voice_blocking,
            voice=voice,
            text=preview_text,
            rate=float(agent.get("tts_rate") or 1.0),
            volume=float(agent.get("tts_volume") or 1.0),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Edge TTS profile test failed: {exc}") from exc
    if not played:
        raise HTTPException(status_code=503, detail="Language profile voice test was cancelled")

    return {
        "ok": True,
        "language": language,
        "model": model_name,
        "voice": voice,
        "asr": asr_status,
        "stt": state.stt.status(),
    }


@router.post("/api/ai/benchmark-asr")
async def benchmark_ai_asr(
    token: Token,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Compare Indonesian Whisper Base and Small using one real WAV sample.

    This intentionally runs only on an uploaded sample so the benchmark reflects
    the user's actual microphone, CPU and speech rather than synthetic audio.
    The active agent's selected ASR model is restored afterward.
    """
    if state.ai_engine is None:
        raise HTTPException(status_code=400, detail="AI Engine process isolation is disabled")
    payload = await read_upload_limited(
        file,
        max_bytes=12 * 1024 * 1024,
        too_large_message="ASR benchmark WAV is too large",
    )
    try:
        samples = decode_pcm_wav(payload, state.settings.sample_rate)
    except AudioUnavailable as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if samples.size < int(state.settings.sample_rate * 0.25):
        raise HTTPException(status_code=400, detail="ASR benchmark audio is too short")

    await state.conversation.stop_conversation(stop_tts=True)
    await state.script_queue.stop()
    active_agent = state.conversation.active_agent()
    restore_model = str(active_agent.get("stt_model") or state.settings.funasr_model)
    duration_seconds = samples.size / float(state.settings.sample_rate)
    results: list[dict[str, Any]] = []
    try:
        for model_name in ("Whisper-base", "Whisper-small"):
            item: dict[str, Any] = {"model": model_name}
            try:
                load_status = await asyncio.to_thread(state.ai_engine.reload_asr, model_name)
                transcription = await asyncio.to_thread(
                    state.ai_engine.call,
                    "asr.transcribe",
                    samples,
                    model_name,
                    "id",
                    timeout=max(float(state.settings.stt_timeout_seconds), 180.0),
                )
                latency_ms = int(dict(transcription).get("latency_ms") or 0)
                item.update({
                    "ok": True,
                    "load_ms": int(load_status.get("model_load_ms") or 0),
                    "transcription_ms": latency_ms,
                    "rtf": round((latency_ms / 1000.0) / max(duration_seconds, 0.001), 3),
                    "text": str(dict(transcription).get("text") or ""),
                    "confidence": float(dict(transcription).get("confidence") or 0.0),
                    "confidence_source": str(dict(transcription).get("confidence_source") or "estimated"),
                })
            except Exception as exc:
                item.update({"ok": False, "error": str(exc)})
            results.append(item)
    finally:
        try:
            await asyncio.to_thread(state.ai_engine.reload_asr, restore_model)
        except Exception as exc:
            LOGGER.warning("Could not restore active ASR model %s after benchmark: %s", restore_model, exc)

    return {
        "language": "id",
        "audio_seconds": round(duration_seconds, 2),
        "sample_rate": state.settings.sample_rate,
        "restored_model": restore_model,
        "results": results,
    }


@router.post("/api/ai/reload-kokoro")
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

