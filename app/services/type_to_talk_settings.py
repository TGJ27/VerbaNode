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
_KEYS = {key: f"type_to_talk_{key}" for key in _DEFAULTS}


def get_type_to_talk_settings(db: Database) -> dict[str, Any]:
    values: dict[str, Any] = dict(_DEFAULTS)
    for key, setting_key in _KEYS.items():
        raw = db.get_setting(setting_key, None)
        if raw in (None, ""):
            continue
        if key == "kokoro_voice_id":
            try:
                values[key] = int(raw)
            except (TypeError, ValueError):
                pass
        elif key in {"tts_rate", "tts_volume"}:
            try:
                values[key] = float(raw)
            except (TypeError, ValueError):
                pass
        else:
            values[key] = str(raw)
    language = str(values.get("language") or "en")
    if language == "id":
        values["tts_mode"] = "edge"
        if not str(values.get("edge_voice") or "").startswith("id-"):
            values["edge_voice"] = "id-ID-GadisNeural"
    elif str(values.get("edge_voice") or "").startswith("id-"):
        values["edge_voice"] = "en-US-AriaNeural"
    return values


def save_type_to_talk_settings(db: Database, updates: dict[str, Any]) -> dict[str, Any]:
    values = get_type_to_talk_settings(db)
    for key in _DEFAULTS:
        if key in updates:
            values[key] = updates[key]
    language = "id" if str(values.get("language") or "en") == "id" else "en"
    values["language"] = language
    values["tts_rate"] = max(0.5, min(2.0, float(values.get("tts_rate", 1.0))))
    values["tts_volume"] = max(0.0, min(1.0, float(values.get("tts_volume", 1.0))))
    values["kokoro_voice_id"] = max(0, min(102, int(values.get("kokoro_voice_id", 0))))
    values["tts_mode"] = str(values.get("tts_mode") or "edge")
    values["edge_voice"] = str(values.get("edge_voice") or ("id-ID-GadisNeural" if language == "id" else "en-US-AriaNeural"))
    if language == "id":
        values["tts_mode"] = "edge"
        if not values["edge_voice"].startswith("id-"):
            values["edge_voice"] = "id-ID-GadisNeural"
    elif values["edge_voice"].startswith("id-"):
        values["edge_voice"] = "en-US-AriaNeural"
    for key, setting_key in _KEYS.items():
        db.set_setting(setting_key, str(values[key]))
    return get_type_to_talk_settings(db)


__all__ = ["get_type_to_talk_settings", "save_type_to_talk_settings"]
