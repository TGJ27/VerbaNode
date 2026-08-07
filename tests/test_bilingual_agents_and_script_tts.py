from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from app.config import Settings
from app.db import Database
from app.services.prompts import PromptComposer
from app.services.script_queue import ScriptQueueManager


def test_default_english_and_indonesian_agents(tmp_path: Path) -> None:
    db = Database(Settings(db_path=tmp_path / "bilingual.db", open_browser=False))
    db.initialize()
    agents = db.list_agents()
    english = next(agent for agent in agents if agent["language"] == "en")
    indonesian = next(agent for agent in agents if agent["language"] == "id")
    assert english["stt_model"] == "iic/SenseVoiceSmall"
    assert english["edge_voice"] == "en-US-AriaNeural"
    assert indonesian["name"] == "Ropi Indonesia"
    assert indonesian["stt_model"] == "Whisper-base"
    assert indonesian["tts_mode"] == "edge"
    assert indonesian["edge_voice"] == "id-ID-GadisNeural"


def test_indonesian_prompt_is_language_locked() -> None:
    prompt = PromptComposer(Settings(open_browser=False)).compose(
        agent={
            "name": "Ropi Indonesia",
            "role": "Resepsionis",
            "system_prompt": "Berbicara dengan ramah.",
            "language": "id",
        },
        information=[],
        summary=None,
        tool_schemas=[],
    )
    assert "The active agent language is Bahasa Indonesia" in prompt
    assert "Respond only in natural Bahasa Indonesia" in prompt


def test_script_stores_its_own_voice_configuration(tmp_path: Path) -> None:
    db = Database(Settings(db_path=tmp_path / "scripts.db", open_browser=False))
    db.initialize()
    script = db.create_script(
        {
            "title": "Sambutan",
            "text": "Selamat datang.",
            "enabled": True,
            "language": "id",
            "tts_mode": "edge",
            "edge_voice": "id-ID-GadisNeural",
            "kokoro_voice_id": 0,
            "tts_rate": 0.95,
            "tts_volume": 0.8,
        }
    )
    queued = db.queue_script(script["id"])
    assert queued["language"] == "id"
    assert queued["tts_mode"] == "edge"
    assert queued["edge_voice"] == "id-ID-GadisNeural"
    assert queued["tts_rate"] == 0.95
    assert queued["tts_volume"] == 0.8


def test_script_queue_uses_script_voice_not_active_agent(tmp_path: Path) -> None:
    db = Database(Settings(db_path=tmp_path / "queue.db", open_browser=False))
    db.initialize()
    script = db.create_script(
        {
            "title": "Sambutan",
            "text": "Selamat datang.",
            "enabled": True,
            "language": "id",
            "tts_mode": "edge",
            "edge_voice": "id-ID-ArdiNeural",
            "kokoro_voice_id": 0,
            "tts_rate": 1.1,
            "tts_volume": 0.7,
        }
    )

    captured: dict[str, object] = {}

    class FakeTts:
        def begin_speech(self):
            return 3

        def generate_audio_blocking(self, text, agent, speech_id, **kwargs):
            captured.update(agent)
            return None

        def stop_current(self):
            return None

    class FakeEvents:
        async def broadcast(self, event, payload):
            return None

    manager = ScriptQueueManager(
        db, FakeTts(), FakeEvents(), lambda: {"edge_voice": "en-US-AriaNeural"}
    )
    asyncio.run(manager.run_now(script["id"]))
    assert captured["language"] == "id"
    assert captured["edge_voice"] == "id-ID-ArdiNeural"
    assert captured["tts_rate"] == 1.1
    assert captured["tts_volume"] == 0.7


def test_frontend_contains_agent_language_and_script_tts_controls() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'name="language"' in html
    assert "Whisper-base" in javascript
    assert "scriptEdgeVoiceSelect" in javascript
    assert "previewScriptVoiceBtn" in javascript


def test_whisper_base_runs_through_funasr_with_indonesian_decoding(
    tmp_path: Path, monkeypatch
) -> None:
    import sys
    import types

    from app.services.stt import FunASRService

    captured: dict[str, object] = {}

    class FakeModel:
        def generate(self, **kwargs):
            captured["generate"] = kwargs
            return [{"text": "Halo dunia"}]

    def auto_model(**kwargs):
        captured["load"] = kwargs
        return FakeModel()

    funasr_module = types.ModuleType("funasr")
    funasr_module.AutoModel = auto_model
    whisper_module = types.ModuleType("whisper")
    soundfile_module = types.ModuleType("soundfile")
    soundfile_module.write = lambda path, audio, rate, subtype=None: Path(path).write_bytes(b"wav")
    monkeypatch.setitem(sys.modules, "funasr", funasr_module)
    monkeypatch.setitem(sys.modules, "whisper", whisper_module)
    monkeypatch.setitem(sys.modules, "soundfile", soundfile_module)

    settings = Settings(
        open_browser=False,
        runtime_audio_dir=tmp_path / "audio",
    )
    settings.runtime_audio_dir.mkdir(parents=True, exist_ok=True)
    service = FunASRService(settings)
    result = service.transcribe_with_confidence(
        np.ones(16000, dtype=np.float32) * 0.05,
        "Whisper-base",
        "id",
    )

    assert result.text == "Halo dunia"
    assert captured["load"]["model"] == "Whisper-base"
    assert captured["load"]["hub"] == "openai"
    decoding = captured["generate"]["DecodingOptions"]
    assert decoding["language"] == "id"
    assert decoding["task"] == "transcribe"
    assert decoding["fp16"] is False


def test_agent_and_script_language_validators_select_safe_profiles() -> None:
    from app.schemas import AgentCreate, ScriptCreate

    agent = AgentCreate(language="id", stt_model="anything", edge_voice="en-US-AriaNeural")
    assert agent.stt_model == "Whisper-base"
    assert agent.tts_mode == "edge"
    assert agent.edge_voice == "id-ID-GadisNeural"

    script = ScriptCreate(
        title="Sambutan",
        text="Selamat datang.",
        language="id",
        tts_mode="kokoro",
        edge_voice="en-US-AriaNeural",
    )
    assert script.tts_mode == "edge"
    assert script.edge_voice == "id-ID-GadisNeural"
