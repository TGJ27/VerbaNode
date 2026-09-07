from __future__ import annotations

from pathlib import Path

from app.api.client_contract import feature_manifest
from app.config import Settings
from app.db import Database
from app.migrations import CURRENT_SCHEMA_VERSION
from app.services.audio_library import AudioLibraryManager
from app.services.events import EventHub
from app.services.script_defaults import get_script_defaults, save_script_defaults
from app.version import APP_VERSION


class _Player:
    def stop(self) -> None:
        return None

    def play_file(self, path: Path, volume: float) -> bool:
        return path.exists() and volume > 0


def _db(tmp_path: Path) -> Database:
    settings = Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
        open_browser=False,
    )
    db = Database(settings)
    db.initialize()
    return db


def test_v092_contract_and_schema() -> None:
    assert APP_VERSION == "0.12.2"
    assert CURRENT_SCHEMA_VERSION >= 14
    features = feature_manifest()
    assert features["type_to_talk_queue"] is True
    assert features["script_defaults"] is True
    assert features["broad_audio_formats"] is True
    assert "flac" in features["audio_library_formats"]
    assert "m4a" in features["audio_library_formats"]


def test_type_to_talk_queue_is_persistent_and_reorderable(tmp_path: Path) -> None:
    db = _db(tmp_path)
    first = db.add_type_to_talk("First announcement")
    second = db.add_type_to_talk("Second announcement")
    assert [row["text"] for row in db.list_type_to_talk_queue()] == [
        "First announcement",
        "Second announcement",
    ]
    db.reorder_type_to_talk([int(second["id"]), int(first["id"])])
    reopened = Database(db.settings)
    reopened.initialize()
    assert [row["text"] for row in reopened.list_type_to_talk_queue()] == [
        "Second announcement",
        "First announcement",
    ]


def test_script_defaults_remember_last_configuration(tmp_path: Path) -> None:
    db = _db(tmp_path)
    saved = save_script_defaults(
        db,
        {
            "language": "en",
            "tts_mode": "edge",
            "edge_voice": "en-US-GuyNeural",
            "tts_rate": 1.15,
            "tts_volume": 0.8,
        },
    )
    assert saved["edge_voice"] == "en-US-GuyNeural"
    assert saved["tts_rate"] == 1.15
    assert saved["tts_volume"] == 0.8
    assert get_script_defaults(Database(db.settings))["edge_voice"] == "en-US-GuyNeural"


def test_audio_library_accepts_common_formats(tmp_path: Path) -> None:
    manager = AudioLibraryManager(tmp_path / "audio", _Player(), EventHub())
    names = ["a.wav", "b.mp3", "c.mpeg", "d.mpga", "e.mp2", "f.flac", "g.ogg", "h.opus", "i.m4a", "j.aac", "k.webm"]
    for name in names:
        manager.save(name, b"test-audio-payload")
    assert {item["name"] for item in manager.list_files()} == set(names)


def test_script_ui_uses_last_saved_configuration_inside_create_dialog() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="scriptDefaultLanguage"' not in html
    assert 'id="saveScriptDefaultsBtn"' not in html
    assert "const remembered = item || appState.scriptDefaults || {};" in js
    assert 'name="tts_rate"' in js
    assert 'name="tts_volume"' in js
    assert "await loadScriptDefaults();" in js


def test_type_to_talk_has_independent_tts_settings(tmp_path: Path) -> None:
    from app.services.type_to_talk_settings import get_type_to_talk_settings, save_type_to_talk_settings
    db = _db(tmp_path)
    saved = save_type_to_talk_settings(db, {
        "language": "id", "tts_mode": "kokoro", "edge_voice": "en-US-AriaNeural",
        "kokoro_voice_id": 4, "tts_rate": 1.2, "tts_volume": 0.75,
    })
    assert saved["language"] == "id"
    assert saved["tts_mode"] == "edge"
    assert saved["edge_voice"].startswith("id-")
    assert saved["tts_rate"] == 1.2
    assert saved["tts_volume"] == 0.75
    assert get_type_to_talk_settings(db)["language"] == "id"
