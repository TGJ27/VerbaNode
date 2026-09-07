from __future__ import annotations

import asyncio
from pathlib import Path

from app.api.client_contract import feature_manifest
from app.config import Settings
from app.db import Database
from app.migrations import CURRENT_SCHEMA_VERSION
from app.services.audio_library import AudioLibraryError, AudioLibraryManager
from app.services.events import EventHub
from app.services.script_queue import ScriptQueueManager
from app.version import APP_VERSION


class _Player:
    def stop(self) -> None:
        return None

    def play_file(self, path: Path, volume: float) -> bool:
        return path.exists() and volume > 0


class _Tts:
    def stop_current(self) -> None:
        return None


def _db(tmp_path: Path) -> Database:
    settings = Settings(db_path=tmp_path / "verbanode.db", backup_path=tmp_path / "backups", open_browser=False)
    db = Database(settings)
    db.initialize()
    return db


def test_v091_contract_and_dashboard_surface() -> None:
    assert APP_VERSION == "0.12.3"
    assert CURRENT_SCHEMA_VERSION >= 14
    features = feature_manifest()
    assert features["audio_library"] is True
    assert features["script_queue_loop"] is True
    assert features["script_queue_pause"] is True
    assert features["stable_instance_identity"] is True

    root = Path(__file__).resolve().parent.parent
    html = (root / "app/static/index.html").read_text(encoding="utf-8")
    assert 'data-page="audio"' in html
    assert 'id="audioLibraryUpload"' in html
    assert 'id="queueLoopToggle"' in html
    assert '/static/js/audio-library.js?v=0.12.3' in html


def test_queue_pause_is_persistent_and_reorderable(tmp_path: Path) -> None:
    db = _db(tmp_path)
    script = db.create_script({"title": "One", "text": "Hello", "enabled": True})
    first = db.queue_script(int(script["id"]), pause_after_seconds=2.5)
    second = db.queue_script(int(script["id"]), pause_after_seconds=0.0)
    assert db.list_queue()[0]["pause_after_seconds"] == 2.5
    db.update_queue_item_pause(int(second["id"]), 4.0)
    db.reorder_queue([int(second["id"]), int(first["id"])])
    queue = db.list_queue()
    assert [int(item["id"]) for item in queue] == [int(second["id"]), int(first["id"])]
    assert queue[0]["pause_after_seconds"] == 4.0


def test_queue_loop_setting_survives_manager_recreation(tmp_path: Path) -> None:
    db = _db(tmp_path)
    manager = ScriptQueueManager(db, _Tts(), EventHub(), lambda: {})
    asyncio.run(manager.set_loop(True))
    recreated = ScriptQueueManager(db, _Tts(), EventHub(), lambda: {})
    assert recreated.loop_enabled is True


def test_audio_library_accepts_mp3_wav_and_rejects_other_extensions(tmp_path: Path) -> None:
    manager = AudioLibraryManager(tmp_path / "audio", _Player(), EventHub())
    wav = manager.save("alert.wav", b"RIFF-test")
    mp3 = manager.save("music.mp3", b"ID3-test")
    assert {item["name"] for item in manager.list_files()} == {wav["name"], mp3["name"]}
    renamed = manager.rename("music.mp3", "theme.mp3")
    assert renamed["name"] == "theme.mp3"
    try:
        manager.save("bad.txt", b"no")
    except AudioLibraryError:
        pass
    else:
        raise AssertionError("unsupported audio extension should be rejected")
