from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.schemas import TypeToTalkCreate
from app.services.conversation import ConversationManager
from app.services.events import EventHub
from app.services.pipeline import PipelineMonitor


class _AsyncStopper:
    def __init__(self) -> None:
        self.calls = 0

    async def stop(self) -> None:
        self.calls += 1


class _IdleConversation:
    def __init__(self) -> None:
        self.stop_calls = 0
        self.stop_tts_calls = 0
        self._ptt_active = False
        self._browser_ptt_active = False

    @property
    def is_conversation_running(self) -> bool:
        return False

    async def stop_conversation(self, stop_tts: bool = True) -> None:
        self.stop_calls += 1
        raise AssertionError("idle Type-to-Talk must not tear down conversation audio")

    async def stop_current_tts(self) -> None:
        self.stop_tts_calls += 1

    async def cancel_ptt(self) -> None:
        raise AssertionError("PTT is not active")

    async def cancel_browser_ptt(self) -> None:
        raise AssertionError("browser PTT is not active")


class _TypeToTalk:
    state = "idle"

    def __init__(self) -> None:
        self.added: list[str] = []

    async def add(self, text: str) -> dict[str, object]:
        self.added.append(text)
        return {"id": 1, "text": text, "status": "waiting"}


class _FailingRecorder:
    def cancel_capture(self, *_args, **_kwargs) -> bool:
        raise RuntimeError("audio engine restarting")

    def cancel_ptt(self) -> None:
        raise RuntimeError("audio engine restarting")

    def unlock_input(self) -> None:
        raise RuntimeError("audio engine restarting")


class _Tts:
    def __init__(self) -> None:
        self.player = SimpleNamespace(output_locked=False)
        self.stop_calls = 0

    def stop_current(self) -> None:
        self.stop_calls += 1


def test_idle_type_to_talk_does_not_stop_conversation_audio(monkeypatch) -> None:
    import app.api.type_to_talk as api

    conversation = _IdleConversation()
    script_queue = _AsyncStopper()
    audio_library = _AsyncStopper()
    type_to_talk = _TypeToTalk()
    fake_state = SimpleNamespace(
        conversation=conversation,
        script_queue=script_queue,
        audio_library=audio_library,
        type_to_talk=type_to_talk,
    )
    monkeypatch.setattr(api, "state", fake_state)

    result = asyncio.run(api.add_type_to_talk(TypeToTalkCreate(text="hello"), "test-token"))

    assert result["text"] == "hello"
    assert conversation.stop_calls == 0
    assert conversation.stop_tts_calls == 1
    assert script_queue.calls == 1
    assert audio_library.calls == 1
    assert type_to_talk.added == ["hello"]


def test_stop_conversation_is_best_effort_when_audio_engine_is_restarting() -> None:
    tts = _Tts()
    manager = ConversationManager(
        settings=SimpleNamespace(),
        db=SimpleNamespace(),
        events=EventHub(),
        recorder=_FailingRecorder(),
        stt=SimpleNamespace(),
        llm=SimpleNamespace(tools=None),
        tts=tts,
        monitor=PipelineMonitor(),
    )

    asyncio.run(manager.stop_conversation(stop_tts=True))

    assert manager.mode == "idle"
    assert tts.stop_calls == 1
