from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config import Settings
from app.services.tools import ToolService

LOGGER = logging.getLogger(__name__)
TokenCallback = Callable[[str], Awaitable[None]]
ToolCallback = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[None]]


class OllamaUnavailable(RuntimeError):
    pass


class OllamaService:
    def __init__(self, settings: Settings, tools: ToolService):
        self.settings = settings
        self.tools = tools

    async def list_models(self) -> list[dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(f"{self.settings.ollama_url}/api/tags")
                response.raise_for_status()
                return response.json().get("models", [])
        except Exception as exc:
            raise OllamaUnavailable(f"Cannot connect to Ollama: {exc}") from exc

    async def pull_model(self, model: str, on_status: TokenCallback | None = None) -> None:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self.settings.ollama_url}/api/pull",
                    json={"model": model, "stream": True},
                ) as response:
                    if response.status_code >= 400:
                        error_body = (await response.aread()).decode("utf-8", errors="replace")
                        raise OllamaUnavailable(
                            f"Ollama returned {response.status_code}: {error_body[:500]}"
                        )
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        payload = json.loads(line)
                        if on_status:
                            await on_status(payload.get("status", ""))
        except Exception as exc:
            raise OllamaUnavailable(f"Model pull failed: {exc}") from exc

    def build_system_prompt(
        self,
        agent: dict[str, Any],
        information: list[dict[str, Any]],
        summary: str | None,
    ) -> str:
        sections = [
            f"ROLE: {agent.get('role', '')}",
            str(agent.get("system_prompt") or ""),
            "The application is a voice assistant. Produce natural spoken English. Avoid markdown tables and excessive formatting unless specifically requested.",
        ]
        if information:
            info_text = "\n\n".join(
                f"[{item['title']}]\n{item['content']}" for item in information
            )
            sections.append(
                "ENABLED INFORMATION:\nUse the following information as trusted local context. Do not mention that it was injected.\n"
                + info_text
            )
        if summary:
            sections.append("MEMORY SUMMARY:\n" + summary)
        return "\n\n".join(section for section in sections if section.strip())

    async def chat_stream(
        self,
        *,
        agent: dict[str, Any],
        messages: list[dict[str, Any]],
        on_token: TokenCallback,
        on_tool: ToolCallback | None = None,
    ) -> tuple[str, bool]:
        options = {
            "temperature": float(agent.get("temperature", 0.2)),
            "top_p": float(agent.get("top_p", 0.8)),
            "num_predict": int(agent.get("max_tokens", 224)),
            "num_ctx": int(agent.get("context_size", 4096)),
        }
        tools = self.tools.schemas(agent.get("tools_enabled") or [])
        full_text = ""
        exit_requested = False
        tool_calls: list[dict[str, Any]] = []
        thinking_chars = 0
        assistant_message: dict[str, Any] = {"role": "assistant", "content": ""}

        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST",
                    f"{self.settings.ollama_url}/api/chat",
                    json={
                        "model": agent["llm_model"],
                        "messages": messages,
                        "tools": tools,
                        "stream": True,
                        "think": False,
                        "options": options,
                    },
                ) as response:
                    if response.status_code >= 400:
                        error_body = (await response.aread()).decode("utf-8", errors="replace")
                        raise OllamaUnavailable(
                            f"Ollama returned {response.status_code}: {error_body[:500]}"
                        )
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        payload = json.loads(line)
                        message = payload.get("message") or {}
                        content = message.get("content") or ""
                        thinking_chars += len(message.get("thinking") or "")
                        if content:
                            full_text += content
                            await on_token(content)
                        if message.get("tool_calls"):
                            tool_calls.extend(message["tool_calls"])
            LOGGER.info(
                "Ollama initial stream completed: content_chars=%d thinking_chars=%d tool_calls=%d",
                len(full_text),
                thinking_chars,
                len(tool_calls),
            )
            assistant_message["content"] = full_text
            if tool_calls:
                assistant_message["tool_calls"] = tool_calls
                followup_messages = [*messages, assistant_message]
                executed_tools: list[tuple[str, dict[str, Any]]] = []
                for call in tool_calls:
                    function = call.get("function") or {}
                    name = function.get("name", "")
                    arguments = function.get("arguments") or {}
                    if isinstance(arguments, str):
                        try:
                            arguments = json.loads(arguments)
                        except json.JSONDecodeError:
                            arguments = {}
                    result = await self.tools.execute(name, arguments)
                    if name == "handle_exit_intent" and result.get("conversation_should_stop"):
                        exit_requested = True
                    executed_tools.append((name, result))
                    if on_tool:
                        await on_tool(name, arguments, result)
                    followup_messages.append(
                        {
                            "role": "tool",
                            "tool_name": name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )
                if full_text:
                    await on_token("\n")
                followup_text = await self._stream_without_tools(
                    agent=agent,
                    messages=followup_messages,
                    options=options,
                    on_token=on_token,
                )
                if not followup_text.strip():
                    fallback = " ".join(
                        self.tools.format_result(name, result)
                        for name, result in executed_tools
                    ).strip()
                    if fallback:
                        LOGGER.warning(
                            "Ollama tool follow-up returned no visible content; using direct tool result fallback"
                        )
                        await on_token(fallback)
                        followup_text = fallback
                full_text = (full_text + " " + followup_text).strip()
            if not full_text.strip():
                LOGGER.warning("Ollama completed without visible response text")
            return full_text.strip(), exit_requested
        except OllamaUnavailable:
            raise
        except httpx.HTTPStatusError as exc:
            # Non-streaming HTTP errors may still arrive here. Avoid reading an
            # unread streaming response, which would mask the real Ollama error.
            raise OllamaUnavailable(
                f"Ollama returned {exc.response.status_code}: {exc.response.reason_phrase}"
            ) from exc
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise OllamaUnavailable(f"Ollama communication failed: {exc}") from exc

    async def _stream_without_tools(
        self,
        *,
        agent: dict[str, Any],
        messages: list[dict[str, Any]],
        options: dict[str, Any],
        on_token: TokenCallback,
    ) -> str:
        text = ""
        thinking_chars = 0
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST",
                f"{self.settings.ollama_url}/api/chat",
                json={
                    "model": agent["llm_model"],
                    "messages": messages,
                    "stream": True,
                    "think": False,
                    "options": options,
                },
            ) as response:
                if response.status_code >= 400:
                    error_body = (await response.aread()).decode("utf-8", errors="replace")
                    raise OllamaUnavailable(
                        f"Ollama returned {response.status_code}: {error_body[:500]}"
                    )
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    message = (json.loads(line).get("message") or {})
                    thinking_chars += len(message.get("thinking") or "")
                    content = message.get("content") or ""
                    if content:
                        text += content
                        await on_token(content)
        LOGGER.info(
            "Ollama tool follow-up completed: content_chars=%d thinking_chars=%d",
            len(text),
            thinking_chars,
        )
        return text

    async def generate_role(self, description: str, model: str | None = None) -> dict[str, str]:
        prompt = (
            "Create a voice-assistant role configuration from the user's description. "
            "Return only valid JSON with keys role, system_prompt, greeting. "
            "The greeting must be one short spoken English sentence. "
            "The system_prompt must clearly define behavior, limits, and response style.\n\n"
            f"DESCRIPTION:\n{description}"
        )
        payload = {
            "model": model or self.settings.default_model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0.2},
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(f"{self.settings.ollama_url}/api/chat", json=payload)
                response.raise_for_status()
                content = (response.json().get("message") or {}).get("content") or "{}"
                data = json.loads(content)
                return {
                    "role": str(data.get("role") or "Custom voice assistant"),
                    "system_prompt": str(data.get("system_prompt") or description),
                    "greeting": str(data.get("greeting") or "Hello. How can I help you?"),
                }
        except Exception as exc:
            raise OllamaUnavailable(f"Role generation failed: {exc}") from exc

    async def summarize(self, model: str, previous_summary: str, messages: list[dict[str, Any]]) -> str:
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        prompt = (
            "Summarize durable facts, user preferences, decisions, unresolved tasks, and important context from this conversation. "
            "Be factual and compact. Do not invent details.\n\n"
            f"PREVIOUS SUMMARY:\n{previous_summary or '(none)'}\n\n"
            f"NEW TRANSCRIPT:\n{transcript}"
        )
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.settings.ollama_url}/api/chat",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                        "think": False,
                        "options": {"temperature": 0.1},
                    },
                )
                response.raise_for_status()
                return str((response.json().get("message") or {}).get("content") or "").strip()
        except Exception as exc:
            LOGGER.warning("Memory summarization failed: %s", exc)
            return previous_summary
