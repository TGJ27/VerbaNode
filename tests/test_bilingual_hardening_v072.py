from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.config import Settings
from app.services.ai_engine import AiEngineUnavailable, AiSttProxy
from app.services.stt import FunASRService
from app.services.tools import ToolService


def test_indonesian_deterministic_variants() -> None:
    tools = ToolService(Settings(open_browser=False))
    enabled = ["get_current_time", "get_location", "get_weather", "handle_exit_intent"]
    assert tools.match_core_intent("hari apa sekarang?", enabled) == ("get_current_time", {})
    assert tools.match_core_intent("tanggal berapa sekarang?", enabled) == ("get_current_time", {})
    assert tools.match_core_intent("jam sekarang berapa?", enabled) == ("get_current_time", {})
    assert tools.match_core_intent("cuaca di Bandung hari ini", enabled) == ("get_weather", {"location": "bandung"})
    assert tools.match_core_intent("bagaimana cuaca di Jakarta sekarang?", enabled) == ("get_weather", {"location": "jakarta"})
    assert tools.match_core_intent("kita dimana?", enabled) == ("get_location", {})
    assert tools.match_core_intent("berhenti bicara", enabled) == ("handle_exit_intent", {})
    assert tools.match_core_intent("diam dulu", enabled) == ("handle_exit_intent", {})


def test_only_whisper_small_has_automatic_indonesian_fallback() -> None:
    assert FunASRService.fallback_model("Whisper-small", "id") == "Whisper-base"
    assert FunASRService.fallback_model("Whisper-base", "id") is None
    assert FunASRService.fallback_model("Whisper-small", "en") is None
    assert FunASRService.fallback_model("iic/SenseVoiceSmall", "en") is None


def test_ai_stt_proxy_falls_back_from_small_to_base(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", open_browser=False)

    class FakeEngine:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def call(self, operation, *args, **kwargs):
            assert operation == "asr.transcribe"
            model = str(args[1])
            self.calls.append(model)
            if model == "Whisper-small":
                raise AiEngineUnavailable("small model unavailable")
            return {"text": "halo dunia", "confidence": 0.9, "confidence_source": "estimated"}

        def health(self):
            return {"alive": True, "pid": 1, "remote": {"asr": {"state": "ready", "loaded": True, "model": "Whisper-base"}}}

    engine = FakeEngine()
    proxy = AiSttProxy(engine, settings)
    result = proxy.transcribe_with_confidence(np.ones(1600, dtype=np.float32), "Whisper-small", "id")
    assert result.text == "halo dunia"
    assert engine.calls == ["Whisper-small", "Whisper-base"]
    status = proxy.status()
    assert status["fallback_model"] == "Whisper-base"
    assert "small model unavailable" in status["fallback_reason"]
