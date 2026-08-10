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
    assert indonesian["name"] == "Ropi"
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
    assert "Whisper-small" in javascript
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


def test_indonesian_agent_can_select_whisper_small() -> None:
    from app.schemas import AgentCreate

    agent = AgentCreate(
        language="id",
        stt_model="Whisper-small",
        edge_voice="id-ID-GadisNeural",
    )
    assert agent.stt_model == "Whisper-small"
    assert agent.tts_mode == "edge"


def test_active_agent_persists_across_database_reinitialize(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "persist-agent.db", open_browser=False)
    db = Database(settings)
    db.initialize()
    indonesian = next(agent for agent in db.list_agents() if agent["language"] == "id")
    db.set_setting("active_agent_id", str(indonesian["id"]))

    # Re-running initialize mirrors an application restart and must not reset
    # the operator's active agent back to the first seeded agent.
    Database(settings).initialize()
    assert int(Database(settings).get_setting("active_agent_id", "0")) == indonesian["id"]


def test_indonesian_location_phrases_route_deterministically() -> None:
    from app.services.tools import ToolService

    tools = ToolService(Settings(open_browser=False))
    enabled = ["get_location"]
    phrases = [
        "lokasi kita sekarang di mana",
        "lokasi kita dimana",
        "kita ada di kota mana",
        "kita ada di kotaman",
        "sekarang kita berada dimana",
    ]
    for phrase in phrases:
        assert tools.match_core_intent(phrase, enabled) == ("get_location", {})


def test_assistant_text_strips_markdown_bold_but_keeps_content() -> None:
    from app.services.text import clean_assistant_text

    assert clean_assistant_text("Lokasi ini adalah **Jakarta, Indonesia**.") == (
        "Lokasi ini adalah Jakarta, Indonesia."
    )


def test_deleting_inactive_agent_does_not_change_active_agent(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "delete-inactive.db", open_browser=False)
    db = Database(settings)
    db.initialize()
    agents = db.list_agents()
    indonesian = next(agent for agent in agents if agent["language"] == "id")
    english = next(agent for agent in agents if agent["language"] == "en")
    db.set_setting("active_agent_id", str(indonesian["id"]))
    assert db.delete_agent(english["id"]) is True
    assert int(db.get_setting("active_agent_id", "0")) == indonesian["id"]


def test_packaged_default_scripts_and_company_information(tmp_path: Path) -> None:
    db = Database(Settings(db_path=tmp_path / "packaged-defaults.db", open_browser=False))
    db.initialize()

    scripts = db.list_scripts()
    english = next(script for script in scripts if script["language"] == "en" and script["title"] == "Introduction")
    indonesian = next(script for script in scripts if script["language"] == "id" and script["title"] == "Introduksi")
    assert english["text"] == "Hello and welcome. This is the VerbaNode voice assistant."
    assert english["tts_mode"] == "edge"
    assert english["edge_voice"] == "en-US-AriaNeural"
    assert indonesian["text"] == "Halo dan selamat datang. Ini adalah VerbaNode."
    assert indonesian["tts_mode"] == "edge"
    assert indonesian["edge_voice"] == "id-ID-GadisNeural"

    info = next(item for item in db.list_information() if item["title"] == "Sari Teknologi Company Profile")
    assert info["enabled"] == 1
    assert "more than 15 years of experience" in info["content"]
    assert "Industry 4.0" in info["content"]
    for agent in db.list_agents():
        assert info["id"] in agent["info_ids"]


def test_packaged_default_seed_is_idempotent_and_preserves_existing_information(tmp_path: Path) -> None:
    db = Database(Settings(db_path=tmp_path / "idempotent-defaults.db", open_browser=False))
    db.initialize()
    info = next(item for item in db.list_information() if item["title"] == "Sari Teknologi Company Profile")
    db.update_information(info["id"], {"title": info["title"], "content": "Operator customized text", "enabled": True})
    before_scripts = len(db.list_scripts())

    db.initialize()

    assert len(db.list_scripts()) == before_scripts
    updated = db.get_information(info["id"])
    assert updated is not None
    assert updated["content"] == "Operator customized text"
