from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.services.llm import OllamaService
from app.services.tools import ToolService


class FakeStreamResponse:
    def __init__(self, lines):
        self.status_code = 200
        self._lines = lines

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeClient:
    requests = []
    responses = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, json):
        self.__class__.requests.append(json)
        return FakeStreamResponse(self.__class__.responses.pop(0))


@pytest.mark.asyncio
async def test_empty_tool_followup_uses_direct_weather_fallback(monkeypatch):
    settings = Settings(open_browser=False)
    tools = ToolService(settings)

    async def fake_execute(name, arguments=None):
        assert name == "get_weather"
        return {
            "location": "Jakarta",
            "country": "Indonesia",
            "temperature_c": 31.5,
            "feels_like_c": 33.0,
            "humidity_percent": 45,
            "wind_kmh": 9.8,
            "weather_code": 0,
        }

    tools.execute = fake_execute
    service = OllamaService(settings, tools)
    FakeClient.requests = []
    FakeClient.responses = [
        [json.dumps({"message": {"content": "", "tool_calls": [{"function": {"name": "get_weather", "arguments": {"location": "Jakarta"}}}]}})],
        [json.dumps({"message": {"thinking": "internal reasoning", "content": ""}})],
    ]
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    tokens = []

    async def on_token(token):
        tokens.append(token)

    reply, _ = await service.chat_stream(
        agent={
            "llm_model": "qwen3.5:0.8b",
            "temperature": 0.2,
            "top_p": 0.8,
            "max_tokens": 220,
            "context_size": 4096,
            "tools_enabled": ["get_weather"],
        },
        messages=[{"role": "user", "content": "What is the weather?"}],
        on_token=on_token,
    )

    assert "Jakarta" in reply
    assert "31.5 degrees Celsius" in reply
    assert tokens and "Jakarta" in tokens[-1]
    assert all(request.get("think") is False for request in FakeClient.requests)


def test_time_fallback_is_spoken_and_concise():
    service = ToolService(Settings(open_browser=False))
    text = service.format_result(
        "get_current_time",
        {"spoken": "Saturday, July 25, 2026 at 10:16 AM", "timezone": "Asia/Jakarta"},
    )
    assert text == "It is currently Saturday, July 25, 2026 at 10:16 AM in the Asia/Jakarta timezone."
