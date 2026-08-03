import asyncio
from types import SimpleNamespace

import numpy as np

from app.services.conversation import ConversationManager


def test_send_text_removes_internal_numpy_audio() -> None:
    manager = object.__new__(ConversationManager)
    manager._conversation_task = None
    manager._ptt_active = False
    manager.script_queue = None
    manager.tts = SimpleNamespace(stop_current=lambda: None)

    async def fake_process_user_text(**kwargs):
        return {
            "message": {"content": "hello"},
            "exit_requested": False,
            "interrupted_audio": np.empty(0, dtype=np.float32),
        }

    manager.process_user_text = fake_process_user_text
    result = asyncio.run(manager.send_text("hello"))
    assert "interrupted_audio" not in result
    assert result["message"]["content"] == "hello"


def test_safe_half_duplex_does_not_open_microphone_during_tts(tmp_path) -> None:
    manager = object.__new__(ConversationManager)
    manager.settings = SimpleNamespace(post_tts_mic_guard_ms=0, barge_in_start_delay_ms=800)
    manager._stop_event = __import__('threading').Event()

    class FakeDb:
        @staticmethod
        def get_runtime_settings():
            return {"interruption_enabled": False}

    class FakeEvents:
        async def broadcast(self, *args, **kwargs):
            return None

    class FakeTts:
        def __init__(self):
            self.spoken = []
        def begin_speech(self):
            return 1
        def speak_blocking(self, text, agent, speech_id, **kwargs):
            self.spoken.append((text, speech_id, kwargs))
            return True
        def stop_current(self):
            raise AssertionError("Safe half-duplex should not stop its own TTS")

    class FakeRecorder:
        def capture_until_silence(self, **kwargs):
            raise AssertionError("Microphone must remain closed while TTS is playing")

    manager.db = FakeDb()
    manager.events = FakeEvents()
    manager.tts = FakeTts()
    manager.recorder = FakeRecorder()

    audio = asyncio.run(manager._speak_reply("Hello", {}, allow_barge_in=True))
    assert audio.size == 0
    assert manager.tts.spoken == [("Hello", 1, {"use_cache": False, "cache_namespace": "assistant"})]


def test_agent_greeting_uses_persistent_tts_cache() -> None:
    manager = object.__new__(ConversationManager)
    manager.settings = SimpleNamespace(post_tts_mic_guard_ms=0, barge_in_start_delay_ms=800)
    manager._stop_event = __import__('threading').Event()

    class FakeDb:
        @staticmethod
        def get_runtime_settings():
            return {"interruption_enabled": False}

    class FakeEvents:
        def __init__(self):
            self.events = []

        async def broadcast(self, name, payload):
            self.events.append((name, payload))

    class FakeTts:
        def __init__(self):
            self.calls = []

        def begin_speech(self):
            return 7

        def speak_blocking(self, text, agent, speech_id, **kwargs):
            self.calls.append((text, speech_id, kwargs))
            return True

        def stop_current(self):
            return None

    manager.db = FakeDb()
    manager.events = FakeEvents()
    manager.tts = FakeTts()
    manager.recorder = SimpleNamespace()

    audio = asyncio.run(
        manager._speak_reply(
            "Welcome to Sari Technology.",
            {"id": 1},
            allow_barge_in=True,
            use_cache=True,
            cache_namespace="greeting",
            source="greeting",
        )
    )
    assert audio.size == 0
    assert manager.tts.calls == [
        (
            "Welcome to Sari Technology.",
            7,
            {"use_cache": True, "cache_namespace": "greeting"},
        )
    ]
    assert manager.events.events[0] == (
        "tts_started",
        {"source": "greeting", "text": "Welcome to Sari Technology."},
    )
    assert manager.events.events[-1] == ("tts_stopped", {"source": "greeting"})
