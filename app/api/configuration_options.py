from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import Token
from app.state import state

router = APIRouter(tags=["configuration"])


@router.get("/api/configuration-options")
async def configuration_options(token: Token) -> dict[str, Any]:
    try:
        raw_models = await state.llm.list_models()
    except Exception:
        raw_models = []
    models = []
    for item in raw_models:
        name = str(item.get("name") or item.get("model") or "").strip()
        if name and name not in models:
            models.append(name)
    if state.settings.default_model not in models:
        models.insert(0, state.settings.default_model)
    return {
        "languages": [
            {"value": "en", "label": "English"},
            {"value": "id", "label": "Bahasa Indonesia"},
        ],
        "llm_models": models,
        "stt_models": {
            "en": [{"value": "iic/SenseVoiceSmall", "label": "SenseVoice Small"}],
            "id": [
                {"value": "Whisper-base", "label": "Whisper Base — faster CPU"},
                {"value": "Whisper-small", "label": "Whisper Small — better accuracy"},
            ],
        },
        "tts_modes": [
            {"value": "edge", "label": "Edge only"},
            {"value": "kokoro", "label": "Kokoro local only"},
            {"value": "edge_fallback", "label": "Edge → Kokoro fallback"},
            {"value": "kokoro_fallback", "label": "Kokoro → Edge fallback"},
        ],
    }
