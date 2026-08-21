from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.db import Database
from app.services.events import EventHub
from app.services.type_to_talk_defaults import (
    get_type_to_talk_defaults,
    resolve_type_to_talk_config,
    save_type_to_talk_defaults,
)

LOGGER = logging.getLogger(__name__)


class TypeToTalkManager:
    """Persistent FIFO text-to-speech queue shared by all clients."""

    def __init__(self, db: Database, tts: Any, events: EventHub):
        self.db = db
        self.tts = tts
        self.events = events
        self._task: asyncio.Task | None = None
        self._paused = True
        self.db.reset_type_to_talk_playing()

    @property
    def state(self) -> str:
        if self._task and not self._task.done() and not self._paused:
            return "playing"
        return "paused" if self.db.pending_type_to_talk_count() else "idle"

    async def notify(self) -> None:
        await self.events.broadcast(
            "type_to_talk_queue",
            {"state": self.state, "items": self.db.list_type_to_talk_transcript()},
        )

    def defaults(self) -> dict[str, Any]:
        return get_type_to_talk_defaults(self.db)

    async def add(self, text: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
        resolved = resolve_type_to_talk_config(self.db, config)
        save_type_to_talk_defaults(self.db, resolved)
        item = self.db.add_type_to_talk(text, resolved)
        await self.play()
        return item

    async def play(self) -> None:
        self._paused = False
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._worker(), name="type-to-talk")
        await self.notify()

    async def stop(self) -> None:
        self._paused = True
        self.tts.stop_current()
        self.db.reset_type_to_talk_playing()
        await self.notify()

    async def clear(self) -> None:
        await self.stop()
        self.db.clear_type_to_talk()
        await self.notify()

    async def remove(self, item_id: int) -> None:
        self.db.remove_type_to_talk(item_id)
        await self.notify()

    async def reorder(self, ordered_ids: list[int]) -> None:
        current = [int(item["id"]) for item in self.db.list_type_to_talk_queue() if item.get("status") == "waiting"]
        current_set = set(current)
        values = [int(value) for value in ordered_ids if int(value) in current_set]
        if sorted(current) != sorted(values):
            raise ValueError("Queue reorder must include each waiting Type-to-Talk item exactly once")
        self.db.reorder_type_to_talk(values)
        await self.notify()

    async def _worker(self) -> None:
        try:
            while not self._paused:
                item = self.db.pop_next_type_to_talk()
                if not item:
                    self._paused = True
                    break
                item_id = int(item["id"])
                text = str(item.get("text") or "").strip()
                if not text:
                    self.db.remove_type_to_talk(item_id)
                    continue
                defaults = resolve_type_to_talk_config(
                    self.db,
                    {
                        "language": item.get("language"),
                        "tts_mode": item.get("tts_mode"),
                        "edge_voice": item.get("edge_voice"),
                        "kokoro_voice_id": item.get("kokoro_voice_id"),
                        "tts_rate": item.get("tts_rate"),
                        "tts_volume": item.get("tts_volume"),
                    },
                )
                speech_id = self.tts.begin_speech()
                await self.notify()
                await self.events.broadcast(
                    "tts_started", {"source": "type_to_talk", "queue_id": item_id, "text": text}
                )
                try:
                    played = await asyncio.to_thread(
                        self.tts.speak_blocking,
                        text,
                        defaults,
                        speech_id,
                        use_cache=False,
                        cache_namespace="type-to-talk",
                    )
                    if played:
                        self.db.complete_type_to_talk(item_id)
                    else:
                        self.db.reset_type_to_talk_playing()
                        self._paused = True
                except Exception as exc:
                    LOGGER.exception("Type-to-Talk playback failed")
                    self.db.remove_type_to_talk(item_id)
                    await self.events.broadcast(
                        "error", {"source": "type_to_talk", "message": str(exc)}
                    )
                finally:
                    await self.events.broadcast("tts_stopped", {"source": "type_to_talk"})
                    await self.notify()
        finally:
            await self.notify()

__all__ = ["TypeToTalkManager"]
