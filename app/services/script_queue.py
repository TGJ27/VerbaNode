from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from app.db import Database
from app.services.events import EventHub
from app.services.tts import TtsService

LOGGER = logging.getLogger(__name__)


class ScriptQueueManager:
    def __init__(
        self,
        db: Database,
        tts: TtsService,
        events: EventHub,
        get_active_agent: Callable[[], dict[str, Any]],
    ):
        self.db = db
        self.tts = tts
        self.events = events
        self.get_active_agent = get_active_agent
        self._task: asyncio.Task | None = None
        self._paused = True
        self._stopping = False

    @property
    def state(self) -> str:
        if self._task and not self._task.done() and not self._paused:
            return "playing"
        return "paused"

    async def notify(self) -> None:
        await self.events.broadcast(
            "queue_state",
            {"state": self.state, "items": self.db.list_queue()},
        )

    async def add(self, script_id: int) -> dict[str, Any]:
        item = self.db.queue_script(script_id)
        await self.notify()
        return item

    async def _speak_cached_script(
        self,
        *,
        text: str,
        agent: dict[str, Any],
        speech_id: int,
        source: str,
        queue_id: int | None = None,
    ) -> bool:
        generated = await asyncio.to_thread(
            self.tts.generate_audio_blocking,
            text,
            agent,
            speech_id,
            use_cache=True,
            cache_namespace="script",
        )
        if generated is None:
            return False
        payload = {
            "source": source,
            "text": text,
            "provider": generated.provider,
            "cached": generated.cached,
        }
        if queue_id is not None:
            payload["queue_id"] = queue_id
        await self.events.broadcast("tts_chunk", payload)
        return await asyncio.to_thread(
            self.tts.play_generated_blocking, generated, agent, speech_id
        )

    async def run_now(self, script_id: int) -> None:
        script = self.db.get_script(script_id)
        if not script or not script.get("enabled"):
            raise ValueError("Script not found or disabled")
        self.db.clear_queue()
        self._paused = True
        speech_id = self.tts.begin_speech()
        await self.notify()
        agent = self.get_active_agent()
        await self.events.broadcast("tts_started", {"source": "script", "text": script["text"]})
        try:
            played = await self._speak_cached_script(
                text=script["text"],
                agent=agent,
                speech_id=speech_id,
                source="script",
            )
            if not played:
                LOGGER.warning("Run-now script playback was cancelled or produced no audio")
        except Exception as exc:
            LOGGER.exception("Run-now script failed")
            await self.events.broadcast("error", {"message": str(exc), "source": "script"})
        finally:
            await self.events.broadcast("tts_stopped", {"source": "script"})

    async def play(self) -> None:
        self._paused = False
        self._stopping = False
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._worker(), name="script-queue")
        await self.notify()

    async def pause(self) -> None:
        self._paused = True
        await self.notify()

    async def stop(self) -> None:
        self._paused = True
        self._stopping = True
        self.tts.stop_current()
        await self.notify()

    async def clear(self) -> None:
        self.db.clear_queue()
        await self.notify()

    async def remove(self, queue_id: int) -> None:
        self.db.remove_queue_item(queue_id)
        await self.notify()

    async def reorder(self, ordered_ids: list[int]) -> None:
        self.db.reorder_queue(ordered_ids)
        await self.notify()

    async def interrupt_for_conversation(self) -> None:
        if self.state == "playing":
            self._paused = True
        self.tts.stop_current()
        await self.notify()

    async def _worker(self) -> None:
        while not self._paused:
            item = self.db.pop_next_queue_item()
            if not item:
                self._paused = True
                break
            if not item.get("enabled"):
                self.db.finish_queue_item(int(item["id"]), remove=True)
                continue
            agent = self.get_active_agent()
            speech_id = self.tts.begin_speech()
            await self.events.broadcast(
                "tts_started",
                {"source": "script_queue", "queue_id": item["id"], "text": item["text"]},
            )
            try:
                await self._speak_cached_script(
                    text=item["text"],
                    agent=agent,
                    speech_id=speech_id,
                    source="script_queue",
                    queue_id=int(item["id"]),
                )
                # A played or manually interrupted item is consumed; remaining items stay queued.
                self.db.finish_queue_item(int(item["id"]), remove=True)
            except Exception as exc:
                LOGGER.exception("Queued script failed")
                self.db.finish_queue_item(int(item["id"]), remove=True)
                await self.events.broadcast("error", {"message": str(exc), "source": "script_queue"})
            finally:
                self._stopping = False
                await self.events.broadcast("tts_stopped", {"source": "script_queue"})
                await self.notify()
        await self.notify()
