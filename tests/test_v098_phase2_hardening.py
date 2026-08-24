from __future__ import annotations

import asyncio
from pathlib import Path

from app.services.audio_library import AudioLibraryManager
from app.services.events import EventHub


class _Player:
    def stop(self) -> None:
        return None

    def play_file(self, path: Path, volume: float) -> bool:
        return path.exists() and volume > 0


def test_audio_library_duplicate_filename_can_be_deleted(tmp_path: Path) -> None:
    """Regression: collision names such as ``clip (2).mp3`` must resolve exactly."""
    manager = AudioLibraryManager(tmp_path / "audio", _Player(), EventHub())
    manager.save("clip.mp3", b"first")
    duplicate = manager.save("clip.mp3", b"second")

    assert duplicate["name"] == "clip (2).mp3"
    assert asyncio.run(manager.delete(duplicate["name"])) is True
    assert {item["name"] for item in manager.list_files()} == {"clip.mp3"}


def test_audio_library_existing_legacy_name_is_not_resanitized(tmp_path: Path) -> None:
    directory = tmp_path / "audio"
    directory.mkdir()
    legacy = directory / "legacy (voice) [old].mp3"
    legacy.write_bytes(b"legacy")
    manager = AudioLibraryManager(directory, _Player(), EventHub())

    assert {item["name"] for item in manager.list_files()} == {legacy.name}
    assert asyncio.run(manager.delete(legacy.name)) is True
    assert not legacy.exists()


def test_audio_library_delete_missing_item_is_idempotent(tmp_path: Path) -> None:
    manager = AudioLibraryManager(tmp_path / "audio", _Player(), EventHub())
    assert asyncio.run(manager.delete("already-gone.mp3")) is False
