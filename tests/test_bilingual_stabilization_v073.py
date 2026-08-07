from __future__ import annotations

from pathlib import Path

from app.schemas import AgentCreate, ScriptCreate, ScriptTtsPreviewRequest
from app.services.stt import FunASRService


def test_whisper_cache_status_reports_base_and_small(tmp_path: Path) -> None:
    (tmp_path / "base.pt").write_bytes(b"base")
    status = FunASRService.whisper_cache_status(tmp_path)
    assert status["root"] == str(tmp_path)
    assert status["models"]["Whisper-base"]["downloaded"] is True
    assert status["models"]["Whisper-base"]["size_bytes"] == 4
    assert status["models"]["Whisper-small"]["downloaded"] is False


def test_english_agent_normalizes_non_english_voice() -> None:
    agent = AgentCreate(
        language="en",
        stt_model="Whisper-small",
        edge_voice="ja-JP-NanamiNeural",
    )
    assert agent.stt_model == "iic/SenseVoiceSmall"
    assert agent.edge_voice == "en-US-AriaNeural"


def test_indonesian_agent_keeps_whisper_small_and_edge_only() -> None:
    agent = AgentCreate(
        language="id",
        stt_model="Whisper-small",
        tts_mode="kokoro_fallback",
        edge_voice="id-ID-GadisNeural",
    )
    assert agent.stt_model == "Whisper-small"
    assert agent.tts_mode == "edge"


def test_script_and_preview_normalize_language_voice_profiles() -> None:
    script = ScriptCreate(
        title="English",
        text="Hello",
        language="en",
        edge_voice="id-ID-GadisNeural",
    )
    assert script.edge_voice == "en-US-AriaNeural"

    preview = ScriptTtsPreviewRequest(
        text="Halo",
        language="id",
        tts_mode="kokoro",
        edge_voice="en-US-AriaNeural",
    )
    assert preview.tts_mode == "edge"
    assert preview.edge_voice == "id-ID-GadisNeural"


def test_bilingual_stabilization_ui_controls_exist() -> None:
    html = Path("app/static/index.html").read_text(encoding="utf-8")
    js = Path("app/static/app.js").read_text(encoding="utf-8")
    assert 'id="asrModelCache"' in html
    assert 'id="testLanguageProfileBtn"' in html
    assert "/api/ai/test-language-profile" in js
    assert "First use will download the model" in js
    assert "Bahasa Indonesia scripts use Edge TTS only" in js


def test_whisper_cache_status_checks_default_home_when_xdg_points_elsewhere(tmp_path: Path, monkeypatch) -> None:
    real_home = tmp_path / "real-home"
    whisper_dir = real_home / ".cache" / "whisper"
    whisper_dir.mkdir(parents=True)
    (whisper_dir / "base.pt").write_bytes(b"base-model")
    (whisper_dir / "small.pt").write_bytes(b"small-model")

    monkeypatch.setenv("HOME", str(real_home))
    monkeypatch.setenv("USERPROFILE", str(real_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "wrong-xdg-cache"))
    monkeypatch.delenv("WHISPER_CACHE_DIR", raising=False)

    status = FunASRService.whisper_cache_status()
    assert status["models"]["Whisper-base"]["downloaded"] is True
    assert status["models"]["Whisper-small"]["downloaded"] is True
    assert Path(status["models"]["Whisper-base"]["path"]) == whisper_dir / "base.pt"
    assert Path(status["models"]["Whisper-small"]["path"]) == whisper_dir / "small.pt"
