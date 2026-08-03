from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from app.config import Settings
from app.services.conversation import ConversationManager
from app.services.llm import OllamaService
from app.services.sentence_tts import StreamingTtsSession
from app.services.text import clean_assistant_text, strip_emoji
from app.services.tools import ToolService
from app.services.tts import GeneratedSpeech


class _Events:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    async def broadcast(self, name, payload):
        self.items.append((name, payload))


class _Tts:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.generated: list[str] = []
        self.spoken: list[str] = []
        self.stop_calls = 0
        self._speech_id = 0

    def begin_speech(self) -> int:
        self._speech_id += 1
        return self._speech_id

    def stop_current(self) -> None:
        self.stop_calls += 1

    def generate_audio_blocking(self, text, agent, speech_id):
        self.generated.append(text)
        path = self.tmp_path / f"{len(self.generated)}.wav"
        path.write_bytes(b"wave")
        return GeneratedSpeech(path=path, provider="fake", text=text)

    def play_generated_blocking(self, generated, agent, speech_id):
        self.spoken.append(generated.text)
        self.cleanup_generated(generated)
        return True

    @staticmethod
    def cleanup_generated(generated):
        if generated and not generated.persistent:
            generated.path.unlink(missing_ok=True)


def test_backend_output_sanitizer_removes_emoji_but_preserves_languages() -> None:
    assert clean_assistant_text("Hello 😊 there 👋!") == "Hello there!"
    assert clean_assistant_text("Suhu 30°C di Jakarta.") == "Suhu 30°C di Jakarta."
    assert clean_assistant_text("你好，世界。") == "你好，世界。"
    assert strip_emoji("Ready :) <3") == "Ready  "


def test_hidden_voice_policy_forbids_emoji() -> None:
    settings = Settings(open_browser=False)
    llm = OllamaService(settings, ToolService(settings))
    prompt = llm.build_system_prompt(
        {
            "name": "Ropi",
            "role": "Receptionist",
            "system_prompt": "You are friendly.",
            "tools_enabled": [],
        },
        [],
        None,
    )
    assert "Do not use emoji" in prompt
    assert "emoticons" in prompt


def test_streaming_tts_drops_emoji_only_chunks(tmp_path: Path) -> None:
    async def run():
        tts = _Tts(tmp_path)
        events = _Events()
        session = StreamingTtsSession(tts=tts, events=events, agent={})
        await session.feed("Hello there. 😊 ")
        await session.feed("This stays 👋. ")
        await session.wait_finished()
        return tts

    tts = asyncio.run(run())
    assert tts.generated == ["Hello there.", "This stays."]
    assert tts.spoken == ["Hello there.", "This stays."]


def test_stop_conversation_cancels_tts_by_default() -> None:
    manager = object.__new__(ConversationManager)
    manager._stop_event = threading.Event()
    manager._conversation_task = None
    manager._ptt_active = False
    manager._mode = "conversation"
    manager.monitor = None
    calls: list[str] = []

    class Recorder:
        def cancel_capture(self, wait=True, timeout=2.0):
            calls.append("capture")
            return True

        def cancel_ptt(self):
            calls.append("ptt")

        def unlock_input(self):
            calls.append("unlock")

    class Player:
        output_locked = True

    class Tts:
        player = Player()

    manager.recorder = Recorder()
    manager.tts = Tts()
    manager.events = _Events()

    async def stop_tts():
        calls.append("tts")

    async def set_pipeline(*args, **kwargs):
        return None

    manager.stop_current_tts = stop_tts
    manager._set_pipeline = set_pipeline
    asyncio.run(manager.stop_conversation())

    assert calls[0] == "tts"
    assert calls[1:] == ["capture", "ptt", "unlock"]
