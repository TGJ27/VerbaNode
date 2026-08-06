from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services.sentence_tts import StreamingTtsSession


class FakeEvents:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    async def broadcast(self, event: str, payload: dict) -> None:
        self.items.append((event, payload))


class FakeTts:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(tts_text_queue_size=8, tts_audio_queue_size=4)
        self.stop_count = 0
        self.cleaned: list[object] = []

    def stop_current(self) -> None:
        self.stop_count += 1

    def cleanup_generated(self, generated: object) -> None:
        self.cleaned.append(generated)


@pytest.mark.asyncio
async def test_cancel_reinserts_audio_end_marker_after_drain() -> None:
    """Regression: typed input during speech must not wedge the next turn."""
    events = FakeEvents()
    session = StreamingTtsSession(
        tts=FakeTts(),
        events=events,
        agent={},
        turn_id="turn-1",
        generation_id="generation-1",
    )

    # Reproduce the old race: the generator has finished and queued _END, but
    # the player has not consumed it yet. cancel() used to drain that marker and
    # leave the player blocked on queue.get() forever.
    session._player_task = asyncio.create_task(session._player())
    session._audio_queue.put_nowait(session._END)

    await asyncio.wait_for(session.cancel(), timeout=1.0)
    await asyncio.wait_for(session.wait_finished(), timeout=1.0)

    assert session.finished.is_set()
    assert session._player_task.done()
    assert session.tts.stop_count >= 1
    assert [name for name, _payload in events.items].count("tts_stopped") == 1


@pytest.mark.asyncio
async def test_cancel_is_idempotent_and_never_leaves_worker_waiting() -> None:
    events = FakeEvents()
    session = StreamingTtsSession(
        tts=FakeTts(),
        events=events,
        agent={},
        turn_id="turn-2",
        generation_id="generation-2",
    )
    session._player_task = asyncio.create_task(session._player())

    await asyncio.wait_for(session.cancel(), timeout=1.0)
    await asyncio.wait_for(session.cancel(), timeout=1.0)

    assert session.finished.is_set()
    assert session._player_task.done()
    assert [name for name, _payload in events.items].count("tts_stopped") == 1
