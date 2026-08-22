from __future__ import annotations

from typing import Any

from app.db import Database
from app.services.script_defaults import get_script_defaults

_KEYS = {
    "language": "type_to_talk_default_language",
    "tts_mode": "type_to_talk_default_tts_mode",
    "edge_voice": "type_to_talk_default_edge_voice",
    "kokoro_voice_id": "type_to_talk_default_kokoro_voice_id",
    "tts_rate": "type_to_talk_default_tts_rate",
    "tts_volume": "type_to_talk_default_tts_volume",
}


def _normalize(values: dict[str, Any]) -> dict[str, Any]:
    result = {
        "language": str(values.get("language") or "en"),
        "tts_mode": str(values.get("tts_mode") or "edge"),
        "edge_voice": str(values.get("edge_voice") or "en-US-AriaNeural"),
        "kokoro_voice_id": int(values.get("kokoro_voice_id") or 0),
        "tts_rate": max(0.5, min(2.0, float(values.get("tts_rate") or 1.0))),
        "tts_volume": max(0.0, min(1.0, float(values.get("tts_volume") if values.get("tts_volume") is not None else 1.0))),
    }
    if result["language"] not in {"en", "id"}:
        result["language"] = "en"
    if result["language"] == "id":
        result["tts_mode"] = "edge"
        if not result["edge_voice"].startswith("id-"):
            result["edge_voice"] = "id-ID-GadisNeural"
    elif result["tts_mode"] not in {"edge", "kokoro", "edge_fallback", "kokoro_fallback"}:
        result["tts_mode"] = "edge"
    return result


def get_type_to_talk_defaults(db: Database) -> dict[str, Any]:
    # First use inherits the last script speech configuration, then Type to Talk
    # remembers its own most recently submitted configuration.
    values = dict(get_script_defaults(db))
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
            continue
    return _normalize(values)


def save_type_to_talk_defaults(db: Database, values: dict[str, Any]) -> dict[str, Any]:
    merged = get_type_to_talk_defaults(db)
    merged.update({key: values[key] for key in _KEYS if key in values and values[key] is not None})
    normalized = _normalize(merged)
    for key, setting_key in _KEYS.items():
        db.set_setting(setting_key, str(normalized[key]))
    return normalized


__all__ = ["get_type_to_talk_defaults", "save_type_to_talk_defaults"]
