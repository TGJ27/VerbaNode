from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.audio import AudioUnavailable
from app.services.events import EventHub

LOGGER = logging.getLogger(__name__)
_ALLOWED_SUFFIXES = {
    ".wav", ".mp3", ".mpeg", ".mpg", ".mpga", ".mp2", ".mpa",
    ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".wma",
    ".aiff", ".aif", ".webm", ".mka", ".amr",
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


class AudioLibraryError(ValueError):
    pass


def _safe_filename(value: str) -> str:
    name = Path(str(value or "audio")).name.strip()
    name = _SAFE_NAME.sub("_", name).strip(" .")
    if not name:
        name = "audio"
    suffix = Path(name).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        raise AudioLibraryError("Unsupported audio format. Use WAV, MP3/MPEG, MP2/MPA/MPGA, FLAC, OGG/OGA, Opus, M4A, AAC, WMA, AIFF/AIF, WebM audio, MKA, or AMR")
    stem = Path(name).stem[:120].strip(" .") or "audio"
    return f"{stem}{suffix}"


class AudioLibraryManager:
    def __init__(self, directory: Path, player: Any, events: EventHub):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.player = player
        self.events = events
        self._task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._playing_name: str | None = None

    @property
    def playing_name(self) -> str | None:
        return self._playing_name

    def _new_path(self, name: str) -> Path:
        """Return a sanitized destination path for a new/renamed library item."""
        safe = _safe_filename(name)
        path = (self.directory / safe).resolve()
        if path.parent != self.directory.resolve():
            raise AudioLibraryError("Invalid audio filename")
        return path

    def _existing_path(self, name: str) -> Path:
        """Resolve an existing library item by its exact displayed filename.

        Existing names must not be sanitized again. Collision handling deliberately
        creates names such as ``track (2).mp3`` and older VerbaNode versions may
        also have written filenames containing characters that the current upload
        sanitizer replaces. Re-sanitizing a name returned by ``list_files()`` can
        therefore point at a different, non-existent file.
        """
        raw = str(name or "").strip()
        if not raw or raw in {".", ".."} or "/" in raw or "\\" in raw or "\x00" in raw:
            raise AudioLibraryError("Invalid audio filename")
        if Path(raw).suffix.lower() not in _ALLOWED_SUFFIXES:
            raise AudioLibraryError("Unsupported audio format")
        path = (self.directory / raw).resolve()
        if path.parent != self.directory.resolve():
            raise AudioLibraryError("Invalid audio filename")
        return path

    @staticmethod
    def _metadata(path: Path, *, playing: bool = False) -> dict[str, Any]:
        stat = path.stat()
        duration: float | None = None
        try:
            import soundfile as sf

            info = sf.info(str(path))
            if info.samplerate:
                duration = round(float(info.frames) / float(info.samplerate), 3)
        except Exception:
            duration = None
        return {
            "name": path.name,
            "size_bytes": int(stat.st_size),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(timespec="seconds"),
            "duration_seconds": duration,
            "playing": bool(playing),
        }

    def list_files(self) -> list[dict[str, Any]]:
        files = []
        for path in self.directory.iterdir():
            if not path.is_file() or path.suffix.lower() not in _ALLOWED_SUFFIXES:
                continue
            files.append(self._metadata(path, playing=path.name == self._playing_name))
        files.sort(key=lambda item: str(item["name"]).casefold())
        return files

    def save(self, filename: str, payload: bytes) -> dict[str, Any]:
        if not payload:
            raise AudioLibraryError("Audio upload is empty")
        path = self._new_path(filename)
        candidate = path
        counter = 2
        while candidate.exists():
            candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
            counter += 1
        candidate.write_bytes(payload)
        return self._metadata(candidate)

    def rename(self, old_name: str, new_name: str) -> dict[str, Any]:
        old_path = self._existing_path(old_name)
        if not old_path.exists():
            raise FileNotFoundError(old_name)
        new_path = self._new_path(new_name)
        if new_path.exists() and new_path != old_path:
            raise AudioLibraryError("An audio file with that name already exists")
        old_path.replace(new_path)
        if self._playing_name == old_path.name:
            self._playing_name = new_path.name
        return self._metadata(new_path, playing=self._playing_name == new_path.name)

    async def delete(self, name: str) -> bool:
        path = self._existing_path(name)
        if not path.exists():
            return False
        if self._playing_name == path.name:
            await self.stop()
        path.unlink(missing_ok=True)
        await self.events.broadcast("audio_library_changed", {"items": self.list_files()})
        return True

    async def play(self, name: str) -> None:
        path = self._existing_path(name)
        if not path.exists():
            raise FileNotFoundError(name)
        async with self._lock:
            await self.stop()
            self._playing_name = path.name
            await self.events.broadcast(
                "audio_library_state",
                {"state": "playing", "name": path.name, "items": self.list_files()},
            )
            self._task = asyncio.create_task(self._play_worker(path), name=f"audio-library:{path.name}")

    async def _play_worker(self, path: Path) -> None:
        try:
            played = await asyncio.to_thread(self.player.play_file, path, 1.0)
            if not played:
                LOGGER.info("Audio library playback stopped: %s", path.name)
        except Exception as exc:
            LOGGER.exception("Audio library playback failed: %s", path.name)
            await self.events.broadcast("error", {"source": "audio_library", "message": str(exc)})
        finally:
            if self._playing_name == path.name:
                self._playing_name = None
            self._task = None
            await self.events.broadcast(
                "audio_library_state",
                {"state": "idle", "name": None, "items": self.list_files()},
            )

    async def stop(self) -> None:
        task = self._task
        if task is None and self._playing_name is None:
            return
        try:
            self.player.stop()
        except Exception:
            LOGGER.debug("Audio library player stop failed", exc_info=True)
        if task is not None and task is not asyncio.current_task():
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=2.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass
        self._playing_name = None
        if self._task is task:
            self._task = None
        await self.events.broadcast(
            "audio_library_state",
            {"state": "idle", "name": None, "items": self.list_files()},
        )


__all__ = ["AudioLibraryError", "AudioLibraryManager"]
