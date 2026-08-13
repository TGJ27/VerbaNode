from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.plugins.builtin.location import LocationPlugin
from app.plugins.context import PluginContext
from app.services.llm import OllamaService
from app.services.memory_context import requires_memory_context, select_memory_context
from app.services.tools import ToolService
from app.services.tts import EdgeTtsProvider


def test_independent_request_does_not_receive_history_or_summary() -> None:
    selection = select_memory_context(
        text="What is a chatbot?",
        summary="The user previously discussed a confidential project.",
        prior_messages=[
            {"role": "user", "content": "My project is VerbaNode."},
            {"role": "assistant", "content": "Understood."},
        ],
        context_size=4096,
    )
    assert selection.required is False
    assert selection.summary is None
    assert selection.messages == []


def test_explicit_recall_gets_only_bounded_recent_context() -> None:
    prior = [
        {"role": "user" if index % 2 == 0 else "assistant", "content": f"message {index}"}
        for index in range(20)
    ]
    selection = select_memory_context(
        text="What were we talking about before?",
        summary="summary " * 1000,
        prior_messages=prior,
        context_size=4096,
    )
    assert selection.required is True
    assert selection.reason == "explicit_recall"
    assert 1 <= len(selection.messages) <= 8
    assert selection.messages[-1]["content"] == "message 19"
    assert selection.summary is not None
    assert len(selection.summary) <= 2201


def test_follow_up_phrases_use_short_term_context() -> None:
    assert requires_memory_context("Tell me more.")[0] is True
    assert requires_memory_context("What about that project?")[0] is True
    assert requires_memory_context("How is the weather today?")[0] is False


def test_location_plugin_accepts_natural_current_location_phrases() -> None:
    plugin = LocationPlugin()
    context = PluginContext(settings=Settings(open_browser=False), text="Where are we currently at?")
    assert plugin.match(context) == {}
    context.text = "Where are we right now?"
    assert plugin.match(context) == {}


def test_edge_voice_provider_has_offline_dropdown_fallback() -> None:
    payload = EdgeTtsProvider(Settings(open_browser=False)).cached_voice_payload()
    names = {voice["short_name"] for voice in payload["voices"]}
    assert "en-US-AriaNeural" in names
    assert "id-ID-GadisNeural" in names
    assert payload["source"] == "built-in-fallback"


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
    responses: list[list[str]] = []
    requests: list[dict] = []

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
async def test_empty_ollama_output_retries_without_tools_and_recovers(monkeypatch) -> None:
    service = OllamaService(Settings(open_browser=False), ToolService(Settings(open_browser=False)))
    FakeClient.responses = [
        [json.dumps({"message": {"content": "", "tool_calls": []}})],
        [json.dumps({"message": {"content": "A chatbot is software that communicates with users."}})],
    ]
    FakeClient.requests = []
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    tokens: list[str] = []

    async def on_token(token: str) -> None:
        tokens.append(token)

    reply, _ = await service.chat_stream(
        agent={
            "llm_model": "qwen3.5:0.8b",
            "temperature": 0.2,
            "top_p": 0.8,
            "max_tokens": 224,
            "context_size": 4096,
            "tools_enabled": ["get_current_time"],
        },
        messages=[
            {"role": "system", "content": "full context"},
            {"role": "user", "content": "What is a chatbot?"},
        ],
        recovery_messages=[
            {"role": "system", "content": "minimal context"},
            {"role": "user", "content": "What is a chatbot?"},
        ],
        on_token=on_token,
    )

    assert reply.startswith("A chatbot")
    assert len(FakeClient.requests) == 2
    assert FakeClient.requests[1]["tools"] == []
    assert FakeClient.requests[1]["messages"][0]["content"] == "minimal context"
    assert tokens[-1].startswith("A chatbot")


def test_edge_voice_dropdown_and_preview_controls_are_in_agent_editor() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    tts_api = (root / "app" / "api" / "tts.py").read_text(encoding="utf-8")
    assert 'id="edgeVoiceSelect"' in html
    assert 'id="edgeVoiceLocaleFilter"' in html
    assert 'id="previewEdgeVoiceBtn"' in html
    assert "function renderEdgeVoiceOptions" in javascript
    assert '"/api/tts/edge-voices"' in tts_api
    assert '"/api/tts/edge-voice-preview"' in tts_api
