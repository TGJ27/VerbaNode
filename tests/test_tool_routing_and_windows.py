from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.runtime import is_expected_windows_proactor_reset
from app.services.conversation import ConversationManager
from app.services.pipeline import PipelineMonitor
from app.services.tools import ToolService


class WindowsReset(ConnectionResetError):
    winerror = 10054


def test_only_expected_windows_proactor_reset_is_suppressed() -> None:
    expected = {
        "exception": WindowsReset("connection reset"),
        "handle": "<Handle _ProactorBasePipeTransport._call_connection_lost(None)>",
    }
    assert is_expected_windows_proactor_reset(expected) is True
    assert is_expected_windows_proactor_reset(
        {"exception": WindowsReset("connection reset"), "handle": "other_callback"}
    ) is False
    assert is_expected_windows_proactor_reset(
        {"exception": RuntimeError("real application error"), "handle": expected["handle"]}
    ) is False


def test_core_intent_router_is_conservative() -> None:
    tools = ToolService(Settings(open_browser=False))
    enabled = [
        "get_current_time",
        "get_location",
        "get_weather",
        "handle_exit_intent",
    ]

    assert tools.match_core_intent("what time is it?", enabled) == (
        "get_current_time",
        {},
    )
    assert tools.match_core_intent("hello what time is it?", enabled) == (
        "get_current_time",
        {},
    )
    assert tools.match_core_intent(
        "Hey Ropi, can you tell me the time right now?", enabled
    ) == ("get_current_time", {})
    assert tools.match_core_intent("what day its its?", enabled) == (
        "get_current_time",
        {},
    )
    assert tools.match_core_intent("Sekarang jam berapa?", enabled) == (
        "get_current_time",
        {},
    )
    assert tools.match_core_intent("Halo Ropi, sekarang jam berapa?", enabled) == (
        "get_current_time",
        {},
    )
    assert tools.match_core_intent("Where are we?", enabled) == (
        "get_location",
        {},
    )
    assert tools.match_core_intent("What's the weather in Bandung?", enabled) == (
        "get_weather",
        {"location": "bandung"},
    )
    assert tools.match_core_intent("Hi, what's the weather like?", enabled) == (
        "get_weather",
        {},
    )
    assert tools.match_core_intent("Hello Ropi, where are we?", enabled) == (
        "get_location",
        {},
    )
    assert tools.match_core_intent("What is time complexity?", enabled) is None
    assert tools.match_core_intent("What time does the meeting start?", enabled) is None
    assert tools.match_core_intent("What time is it?", []) is None


@pytest.mark.asyncio
async def test_obvious_time_request_bypasses_llm(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "test.db",
        open_browser=False,
        default_timezone="Asia/Jakarta",
    )
    db = Database(settings)
    db.initialize()
    tools = ToolService(settings)

    class Events:
        def __init__(self) -> None:
            self.items: list[tuple[str, dict]] = []

        async def broadcast(self, name: str, payload: dict) -> None:
            self.items.append((name, payload))

    class Llm:
        def __init__(self) -> None:
            self.tools = tools

        @staticmethod
        def build_system_prompt(agent, information, summary) -> str:
            return "test"

        async def chat_stream(self, **kwargs):
            raise AssertionError("The LLM must not be called for an obvious time request")

    manager = ConversationManager(
        settings=settings,
        db=db,
        events=Events(),
        recorder=object(),
        stt=object(),
        llm=Llm(),
        tts=object(),
        monitor=PipelineMonitor(),
    )

    async def no_summary(*args, **kwargs) -> None:
        return None

    manager._maybe_summarize = no_summary  # type: ignore[method-assign]
    result = await manager.process_user_text(
        text="hello what time is it?",
        conversation_id=None,
        source="text",
        speak=False,
        allow_barge_in=False,
    )
    await asyncio.sleep(0)

    assert result["message"]["source"] == "tool"
    assert "Asia/Jakarta" in result["message"]["content"]
    assert manager.monitor.snapshot()["latency_ms"]["tool_total"] >= 0
