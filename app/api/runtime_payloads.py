from __future__ import annotations

from typing import Any

from app.state import state

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
