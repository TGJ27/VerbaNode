from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.config import Settings
from app.services.prompts import PromptComposer
from app.services.tools import ToolService

LOGGER = logging.getLogger(__name__)
TokenCallback = Callable[[str], Awaitable[None]]
ToolCallback = Callable[[str, dict[str, Any], dict[str, Any]], Awaitable[None]]


class OllamaUnavailable(RuntimeError):
    pass


class OllamaService:
    def __init__(self, settings: Settings, tools: ToolService, monitor: Any | None = None):
        self.settings = settings
        self.tools = tools
        self.monitor = monitor
        self.prompts = PromptComposer(settings)

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=float(self.settings.ollama_connect_timeout_seconds),
            read=float(self.settings.ollama_read_timeout_seconds),
            write=30.0,
            pool=float(self.settings.ollama_connect_timeout_seconds),
        )

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
        return self.prompts.compose(
            agent=agent,
            information=information,
            summary=summary,
            tool_schemas=self.tools.schemas(agent.get("tools_enabled") or []),
        )

    @staticmethod
    def _repair_tool_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Ensure interrupted assistant tool calls have matching tool results."""
        repaired: list[dict[str, Any]] = []
        pending: list[str] = []
        for message in messages:
            if pending and message.get("role") != "tool":
                for name in pending:
                    repaired.append({
                        "role": "tool",
                        "tool_name": name,
                        "content": json.dumps({"status": "cancelled", "reason": "user_interrupted"}),
                    })
                pending = []
            repaired.append(message)
            if message.get("role") == "assistant" and message.get("tool_calls"):
                pending = [
                    str((call.get("function") or {}).get("name") or "unknown_tool")
                    for call in message.get("tool_calls") or []
                ]
            elif message.get("role") == "tool" and pending:
                tool_name = str(message.get("tool_name") or "")
                if tool_name in pending:
                    pending.remove(tool_name)
        if pending:
            for name in pending:
                repaired.append({
                    "role": "tool",
                    "tool_name": name,
                    "content": json.dumps({"status": "cancelled", "reason": "user_interrupted"}),
                })
        return repaired

    async def _stream_round(
        self,
        *,
        client: httpx.AsyncClient,
        agent: dict[str, Any],
        messages: list[dict[str, Any]],
        options: dict[str, Any],
        tools: list[dict[str, Any]],
        on_token: TokenCallback,
    ) -> tuple[str, list[dict[str, Any]]]:
        text = ""
        calls: list[dict[str, Any]] = []
        thinking_chars = 0
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
                    text += content
                    await on_token(content)
                if message.get("tool_calls"):
                    calls.extend(message["tool_calls"])
        LOGGER.info(
            "Ollama stream round completed: content_chars=%d thinking_chars=%d tool_calls=%d",
            len(text), thinking_chars, len(calls),
        )
        return text, calls

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
        working_messages = self._repair_tool_history(list(messages))
        visible_parts: list[str] = []
        exit_requested = False
        last_executed: list[tuple[str, dict[str, Any]]] = []
        max_rounds = max(1, int(self.settings.max_tool_rounds))

        try:
            async with httpx.AsyncClient(timeout=self._timeout()) as client:
                for round_index in range(max_rounds + 1):
                    round_text, tool_calls = await self._stream_round(
                        client=client,
                        agent=agent,
                        messages=working_messages,
                        options=options,
                        tools=tools if round_index < max_rounds else [],
                        on_token=on_token,
                    )
                    if round_text:
                        visible_parts.append(round_text)
                    assistant_message: dict[str, Any] = {
                        "role": "assistant",
                        "content": round_text,
                    }
                    if tool_calls:
                        assistant_message["tool_calls"] = tool_calls
                    working_messages.append(assistant_message)

                    if not tool_calls:
                        break
                    if round_index >= max_rounds:
                        LOGGER.warning("Maximum tool rounds reached; refusing further tool recursion")
                        break

                    last_executed = []
                    for call in tool_calls:
                        function = call.get("function") or {}
                        name = str(function.get("name") or "")
                        arguments = function.get("arguments") or {}
                        if isinstance(arguments, str):
                            try:
                                arguments = json.loads(arguments)
                            except json.JSONDecodeError:
                                arguments = {}
                        if self.monitor:
                            self.monitor.transition("tooling", tool=name)
                        try:
                            result = await asyncio.wait_for(
                                self.tools.execute(name, arguments),
                                timeout=float(self.settings.tool_timeout_seconds),
                            )
                        except asyncio.TimeoutError:
                            result = {"error": f"Tool '{name}' timed out after {self.settings.tool_timeout_seconds:g} seconds"}
                            if self.monitor:
                                self.monitor.increment("tool_timeouts")
                        except Exception as exc:
                            result = {"error": f"Tool '{name}' failed: {exc}"}
                        if name == "handle_exit_intent" and result.get("conversation_should_stop"):
                            exit_requested = True
                        last_executed.append((name, result))
                        if on_tool:
                            await on_tool(name, arguments, result)
                        working_messages.append({
                            "role": "tool",
                            "tool_name": name,
                            "content": json.dumps(result, ensure_ascii=False),
                        })
                    if round_text:
                        await on_token("\n")

            full_text = " ".join(part.strip() for part in visible_parts if part.strip()).strip()
            if not full_text and last_executed:
                fallback = " ".join(
                    self.tools.format_result(name, result)
                    for name, result in last_executed
                ).strip()
                if fallback:
                    LOGGER.warning("Ollama tool flow returned no visible content; using direct result fallback")
                    await on_token(fallback)
                    full_text = fallback
            if not full_text:
                LOGGER.warning("Ollama completed without visible response text")
            return full_text, exit_requested
        except OllamaUnavailable:
            raise
        except httpx.HTTPStatusError as exc:
            raise OllamaUnavailable(
                f"Ollama returned {exc.response.status_code}: {exc.response.reason_phrase}"
            ) from exc
        except (httpx.TimeoutException, httpx.HTTPError, json.JSONDecodeError) as exc:
            raise OllamaUnavailable(f"Ollama communication failed: {exc}") from exc

    async def generate_role(self, description: str, model: str | None = None) -> dict[str, str]:
        prompt = (
            "Create an agent identity and character configuration from the user's description. "
            "Return only valid JSON with keys role, system_prompt, greeting. "
            "The role must be a short role summary. The system_prompt must contain only identity, "
            "domain, personality, tone, and speaking style. Do not include instructions about tools, "
            "memory, external data, safety policy, prompt hierarchy, runtime state, or application internals; "
            "VerbaNode handles those separately. The greeting must be one short natural spoken sentence "
            "appropriate to the described agent and language.\n\n"
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
