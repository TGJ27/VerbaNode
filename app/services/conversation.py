from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from typing import Any

import numpy as np

from app.config import Settings
from app.db import Database
from app.services.audio import AudioUnavailable, HostAudioRecorder
from app.services.events import EventHub
from app.services.llm import OllamaService, OllamaUnavailable
from app.services.pipeline import PipelineMonitor, TurnContext
from app.services.script_queue import ScriptQueueManager
from app.services.sentence_tts import StreamingTtsSession, empty_audio
from app.services.stt import FunASRService, SttUnavailable, TranscriptionResult
from app.services.tts import TtsService, TtsUnavailable

LOGGER = logging.getLogger(__name__)


class ConversationManager:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        events: EventHub,
        recorder: HostAudioRecorder,
        stt: FunASRService,
        llm: OllamaService,
        tts: TtsService,
        monitor: PipelineMonitor | None = None,
    ):
        self.settings = settings
        self.db = db
        self.events = events
        self.recorder = recorder
        self.stt = stt
        self.llm = llm
        self.tts = tts
        self.monitor = monitor or PipelineMonitor()
        self.script_queue: ScriptQueueManager | None = None
        self._conversation_task: asyncio.Task | None = None
        self._stop_event = threading.Event()
        self._generation_lock = asyncio.Lock()
        self._ptt_active = False
        self._browser_ptt_active = False
        self._browser_ptt_timeout_task: asyncio.Task | None = None
        self._mode = "idle"
        self._active_tts_stream: StreamingTtsSession | None = None
        self._barge_capture_cancel: threading.Event | None = None

    async def _set_pipeline(self, stage: str, **payload: Any) -> None:
        monitor = getattr(self, "monitor", None)
        if monitor is None:
            monitor = PipelineMonitor()
            self.monitor = monitor
        snapshot = monitor.transition(stage, **payload)
        await self.events.broadcast("pipeline_state", snapshot)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def is_conversation_running(self) -> bool:
        task = getattr(self, "_conversation_task", None)
        return bool(task and not task.done())

    def active_agent(self) -> dict[str, Any]:
        agent_id = int(self.db.get_setting("active_agent_id", "1") or 1)
        agent = self.db.get_agent(agent_id)
        if not agent:
            agents = self.db.list_agents()
            if not agents:
                raise RuntimeError("No agents configured")
            agent = agents[0]
            self.db.set_setting("active_agent_id", str(agent["id"]))
        return agent

    def active_conversation(self, agent_id: int | None = None) -> dict[str, Any]:
        agent_id = agent_id or int(self.active_agent()["id"])
        return self.db.latest_conversation(agent_id)

    async def switch_agent(self, agent_id: int) -> dict[str, Any]:
        agent = self.db.get_agent(agent_id)
        if not agent:
            raise ValueError("Agent not found")
        await self.stop_conversation(stop_tts=True)
        if getattr(self, "_browser_ptt_active", False):
            await self.cancel_browser_ptt()
        if self.script_queue:
            await self.script_queue.stop()
        self.db.set_setting("active_agent_id", str(agent_id))
        conversation = self.db.latest_conversation(agent_id)
        await self.events.broadcast(
            "agent_changed",
            {"agent": agent, "conversation": conversation},
        )
        return {"agent": agent, "conversation": conversation}

    async def new_chat(self, title: str | None = None) -> dict[str, Any]:
        agent = self.active_agent()
        conversation = self.db.create_conversation(int(agent["id"]), title)
        await self.events.broadcast("conversation_changed", conversation)
        return conversation

    async def start_conversation(self) -> None:
        if self.is_conversation_running:
            return
        await asyncio.to_thread(self.recorder.cancel_capture, True, 2.0)
        if getattr(self, "_browser_ptt_active", False):
            await self.cancel_browser_ptt()
        if self._ptt_active:
            await self.cancel_ptt()
        if self.script_queue:
            await self.script_queue.interrupt_for_conversation()

        # Lock output first, then input. The output callback continuously emits
        # silence while idle, so Windows keeps the selected output endpoint alive
        # when the microphone stream is activated. Both streams remain open
        # for the complete conversation instead of being recreated every turn.
        runtime = self.db.get_runtime_settings()
        self.tts.player.set_output_device(runtime.get("output_device"))
        try:
            await asyncio.to_thread(
                self.tts.player.lock_output, runtime.get("output_device")
            )
            await asyncio.to_thread(
                self.recorder.lock_input, runtime.get("input_device")
            )
        except AudioUnavailable as exc:
            await self.events.broadcast("error", {"message": str(exc), "source": "audio"})
            raise

        self._stop_event.clear()
        self._mode = "conversation"
        await self._set_pipeline("listening", mode=self._mode)
        self._conversation_task = asyncio.create_task(self._conversation_loop(), name="conversation-mode")
        await self.events.broadcast(
            "audio_lock_changed",
            {"input_locked": True, "output_locked": True},
        )
        await self.events.broadcast("mode_changed", {"mode": self._mode})

    async def stop_conversation(self, stop_tts: bool = True) -> None:
        self._stop_event.set()
        task = self._conversation_task
        self._conversation_task = None
        if stop_tts:
            await self.stop_current_tts()
        # asyncio task cancellation alone does not stop a function already
        # running inside asyncio.to_thread(). Explicitly close and wait for the
        # microphone before scripts or TTS are allowed to start.
        await asyncio.to_thread(self.recorder.cancel_capture, True, 2.0)
        self.recorder.cancel_ptt()
        await asyncio.to_thread(self.recorder.unlock_input)
        self._ptt_active = False
        await self.events.broadcast(
            "audio_lock_changed",
            {
                "input_locked": False,
                "output_locked": self.tts.player.output_locked,
            },
        )
        if task and task is not asyncio.current_task():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass
        self._mode = "idle"
        await self._set_pipeline("idle", mode=self._mode)
        await self.events.broadcast("mode_changed", {"mode": self._mode})

    async def start_ptt(self) -> None:
        if self._ptt_active:
            return
        if self.is_conversation_running:
            await self.stop_conversation(stop_tts=True)
        if getattr(self, "_browser_ptt_active", False):
            await self.cancel_browser_ptt()
        if self.script_queue:
            await self.script_queue.interrupt_for_conversation()
        await self.stop_current_tts()
        runtime = self.db.get_runtime_settings()
        self.tts.player.set_output_device(runtime.get("output_device"))
        await asyncio.to_thread(self.tts.player.lock_output, runtime.get("output_device"))
        self.recorder.start_ptt(runtime.get("input_device"))
        self._ptt_active = True
        self._mode = "ptt"
        await self._set_pipeline("recording", mode=self._mode, source="host_ptt")
        await self.events.broadcast("mode_changed", {"mode": self._mode, "recording": True})

    async def stop_ptt(self) -> None:
        if not self._ptt_active:
            return
        self._ptt_active = False
        samples = await asyncio.to_thread(self.recorder.stop_ptt)
        self._mode = "conversation" if self.is_conversation_running else "idle"
        await self.events.broadcast("mode_changed", {"mode": self._mode, "recording": False})
        await asyncio.to_thread(self.recorder.unlock_input)
        if samples.size:
            await self._handle_audio(samples, source="ptt", allow_barge_in=False)

    async def cancel_ptt(self) -> None:
        self._ptt_active = False
        self.recorder.cancel_ptt()
        if not self.is_conversation_running:
            await asyncio.to_thread(self.recorder.unlock_input)
        self._mode = "conversation" if self.is_conversation_running else "idle"
        await self.events.broadcast("mode_changed", {"mode": self._mode, "recording": False})


    async def start_browser_ptt(self) -> None:
        """Prepare a PTT capture performed by the browser device microphone."""
        if getattr(self, "_browser_ptt_active", False):
            return
        if self.is_conversation_running:
            await self.stop_conversation(stop_tts=True)
        if self._ptt_active:
            await self.cancel_ptt()
        if self.script_queue:
            await self.script_queue.interrupt_for_conversation()
        await self.stop_current_tts()
        runtime = self.db.get_runtime_settings()
        self.tts.player.set_output_device(runtime.get("output_device"))
        try:
            await asyncio.to_thread(self.tts.player.lock_output, runtime.get("output_device"))
        except AudioUnavailable as exc:
            await self.events.broadcast("error", {"message": str(exc), "source": "audio"})
            raise
        self._browser_ptt_active = True
        self._mode = "browser_ptt"
        timeout_task = getattr(self, "_browser_ptt_timeout_task", None)
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()
        self._browser_ptt_timeout_task = asyncio.create_task(
            self._browser_ptt_timeout(), name="browser-ptt-timeout"
        )
        await self.events.broadcast(
            "mode_changed",
            {"mode": self._mode, "recording": True, "input_source": "browser"},
        )

    async def _browser_ptt_timeout(self) -> None:
        try:
            await asyncio.sleep(60.0)
            if getattr(self, "_browser_ptt_active", False):
                self._browser_ptt_active = False
                self._mode = "idle"
                await self.events.broadcast(
                    "mode_changed",
                    {"mode": self._mode, "recording": False, "input_source": "browser", "reason": "timeout"},
                )
        except asyncio.CancelledError:
            return

    async def submit_browser_ptt(self, samples: np.ndarray) -> dict[str, Any]:
        timeout_task = getattr(self, "_browser_ptt_timeout_task", None)
        self._browser_ptt_timeout_task = None
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()
        self._browser_ptt_active = False
        await self.events.broadcast(
            "mode_changed",
            {"mode": "processing", "recording": False, "input_source": "browser"},
        )
        try:
            if samples.size == 0:
                return {"ok": False, "empty": True}
            result = await self._handle_audio(
                samples.astype(np.float32, copy=False),
                source="browser_ptt",
                allow_barge_in=False,
            )
            result.pop("interrupted_audio", None)
            return {"ok": True, **result}
        finally:
            self._mode = "idle"
            await self.events.broadcast(
                "mode_changed",
                {"mode": self._mode, "recording": False, "input_source": "browser"},
            )

    async def cancel_browser_ptt(self) -> None:
        timeout_task = getattr(self, "_browser_ptt_timeout_task", None)
        self._browser_ptt_timeout_task = None
        if timeout_task and not timeout_task.done():
            timeout_task.cancel()
        was_active = getattr(self, "_browser_ptt_active", False)
        self._browser_ptt_active = False
        if self._mode == "browser_ptt":
            self._mode = "idle"
        if was_active:
            await self.events.broadcast(
                "mode_changed",
                {"mode": self._mode, "recording": False, "input_source": "browser"},
            )

    async def send_text(self, text: str, conversation_id: int | None = None) -> dict[str, Any]:
        if self.is_conversation_running:
            await self.stop_conversation(stop_tts=True)
        if self._ptt_active:
            await self.cancel_ptt()
        if getattr(self, "_browser_ptt_active", False):
            await self.cancel_browser_ptt()
        if self.script_queue:
            await self.script_queue.interrupt_for_conversation()
        await self.stop_current_tts()
        result = await self.process_user_text(
            text=text,
            conversation_id=conversation_id,
            source="text",
            speak=True,
            allow_barge_in=False,
        )
        # interrupted_audio is an internal NumPy buffer used only by continuous
        # conversation mode. It is not JSON serializable and is never needed by
        # the typed-chat HTTP client.
        result.pop("interrupted_audio", None)
        return result

    async def process_user_text(
        self,
        *,
        text: str,
        conversation_id: int | None,
        source: str,
        speak: bool,
        allow_barge_in: bool,
        stt_confidence: float | None = None,
        stt_confidence_source: str | None = None,
        turn_context: TurnContext | None = None,
    ) -> dict[str, Any]:
        async with self._generation_lock:
            turn_context = turn_context or self.monitor.begin_turn(source, audio=False)
            agent = self.active_agent()
            if conversation_id is None:
                conversation_id = int(self.active_conversation(int(agent["id"]))["id"])
            conversation = self.db.get_conversation(conversation_id)
            if not conversation or int(conversation["agent_id"]) != int(agent["id"]):
                conversation = self.active_conversation(int(agent["id"]))
                conversation_id = int(conversation["id"])

            user_message = self.db.add_message(
                conversation_id,
                "user",
                text,
                source,
                stt_confidence=stt_confidence,
                stt_confidence_source=stt_confidence_source,
            )
            await self.events.broadcast("message_added", user_message)
            generation_id = turn_context.generation_id
            await self.events.broadcast(
                "assistant_start",
                {"generation_id": generation_id, "turn_id": turn_context.turn_id, "capture_id": turn_context.capture_id, "conversation_id": conversation_id},
            )

            information = self.db.enabled_information_for_agent(int(agent["id"]))
            summary_row = self.db.get_summary(int(agent["id"]), conversation_id)
            summary = summary_row["content"] if summary_row else None
            history = self.db.list_messages(conversation_id, limit=40)
            system_prompt = self.llm.build_system_prompt(agent, information, summary)
            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(
                {"role": row["role"], "content": row["content"]}
                for row in history
                if row["role"] in {"user", "assistant"}
            )

            speech_stream: StreamingTtsSession | None = None
            if speak:
                speech_stream = StreamingTtsSession(
                    tts=self.tts,
                    events=self.events,
                    agent=agent,
                    turn_id=turn_context.turn_id,
                    generation_id=generation_id,
                )
                self._active_tts_stream = speech_stream

            token_parts: list[str] = []

            async def token_callback(token: str) -> None:
                token_parts.append(token)
                await self.events.broadcast(
                    "assistant_token",
                    {"generation_id": generation_id, "token": token},
                )
                if speech_stream:
                    await speech_stream.feed(token)

            async def tool_callback(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> None:
                await self.events.broadcast(
                    "tool_event",
                    {"name": name, "arguments": arguments, "result": result},
                )

            runtime = self.db.get_runtime_settings()
            interruption_enabled = bool(runtime.get("interruption_enabled", False)) and allow_barge_in
            interrupted_audio = empty_audio()
            barge_started = asyncio.Event()
            monitor_task: asyncio.Task | None = None
            barge_wait_task: asyncio.Task | None = None
            llm_task: asyncio.Task | None = None

            async def monitor_barge_in() -> np.ndarray:
                assert speech_stream is not None
                await speech_stream.started.wait()
                if speech_stream.cancelled.is_set() or speech_stream.finished.is_set():
                    return empty_audio()
                await asyncio.sleep(self.settings.barge_in_start_delay_ms / 1000.0)
                if speech_stream.cancelled.is_set() or speech_stream.finished.is_set():
                    return empty_audio()
                cancel_capture = threading.Event()
                self._barge_capture_cancel = cancel_capture
                loop = asyncio.get_running_loop()

                def on_speech_start() -> None:
                    speech_stream.cancel_nowait()
                    loop.call_soon_threadsafe(barge_started.set)

                try:
                    return await asyncio.to_thread(
                        self.recorder.capture_until_silence,
                        silence_ms=int(runtime.get("silence_ms", self.settings.silence_ms)),
                        max_seconds=int(runtime.get("max_record_seconds", self.settings.max_record_seconds)),
                        input_device=runtime.get("input_device"),
                        cancel_event=cancel_capture,
                        on_speech_start=on_speech_start,
                    )
                finally:
                    if self._barge_capture_cancel is cancel_capture:
                        self._barge_capture_cancel = None

            direct_intent = self.llm.tools.match_core_intent(
                text, agent.get("tools_enabled") or []
            )
            used_direct_tool = direct_intent is not None
            assistant_source = "tool" if used_direct_tool else "llm"

            try:
                if direct_intent:
                    tool_name, tool_arguments = direct_intent
                    self.monitor.mark("tool_started")
                    await self._set_pipeline(
                        "tooling",
                        turn_id=turn_context.turn_id,
                        generation_id=generation_id,
                        tool=tool_name,
                        deterministic=True,
                    )
                    LOGGER.info(
                        "Deterministic core tool route: intent=%s text=%r",
                        tool_name,
                        text,
                    )
                    try:
                        tool_result = await asyncio.wait_for(
                            self.llm.tools.execute(tool_name, tool_arguments),
                            timeout=float(self.settings.tool_timeout_seconds),
                        )
                    except asyncio.TimeoutError:
                        tool_result = {
                            "error": f"Tool '{tool_name}' timed out after "
                            f"{self.settings.tool_timeout_seconds:g} seconds"
                        }
                        self.monitor.increment("tool_timeouts")
                    except Exception as exc:
                        tool_result = {"error": f"Tool '{tool_name}' failed: {exc}"}
                    await tool_callback(tool_name, tool_arguments, tool_result)
                    reply = self.llm.tools.format_result(tool_name, tool_result).strip()
                    await token_callback(reply)
                    exit_requested = bool(
                        tool_name == "handle_exit_intent"
                        and tool_result.get("conversation_should_stop")
                    )
                else:
                    self.monitor.mark("llm_started")
                    await self._set_pipeline("thinking", turn_id=turn_context.turn_id, generation_id=generation_id)
                    llm_task = asyncio.create_task(
                        self.llm.chat_stream(
                            agent=agent,
                            messages=messages,
                            on_token=token_callback,
                            on_tool=tool_callback,
                        ),
                        name=f"llm-{generation_id}",
                    )
                    if speech_stream and interruption_enabled:
                        monitor_task = asyncio.create_task(monitor_barge_in(), name=f"barge-{generation_id}")
                        barge_wait_task = asyncio.create_task(barge_started.wait())
                        done, _ = await asyncio.wait(
                            {llm_task, barge_wait_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if barge_wait_task in done and barge_started.is_set() and not llm_task.done():
                            llm_task.cancel()
                            try:
                                await llm_task
                            except asyncio.CancelledError:
                                pass
                            reply = "".join(token_parts).strip()
                            exit_requested = False
                        else:
                            reply, exit_requested = await llm_task
                    else:
                        reply, exit_requested = await llm_task
            except OllamaUnavailable as exc:
                reply = f"I could not reach the local Ollama model. {exc}"
                exit_requested = False
                await token_callback(reply)
                await self.events.broadcast("error", {"message": str(exc), "source": "ollama"})
            finally:
                if barge_wait_task and not barge_wait_task.done():
                    barge_wait_task.cancel()

            if used_direct_tool:
                self.monitor.mark("tool_completed")
                self.monitor.duration("tool_total", "tool_started", "tool_completed")
            else:
                self.monitor.mark("llm_completed")
                self.monitor.duration("llm_total", "llm_started", "llm_completed")
            assistant_message = self.db.add_message(
                conversation_id,
                "assistant",
                reply,
                assistant_source,
            )
            await self.events.broadcast(
                "assistant_complete",
                {
                    "generation_id": generation_id,
                    "turn_id": turn_context.turn_id,
                    "capture_id": turn_context.capture_id,
                    "message": assistant_message,
                },
            )

            if speech_stream:
                await self._set_pipeline("speaking", turn_id=turn_context.turn_id, generation_id=generation_id)
                self.monitor.mark("tts_started")
                await speech_stream.close_input()
                finish_task = asyncio.create_task(speech_stream.wait_finished())
                if monitor_task:
                    if barge_started.is_set():
                        interrupted_audio = await monitor_task
                        await finish_task
                    else:
                        barge_wait_task = asyncio.create_task(barge_started.wait())
                        done, _ = await asyncio.wait(
                            {finish_task, barge_wait_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if barge_wait_task in done and barge_started.is_set():
                            interrupted_audio = await monitor_task
                            await finish_task
                        else:
                            if self._barge_capture_cancel:
                                self._barge_capture_cancel.set()
                            await finish_task
                            interrupted_audio = await monitor_task
                        if not barge_wait_task.done():
                            barge_wait_task.cancel()
                else:
                    await finish_task

                guard_seconds = self.settings.post_tts_mic_guard_ms / 1000.0
                if (
                    guard_seconds > 0
                    and interrupted_audio.size == 0
                    and not self._stop_event.is_set()
                    and not speech_stream.cancelled.is_set()
                ):
                    await asyncio.sleep(guard_seconds)
                if self._active_tts_stream is speech_stream:
                    self._active_tts_stream = None
                self.monitor.mark("tts_completed")
                self.monitor.duration("tts_total", "tts_started", "tts_completed")
            asyncio.create_task(
                self._maybe_summarize(int(agent["id"]), conversation_id, agent["llm_model"]),
                name=f"summarize-{conversation_id}",
            )
            if exit_requested:
                self._stop_event.set()
            self.monitor.finish_turn(cancelled=False)
            await self._set_pipeline("listening" if self.is_conversation_running else "idle")
            return {
                "message": assistant_message,
                "exit_requested": exit_requested,
                "interrupted_audio": interrupted_audio,
            }

    async def stop_current_tts(self) -> None:
        stream = getattr(self, "_active_tts_stream", None)
        if stream:
            await stream.cancel()
            if self._active_tts_stream is stream:
                self._active_tts_stream = None
        capture_cancel = getattr(self, "_barge_capture_cancel", None)
        if capture_cancel:
            capture_cancel.set()
        # Also invalidates non-streamed script/greeting playback and sends
        # a synchronous stop command to the isolated Audio Engine.
        self.tts.stop_current()

    async def _speak_reply(
        self,
        text: str,
        agent: dict[str, Any],
        *,
        allow_barge_in: bool,
        use_cache: bool = False,
        cache_namespace: str = "assistant",
        source: str = "assistant",
    ) -> np.ndarray:
        speech_id = self.tts.begin_speech()
        await self.events.broadcast("tts_started", {"source": source, "text": text})
        runtime = self.db.get_runtime_settings()
        interruption_enabled = bool(runtime.get("interruption_enabled", False)) and allow_barge_in
        try:
            if not interruption_enabled:
                await asyncio.to_thread(
                    self.tts.speak_blocking,
                    text,
                    agent,
                    speech_id,
                    use_cache=use_cache,
                    cache_namespace=cache_namespace,
                )
                # Keep the host microphone closed briefly after playback so room
                # echo and the speaker tail cannot become the next user turn.
                guard_seconds = self.settings.post_tts_mic_guard_ms / 1000.0
                if guard_seconds > 0 and not self._stop_event.is_set():
                    await asyncio.sleep(guard_seconds)
                return np.empty(0, dtype=np.float32)

            cancel_capture = threading.Event()
            speech_started = threading.Event()

            def on_speech_start() -> None:
                speech_started.set()
                self.tts.stop_current()

            tts_task = asyncio.create_task(
                asyncio.to_thread(
                    self.tts.speak_blocking,
                    text,
                    agent,
                    speech_id,
                    use_cache=use_cache,
                    cache_namespace=cache_namespace,
                )
            )
            # Full-duplex barge-in is experimental because this project does not
            # include acoustic echo cancellation. Delay microphone monitoring so
            # the beginning of playback cannot instantly trigger the VAD.
            await asyncio.sleep(self.settings.barge_in_start_delay_ms / 1000.0)
            capture_task = asyncio.create_task(
                asyncio.to_thread(
                    self.recorder.capture_until_silence,
                    silence_ms=int(runtime.get("silence_ms", self.settings.silence_ms)),
                    max_seconds=int(runtime.get("max_record_seconds", self.settings.max_record_seconds)),
                    input_device=runtime.get("input_device"),
                    cancel_event=cancel_capture,
                    on_speech_start=on_speech_start,
                )
            )
            done, _ = await asyncio.wait(
                {tts_task, capture_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if tts_task in done and not speech_started.is_set():
                cancel_capture.set()
                samples = await capture_task
                return samples if speech_started.is_set() else np.empty(0, dtype=np.float32)
            samples = await capture_task
            self.tts.stop_current()
            try:
                await tts_task
            except Exception:
                pass
            return samples
        except (TtsUnavailable, AudioUnavailable) as exc:
            await self.events.broadcast("error", {"message": str(exc), "source": "tts"})
            return np.empty(0, dtype=np.float32)
        finally:
            await self.events.broadcast("tts_stopped", {"source": source})

    async def _conversation_loop(self) -> None:
        agent = self.active_agent()
        try:
            greeting_audio = await self._speak_reply(
                str(agent.get("greeting") or "Hello."),
                agent,
                allow_barge_in=True,
                use_cache=True,
                cache_namespace="greeting",
                source="greeting",
            )
            pending_audio = greeting_audio
            while not self._stop_event.is_set():
                if pending_audio.size == 0:
                    runtime = self.db.get_runtime_settings()
                    self._mode = "conversation"
                    await self.events.broadcast("listening", {"active": True})
                    try:
                        pending_audio = await asyncio.to_thread(
                            self.recorder.capture_until_silence,
                            silence_ms=int(runtime.get("silence_ms", self.settings.silence_ms)),
                            max_seconds=int(runtime.get("max_record_seconds", self.settings.max_record_seconds)),
                            input_device=runtime.get("input_device"),
                            cancel_event=self._stop_event,
                        )
                    except AudioUnavailable as exc:
                        await self.events.broadcast("error", {"message": str(exc), "source": "audio"})
                        break
                    finally:
                        await self.events.broadcast("listening", {"active": False})
                if self._stop_event.is_set():
                    break
                if pending_audio.size == 0:
                    continue
                result = await self._handle_audio(
                    pending_audio,
                    source="conversation",
                    allow_barge_in=True,
                )
                pending_audio = result.get("interrupted_audio", np.empty(0, dtype=np.float32))
                if result.get("exit_requested"):
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.exception("Conversation loop failed")
            await self.events.broadcast("error", {"message": str(exc), "source": "conversation"})
        finally:
            await asyncio.to_thread(self.recorder.cancel_capture, True, 2.0)
            await asyncio.to_thread(self.recorder.unlock_input)
            await self.events.broadcast(
                "audio_lock_changed",
                {
                    "input_locked": False,
                    "output_locked": self.tts.player.output_locked,
                },
            )
            self._mode = "idle"
            self._conversation_task = None
            self._stop_event.set()
            await self.events.broadcast("mode_changed", {"mode": self._mode})

    async def _handle_audio(
        self,
        samples: np.ndarray,
        *,
        source: str,
        allow_barge_in: bool,
    ) -> dict[str, Any]:
        agent = self.active_agent()
        if not hasattr(self, "monitor") or self.monitor is None:
            self.monitor = PipelineMonitor()
        turn_context = self.monitor.begin_turn(source, audio=True)
        await self._set_pipeline("transcribing", turn_id=turn_context.turn_id, capture_id=turn_context.capture_id)
        self.monitor.mark("stt_started")
        await self.events.broadcast("stt_started", {"source": source, "turn_id": turn_context.turn_id, "capture_id": turn_context.capture_id})
        try:
            if hasattr(self.stt, "transcribe_with_confidence"):
                transcription = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.stt.transcribe_with_confidence,
                        samples.copy(),
                        str(agent.get("stt_model") or self.settings.funasr_model),
                    ),
                    timeout=float(getattr(self.settings, "stt_timeout_seconds", 30.0)),
                )
            else:
                text_only = await asyncio.wait_for(
                    asyncio.to_thread(
                        self.stt.transcribe,
                        samples.copy(),
                        str(agent.get("stt_model") or self.settings.funasr_model),
                    ),
                    timeout=float(getattr(self.settings, "stt_timeout_seconds", 30.0)),
                )
                transcription = TranscriptionResult(str(text_only), 1.0, "unavailable")
        except asyncio.TimeoutError:
            self.monitor.increment("stt_timeouts")
            self.monitor.error("stt", "Speech recognition timed out")
            await self.events.broadcast("error", {"message": "Speech recognition timed out.", "source": "stt"})
            self.monitor.finish_turn(cancelled=True)
            return {"interrupted_audio": np.empty(0, dtype=np.float32)}
        except SttUnavailable as exc:
            self.monitor.error("stt", str(exc))
            await self.events.broadcast("error", {"message": str(exc), "source": "stt"})
            self.monitor.finish_turn(cancelled=True)
            return {"interrupted_audio": np.empty(0, dtype=np.float32)}
        finally:
            self.monitor.mark("stt_completed")
            self.monitor.duration("stt_total", "stt_started", "stt_completed")
            await self.events.broadcast("stt_stopped", {"source": source, "turn_id": turn_context.turn_id, "capture_id": turn_context.capture_id})

        text = transcription.text.strip()
        if not text:
            self.monitor.finish_turn(cancelled=True)
            await self._set_pipeline("listening" if self.is_conversation_running else "idle")
            return {"interrupted_audio": np.empty(0, dtype=np.float32)}

        runtime = self.db.get_runtime_settings()
        confidence = max(0.0, min(1.0, float(transcription.confidence)))
        threshold = max(0.0, min(1.0, float(runtime.get("stt_confidence_threshold", 0.70))))
        filtering_enabled = bool(runtime.get("stt_confidence_filter_enabled", True))
        accepted = not filtering_enabled or confidence >= threshold
        transcript_event = {
            "text": text,
            "source": source,
            "confidence": confidence,
            "confidence_percent": int(round(confidence * 100)),
            "confidence_source": transcription.confidence_source,
            "accepted": accepted,
            "threshold": threshold,
            "threshold_percent": int(round(threshold * 100)),
            "turn_id": turn_context.turn_id,
            "capture_id": turn_context.capture_id,
        }
        await self.events.broadcast("transcript", transcript_event)

        if not accepted:
            LOGGER.info(
                "STT transcript rejected at %d%% below threshold %d%%: %r",
                transcript_event["confidence_percent"],
                transcript_event["threshold_percent"],
                text[:160],
            )
            # Deliberately do not speak an apology and do not add the rejected
            # transcript to LLM history. The browser shows it as a local notice.
            self.monitor.finish_turn(cancelled=True)
            await self._set_pipeline("listening" if self.is_conversation_running else "idle")
            return {
                "interrupted_audio": np.empty(0, dtype=np.float32),
                "rejected": True,
                "transcript": transcript_event,
            }

        return await self.process_user_text(
            text=text,
            conversation_id=None,
            source=source,
            speak=True,
            allow_barge_in=allow_barge_in,
            stt_confidence=confidence,
            stt_confidence_source=transcription.confidence_source,
            turn_context=turn_context,
        )

    async def _maybe_summarize(self, agent_id: int, conversation_id: int, model: str) -> None:
        count = self.db.message_count(conversation_id)
        if count < self.settings.summary_trigger_messages:
            return
        messages = self.db.list_messages(conversation_id, limit=1000)
        summary_row = self.db.get_summary(agent_id, conversation_id)
        through = int(summary_row["through_message_id"]) if summary_row else 0
        candidates = [m for m in messages if int(m["id"]) > through]
        if len(candidates) <= self.settings.summary_keep_recent:
            return
        to_summarize = candidates[: -self.settings.summary_keep_recent]
        previous = str(summary_row["content"]) if summary_row else ""
        summary = await self.llm.summarize(model, previous, to_summarize)
        if summary:
            self.db.upsert_summary(
                agent_id,
                conversation_id,
                summary,
                int(to_summarize[-1]["id"]),
            )
            await self.events.broadcast(
                "memory_updated",
                {"agent_id": agent_id, "conversation_id": conversation_id},
            )
