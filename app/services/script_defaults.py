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
_KEYS = {key: f"script_default_{key}" for key in _DEFAULTS}


def get_script_defaults(db: Database) -> dict[str, Any]:
    values: dict[str, Any] = dict(_DEFAULTS)
    for key, setting_key in _KEYS.items():
        raw = db.get_setting(setting_key, None)
        if raw in (None, ""):
            continue
        if key == "kokoro_voice_id":
            try: values[key] = int(raw)
            except (TypeError, ValueError): pass
        elif key in {"tts_rate", "tts_volume"}:
            try: values[key] = float(raw)
            except (TypeError, ValueError): pass
        else:
            values[key] = str(raw)
    language = str(values.get("language") or "en")
    if language == "id":
        values["tts_mode"] = "edge"
        if not str(values.get("edge_voice") or "").startswith("id-"):
            values["edge_voice"] = "id-ID-GadisNeural"
    return values


def save_script_defaults(db: Database, values: dict[str, Any]) -> dict[str, Any]:
    merged = dict(get_script_defaults(db))
    merged.update({key: values[key] for key in _DEFAULTS if key in values})
    if str(merged.get("language") or "en") == "id":
        merged["tts_mode"] = "edge"
        if not str(merged.get("edge_voice") or "").startswith("id-"):
            merged["edge_voice"] = "id-ID-GadisNeural"
    for key, setting_key in _KEYS.items():
        db.set_setting(setting_key, str(merged[key]))
    return get_script_defaults(db)

__all__ = ["get_script_defaults", "save_script_defaults"]
