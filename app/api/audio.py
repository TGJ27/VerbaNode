from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import Token
from app.api.runtime_payloads import audio_device_payload
from app.schemas import AudioDeviceTestRequest, ConversationSettingsUpdate
from app.services.audio import AudioUnavailable
from app.state import state

router = APIRouter()

@router.get("/api/audio/devices")
async def audio_devices(token: Token) -> dict[str, Any]:
    return audio_device_payload()


@router.post("/api/audio/refresh")
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


@router.post("/api/audio/restart-engine")
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



@router.post("/api/audio/test-input")
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


@router.post("/api/audio/test-output")
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


@router.post("/api/audio/test-duplex-lock")
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


@router.put("/api/conversation/settings")
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
