from __future__ import annotations

from typing import Any

from app.db import Database

_DEFAULTS = {
    "language": "en",
    "tts_mode": "edge",
    "edge_voice": "en-US-AriaNeural",
    "kokoro_voice_id": 0,
    "tts_rate": 1.0,
    "tts_volume": 1.0,
}
_KEYS = {key: f"type_to_talk_default_{key}" for key in _DEFAULTS}


def _normalise(values: dict[str, Any]) -> dict[str, Any]:
    result = dict(_DEFAULTS)
    result.update({key: values[key] for key in _DEFAULTS if key in values and values[key] is not None})
    result["language"] = "id" if str(result.get("language")) == "id" else "en"
    result["tts_mode"] = str(result.get("tts_mode") or "edge")
    result["edge_voice"] = str(result.get("edge_voice") or ("id-ID-GadisNeural" if result["language"] == "id" else "en-US-AriaNeural"))
    result["kokoro_voice_id"] = max(0, min(102, int(result.get("kokoro_voice_id") or 0)))
    result["tts_rate"] = max(0.5, min(2.0, float(result.get("tts_rate") or 1.0)))
    result["tts_volume"] = max(0.0, min(1.0, float(1.0 if result.get("tts_volume") is None else result.get("tts_volume"))))
    if result["language"] == "id":
        result["tts_mode"] = "edge"
        if not result["edge_voice"].startswith("id-"):
            result["edge_voice"] = "id-ID-GadisNeural"
    elif result["edge_voice"].lower().startswith("id-"):
        result["edge_voice"] = "en-US-AriaNeural"
    return result


def get_type_to_talk_defaults(db: Database) -> dict[str, Any]:
    values: dict[str, Any] = dict(_DEFAULTS)
    for key, setting_key in _KEYS.items():
        raw = db.get_setting(setting_key, None)
        if raw in (None, ""):
            continue
        try:
            if key == "kokoro_voice_id":
                values[key] = int(raw)
            elif key in {"tts_rate", "tts_volume"}:
                values[key] = float(raw)
            else:
                values[key] = str(raw)
        except (TypeError, ValueError):
            pass
    return _normalise(values)


def save_type_to_talk_defaults(db: Database, values: dict[str, Any]) -> dict[str, Any]:
    merged = get_type_to_talk_defaults(db)
    merged.update({key: values[key] for key in _DEFAULTS if key in values and values[key] is not None})
    merged = _normalise(merged)
    for key, setting_key in _KEYS.items():
        db.set_setting(setting_key, str(merged[key]))
    return merged


def resolve_type_to_talk_config(db: Database, values: dict[str, Any] | None) -> dict[str, Any]:
    merged = get_type_to_talk_defaults(db)
    if values:
        merged.update({key: values[key] for key in _DEFAULTS if key in values and values[key] is not None})
    return _normalise(merged)


__all__ = ["get_type_to_talk_defaults", "save_type_to_talk_defaults", "resolve_type_to_talk_config"]
