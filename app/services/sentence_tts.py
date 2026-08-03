from __future__ import annotations

import asyncio
import logging
import re
import threading
from typing import Any

import numpy as np

from app.services.audio import AudioUnavailable
from app.services.events import EventHub
from app.services.tts import GeneratedSpeech, TtsService, TtsUnavailable

LOGGER = logging.getLogger(__name__)


class SentenceChunker:
    """Incrementally convert streamed LLM tokens into natural TTS chunks."""

    _ABBREVIATIONS = {
        "mr.", "mrs.", "ms.", "dr.", "prof.", "sr.", "jr.", "st.", "vs.",
        "etc.", "e.g.", "i.e.", "a.m.", "p.m.", "u.s.", "u.k.", "no.",
        "fig.", "dept.", "inc.", "ltd.", "co.", "approx.", "est.",
    }
    _CLOSERS = {'"', "'", "’", "”", ")", "]", "}"}

    def __init__(
        self,
        *,
        min_chars: int = 5,
        max_chars: int = 180,
        first_clause_min_chars: int = 24,
        first_clause_max_chars: int = 72,
    ):
        self.min_chars = min_chars
        self.max_chars = max_chars
        self.first_clause_min_chars = first_clause_min_chars
        self.first_clause_max_chars = first_clause_max_chars
        self._buffer = ""
        self._emitted_count = 0

    @property
    def buffered_text(self) -> str:
        return self._buffer

    def feed(self, fragment: str) -> list[str]:
        if not fragment:
            return []
        self._buffer += fragment
        chunks: list[str] = []
        while True:
            boundary = self._find_sentence_boundary()
            if boundary is None and self._emitted_count == 0:
                boundary = self._find_first_clause_boundary()
            if boundary is None and len(self._buffer) >= self.max_chars:
                boundary = self._find_forced_boundary()
            if boundary is None:
                break
            chunk = self._buffer[:boundary].strip()
            self._buffer = self._buffer[boundary:].lstrip()
            if chunk:
                chunks.append(chunk)
                self._emitted_count += 1
        return chunks

    def flush(self) -> list[str]:
        chunk = self._buffer.strip()
        self._buffer = ""
        return [chunk] if chunk else []

    def _find_sentence_boundary(self) -> int | None:
        text = self._buffer
        for index, char in enumerate(text):
            if char == "\n":
                candidate = text[:index].strip()
                if len(candidate) >= self.min_chars:
                    return index + 1
                continue
            if char not in ".?!":
                continue
            if char == "." and self._is_protected_period(index):
                continue

            end = index + 1
            while end < len(text) and text[end] in self._CLOSERS:
                end += 1

            # Wait for following whitespace before committing a sentence. The
            # final remainder is emitted by flush() when generation ends.
            if end < len(text) and text[end].isspace() and len(text[:end].strip()) >= self.min_chars:
                return end
        return None

    def _find_first_clause_boundary(self) -> int | None:
        """Emit one natural early clause to reduce time-to-first-audio."""
        text = self._buffer
        if len(text) < self.first_clause_min_chars:
            return None
        window = text[: self.first_clause_max_chars]
        for index, char in enumerate(window):
            if char not in ",;:":
                continue
            end = index + 1
            if end < len(text) and text[end].isspace() and len(text[:end].strip()) >= self.first_clause_min_chars:
                return end
        return None

    def _is_protected_period(self, index: int) -> bool:
        text = self._buffer
        previous = text[index - 1] if index > 0 else ""
        following = text[index + 1] if index + 1 < len(text) else ""
        if previous.isdigit() and following.isdigit():
            return True

        prefix = text[: index + 1]
        match = re.search(r"([A-Za-z](?:[A-Za-z.]*)\.)$", prefix)
        token = match.group(1).lower() if match else ""
        if token in self._ABBREVIATIONS:
            return True
        if re.search(r"(?:\b[A-Za-z]\.){2,}$", prefix):
            return True
        return False

    def _find_forced_boundary(self) -> int:
        window = self._buffer[: self.max_chars]
        minimum = max(self.min_chars, self.max_chars // 2)
        for separators in ((";", ":", ",", "\n"), (" ",)):
            positions = [window.rfind(separator) for separator in separators]
            best = max(positions)
            if best >= minimum:
                return best + 1
        return self.max_chars


class StreamingTtsSession:
    """Generate sentence audio while earlier sentence audio is playing."""

    _END = object()

    def __init__(
        self,
        *,
        tts: TtsService,
        events: EventHub,
        agent: dict[str, Any],
        source: str = "assistant",
        turn_id: str | None = None,
        generation_id: str | None = None,
    ):
        self.tts = tts
        self.events = events
        self.agent = agent
        self.source = source
        self.turn_id = turn_id
        self.generation_id = generation_id
        self.chunker = SentenceChunker()
        self.started = asyncio.Event()  # first audio chunk actually starts playback
        self.finished = asyncio.Event()
        self.cancelled = threading.Event()
        self._text_queue: asyncio.Queue[tuple[int, str] | object] = asyncio.Queue(
            maxsize=int(getattr(getattr(tts, "settings", None), "tts_text_queue_size", 8))
        )
        self._audio_queue: asyncio.Queue[tuple[int, str, GeneratedSpeech] | object] = asyncio.Queue(
            maxsize=int(getattr(getattr(tts, "settings", None), "tts_audio_queue_size", 4))
        )
        self._generator_task: asyncio.Task | None = None
        self._player_task: asyncio.Task | None = None
        self._speech_id: int | None = None
        self._input_closed = False
        self._stopped_event_sent = False
        self._chunk_index = 0

    @property
    def active(self) -> bool:
        tasks = (self._generator_task, self._player_task)
        return any(task and not task.done() for task in tasks)

    async def feed(self, fragment: str) -> None:
        if self.cancelled.is_set() or self._input_closed:
            return
        for chunk in self.chunker.feed(fragment):
            await self._enqueue(chunk)

    async def close_input(self) -> None:
        if self._input_closed:
            return
        self._input_closed = True
        if not self.cancelled.is_set():
            for chunk in self.chunker.flush():
                await self._enqueue(chunk)
        if self._generator_task:
            await self._text_queue.put(self._END)
        else:
            self.started.set()
            self.finished.set()

    async def wait_finished(self) -> None:
        await self.close_input()
        tasks = [task for task in (self._generator_task, self._player_task) if task]
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                    LOGGER.error("Streaming TTS task failed: %s", result)

    def cancel_nowait(self) -> None:
        self.cancelled.set()
        self.tts.stop_current()

    async def cancel(self) -> None:
        self.cancel_nowait()
        self._input_closed = True
        self.chunker.flush()
        if self._generator_task:
            await self._text_queue.put(self._END)
        else:
            self.started.set()
            self.finished.set()

    async def _enqueue(self, chunk: str) -> None:
        chunk = chunk.strip()
        if not chunk or self.cancelled.is_set():
            return
        self._chunk_index += 1
        index = self._chunk_index
        if self._generator_task is None:
            self._speech_id = self.tts.begin_speech()
            self._generator_task = asyncio.create_task(self._generator(), name="assistant-tts-generator")
            self._player_task = asyncio.create_task(self._player(), name="assistant-tts-player")
            await self.events.broadcast(
                "tts_started",
                {"source": self.source, "text": chunk, "streaming": True, "phase": "preparing", "turn_id": self.turn_id, "generation_id": self.generation_id},
            )
        LOGGER.info("Queued TTS sentence %d: %s", index, chunk[:120])
        await self._text_queue.put((index, chunk))

    async def _generator(self) -> None:
        try:
            while True:
                item = await self._text_queue.get()
                if item is self._END:
                    break
                index, chunk = item
                if self.cancelled.is_set():
                    continue
                await self.events.broadcast(
                    "tts_chunk_generating",
                    {"source": self.source, "index": index, "text": chunk, "turn_id": self.turn_id, "generation_id": self.generation_id},
                )
                try:
                    generated = await asyncio.to_thread(
                        self.tts.generate_audio_blocking,
                        chunk,
                        self.agent,
                        self._speech_id,
                    )
                except (TtsUnavailable, AudioUnavailable) as exc:
                    self.cancelled.set()
                    await self.events.broadcast("error", {"message": str(exc), "source": "tts"})
                    break
                if generated is None:
                    continue
                if self.cancelled.is_set():
                    self.tts.cleanup_generated(generated)
                    continue
                await self._audio_queue.put((index, chunk, generated))
        finally:
            await self._audio_queue.put(self._END)

    async def _player(self) -> None:
        try:
            while True:
                item = await self._audio_queue.get()
                if item is self._END:
                    break
                index, chunk, generated = item
                if self.cancelled.is_set():
                    self.tts.cleanup_generated(generated)
                    continue
                self.started.set()
                LOGGER.info("Playing TTS sentence %d via %s", index, generated.provider)
                await self.events.broadcast(
                    "tts_chunk",
                    {
                        "source": self.source,
                        "index": index,
                        "text": chunk,
                        "provider": generated.provider,
                        "cached": generated.cached,
                        "turn_id": self.turn_id,
                        "generation_id": self.generation_id,
                    },
                )
                try:
                    played = await asyncio.to_thread(
                        self.tts.play_generated_blocking,
                        generated,
                        self.agent,
                        self._speech_id,
                    )
                    if not played and self.cancelled.is_set():
                        break
                except (TtsUnavailable, AudioUnavailable) as exc:
                    self.cancelled.set()
                    await self.events.broadcast("error", {"message": str(exc), "source": "tts"})
                    break
        finally:
            self.started.set()
            self.finished.set()
            if not self._stopped_event_sent:
                self._stopped_event_sent = True
                await self.events.broadcast("tts_stopped", {"source": self.source, "turn_id": self.turn_id, "generation_id": self.generation_id})


def empty_audio() -> np.ndarray:
    return np.empty(0, dtype=np.float32)
