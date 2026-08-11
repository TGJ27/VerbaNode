from __future__ import annotations

import logging
import multiprocessing as mp
import os
import queue
import threading
import time
import traceback
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.config import Settings
from app.services.stt import FunASRService, SttUnavailable, TranscriptionResult
from app.services.tts import KokoroTtsProvider, TtsUnavailable

LOGGER = logging.getLogger(__name__)


class AiEngineUnavailable(RuntimeError):
    """Raised when the isolated model process cannot complete an operation."""


def _serialize_error(exc: BaseException) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(
            traceback.format_exception(type(exc), exc, exc.__traceback__)
        ),
    }


def _ai_engine_worker(
    command_queue: Any,
    result_queue: Any,
    settings_payload: dict[str, Any],
    preload_asr: bool,
    preload_kokoro: bool,
) -> None:
    """Own the active FunASR-compatible ASR model and Kokoro in one child process."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(processName)s] %(name)s - %(message)s",
    )
    settings = Settings(**settings_payload)
    stt = FunASRService(settings)
    kokoro = KokoroTtsProvider(settings)
    closing = threading.Event()
    state_lock = threading.RLock()
    asr_lock = threading.RLock()
    kokoro_lock = threading.RLock()
    operation_lock = threading.RLock()
    operation_threads: set[threading.Thread] = set()
    started_at = time.monotonic()

    state: dict[str, Any] = {
        "asr": {
            "state": "not_loaded",
            "model": settings.funasr_model,
            "installed": None,
            "loaded": False,
            "queued": 0,
            "active": False,
            "jobs_completed": 0,
            "last_latency_ms": None,
            "model_load_ms": None,
            "last_error": None,
        },
        "kokoro": {
            "state": "not_loaded",
            "installed": None,
            "loaded": False,
            "model_ready": kokoro.model_ready(),
            "queued": 0,
            "active": False,
            "jobs_completed": 0,
            "last_latency_ms": None,
            "model_load_ms": None,
            "last_error": None,
        },
    }

    def emit(payload: dict[str, Any]) -> None:
        try:
            result_queue.put(payload)
        except Exception:
            pass

    def snapshot() -> dict[str, Any]:
        with state_lock:
            asr_state = dict(state["asr"])
            kokoro_state = dict(state["kokoro"])
        return {
            "pid": os.getpid(),
            "uptime_seconds": round(time.monotonic() - started_at, 1),
            "coordinator_state": (
                "transcribing"
                if asr_state.get("active")
                else "synthesizing"
                if kokoro_state.get("active")
                else "loading"
                if asr_state.get("state") == "loading"
                or kokoro_state.get("state") == "loading"
                else "idle"
            ),
            "asr": asr_state,
            "kokoro": kokoro_state,
        }

    def set_loading(provider: str) -> float:
        with state_lock:
            state[provider]["state"] = "loading"
            state[provider]["last_error"] = None
        return time.monotonic()

    def warm_asr(force_reload: bool = False, model_name: str | None = None) -> dict[str, Any]:
        with asr_lock:
            started = set_loading("asr")
            try:
                if force_reload:
                    stt.reload_model(model_name or settings.funasr_model, load=False)
                stt.warmup(model_name or settings.funasr_model)
                elapsed = round((time.monotonic() - started) * 1000)
                status = stt.status()
                with state_lock:
                    state["asr"].update(
                        {
                            "state": "ready",
                            "installed": bool(status.get("installed")),
                            "loaded": True,
                            "model": status.get("model") or settings.funasr_model,
                            "model_load_ms": elapsed,
                            "last_error": None,
                        }
                    )
                return dict(state["asr"])
            except BaseException as exc:
                with state_lock:
                    state["asr"].update(
                        {
                            "state": "error",
                            "loaded": False,
                            "last_error": str(exc),
                        }
                    )
                raise

    def warm_kokoro(force_reload: bool = False) -> dict[str, Any]:
        with kokoro_lock:
            started = set_loading("kokoro")
            try:
                if force_reload:
                    kokoro.reload_model(load=False)
                ready = kokoro.model_ready()
                with state_lock:
                    state["kokoro"]["model_ready"] = ready
                if not ready:
                    raise TtsUnavailable(
                        "Kokoro model is missing. Run: python scripts/models/download_kokoro.py"
                    )
                status = kokoro.warmup()
                elapsed = round((time.monotonic() - started) * 1000)
                with state_lock:
                    state["kokoro"].update(
                        {
                            "state": "ready",
                            "installed": bool(status.get("installed")),
                            "loaded": True,
                            "model_ready": True,
                            "model_load_ms": elapsed,
                            "last_error": None,
                        }
                    )
                return dict(state["kokoro"])
            except BaseException as exc:
                with state_lock:
                    state["kokoro"].update(
                        {
                            "state": "missing"
                            if not kokoro.model_ready()
                            else "error",
                            "loaded": False,
                            "model_ready": kokoro.model_ready(),
                            "last_error": str(exc),
                        }
                    )
                raise

    def background_warmup() -> None:
        if preload_asr and not closing.is_set():
            try:
                warm_asr()
                LOGGER.info("Default ASR model is ready in the isolated AI Engine")
            except Exception as exc:
                LOGGER.warning("AI Engine could not preload the default ASR model: %s", exc)
        if preload_kokoro and not closing.is_set() and kokoro.model_ready():
            try:
                warm_kokoro()
                LOGGER.info("Kokoro model is ready in the isolated AI Engine")
            except Exception as exc:
                LOGGER.warning("AI Engine could not preload Kokoro: %s", exc)

    def execute(request: dict[str, Any]) -> None:
        request_id = str(request.get("id") or "")
        operation = str(request.get("operation") or "")
        args = list(request.get("args") or [])
        kwargs = dict(request.get("kwargs") or {})
        provider = "asr" if operation.startswith("asr.") else "kokoro" if operation.startswith("kokoro.") else None
        if provider:
            with state_lock:
                state[provider]["queued"] = max(0, int(state[provider]["queued"]) - 1)
                state[provider]["active"] = True
        try:
            if operation == "engine.ping":
                result: Any = {"ok": True, "pid": os.getpid(), "time": time.monotonic()}
            elif operation == "engine.status":
                result = snapshot()
            elif operation == "engine.warmup":
                requested = set(kwargs.get("providers") or ["asr", "kokoro"])
                result = {}
                if "asr" in requested:
                    result["asr"] = warm_asr()
                if "kokoro" in requested:
                    result["kokoro"] = warm_kokoro()
            elif operation == "asr.transcribe":
                audio = np.asarray(args[0], dtype=np.float32).reshape(-1).copy()
                model_name = str(args[1]) if len(args) > 1 and args[1] else settings.funasr_model
                language = str(args[2]) if len(args) > 2 and args[2] else "en"
                started = time.monotonic()
                with asr_lock:
                    if stt.status().get("model") != model_name or not stt.status().get("loaded"):
                        warm_asr(model_name=model_name)
                    transcription = stt.transcribe_with_confidence(audio, model_name, language)
                latency = round((time.monotonic() - started) * 1000)
                with state_lock:
                    state["asr"].update(
                        {
                            "state": "ready",
                            "loaded": True,
                            "model": model_name,
                            "jobs_completed": int(state["asr"]["jobs_completed"]) + 1,
                            "last_latency_ms": latency,
                            "last_error": None,
                        }
                    )
                result = {
                    "text": transcription.text,
                    "confidence": transcription.confidence,
                    "confidence_source": transcription.confidence_source,
                    "language": language,
                    "latency_ms": latency,
                }
            elif operation == "asr.reload":
                model_name = str(args[0]) if args and args[0] else settings.funasr_model
                result = warm_asr(force_reload=True, model_name=model_name)
            elif operation == "kokoro.generate":
                text = str(args[0])
                voice_id = int(args[1])
                speed = float(args[2])
                started = time.monotonic()
                with kokoro_lock:
                    if not kokoro.status().get("loaded"):
                        warm_kokoro()
                    path = kokoro.generate(text, voice_id, speed)
                latency = round((time.monotonic() - started) * 1000)
                with state_lock:
                    state["kokoro"].update(
                        {
                            "state": "ready",
                            "loaded": True,
                            "model_ready": True,
                            "jobs_completed": int(state["kokoro"]["jobs_completed"]) + 1,
                            "last_latency_ms": latency,
                            "last_error": None,
                        }
                    )
                result = {"path": str(path), "latency_ms": latency}
            elif operation == "kokoro.reload":
                result = warm_kokoro(force_reload=True)
            else:
                raise ValueError(f"Unknown AI-engine operation: {operation}")
            emit({"kind": "response", "id": request_id, "ok": True, "result": result})
        except BaseException as exc:
            if provider:
                with state_lock:
                    state[provider]["last_error"] = str(exc)
                    if state[provider].get("state") != "missing":
                        state[provider]["state"] = "error"
            emit(
                {
                    "kind": "response",
                    "id": request_id,
                    "ok": False,
                    "error": _serialize_error(exc),
                }
            )
        finally:
            if provider:
                with state_lock:
                    state[provider]["active"] = False
            current = threading.current_thread()
            with operation_lock:
                operation_threads.discard(current)

    emit({"kind": "engine", "event": "ready", "pid": os.getpid()})
    threading.Thread(
        target=background_warmup,
        name="ai-engine-warmup",
        daemon=True,
    ).start()

    try:
        while not closing.is_set():
            try:
                request = command_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if not isinstance(request, dict):
                continue
            operation = str(request.get("operation") or "")
            if operation == "engine.shutdown":
                closing.set()
                emit(
                    {
                        "kind": "response",
                        "id": str(request.get("id") or ""),
                        "ok": True,
                        "result": True,
                    }
                )
                break
            if operation in {"engine.ping", "engine.status"}:
                execute(request)
                continue
            provider = "asr" if operation.startswith("asr.") else "kokoro" if operation.startswith("kokoro.") else None
            if provider:
                with state_lock:
                    state[provider]["queued"] = int(state[provider]["queued"]) + 1
            thread = threading.Thread(
                target=execute,
                args=(request,),
                name=f"ai-op-{operation}-{str(request.get('id', ''))[:8]}",
                daemon=True,
            )
            with operation_lock:
                operation_threads.add(thread)
            thread.start()
    finally:
        closing.set()
        with operation_lock:
            threads = list(operation_threads)
        for thread in threads:
            thread.join(timeout=0.5)
        emit({"kind": "engine", "event": "stopped", "pid": os.getpid()})


@dataclass
class _PendingCall:
    request_id: str
    operation: str
    response_queue: queue.Queue[dict[str, Any]]


class AiEngineSupervisor:
    """Supervise one isolated process that owns local ASR and Kokoro models."""

    def __init__(
        self,
        settings: Settings,
        *,
        startup_timeout: float = 10.0,
        command_timeout: float = 45.0,
        watchdog_interval: float = 3.0,
        asr_queue_size: int = 2,
        kokoro_queue_size: int = 4,
        preload_asr: bool = True,
        preload_kokoro: bool = True,
    ):
        self.settings = settings
        self.startup_timeout = float(startup_timeout)
        self.command_timeout = float(command_timeout)
        self.watchdog_interval = float(watchdog_interval)
        self.asr_queue_size = max(1, int(asr_queue_size))
        self.kokoro_queue_size = max(1, int(kokoro_queue_size))
        self.preload_asr = bool(preload_asr)
        self.preload_kokoro = bool(preload_kokoro)
        self._context = mp.get_context("spawn")
        self._command_queue: Any | None = None
        self._result_queue: Any | None = None
        self._process: mp.Process | None = None
        self._listener_thread: threading.Thread | None = None
        self._watchdog_thread: threading.Thread | None = None
        self._listener_stop = threading.Event()
        self._watchdog_stop = threading.Event()
        self._ready = threading.Event()
        self._lifecycle_lock = threading.RLock()
        self._pending_lock = threading.RLock()
        self._pending: dict[str, _PendingCall] = {}
        self._generation = 0
        self._restart_count = 0
        self._last_restart_reason: str | None = None
        self._last_heartbeat = 0.0
        self._stopping = False
        self._inflight_lock = threading.RLock()
        self._inflight_asr = 0
        self._inflight_kokoro = 0

    @property
    def process_alive(self) -> bool:
        process = self._process
        return bool(process is not None and process.is_alive())

    @property
    def pid(self) -> int | None:
        process = self._process
        return int(process.pid) if process is not None and process.pid else None

    def _settings_payload(self) -> dict[str, Any]:
        payload = self.settings.model_dump(mode="json")
        return dict(payload)

    def _listener_loop(self, generation: int) -> None:
        while not self._listener_stop.is_set() and generation == self._generation:
            result_queue = self._result_queue
            if result_queue is None:
                return
            try:
                payload = result_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            except (EOFError, OSError):
                return
            if not isinstance(payload, dict):
                continue
            if payload.get("kind") == "engine":
                if payload.get("event") == "ready":
                    self._last_heartbeat = time.monotonic()
                    self._ready.set()
                continue
            request_id = str(payload.get("id") or "")
            with self._pending_lock:
                pending = self._pending.get(request_id)
            if pending is None:
                continue
            try:
                pending.response_queue.put_nowait(payload)
            except queue.Full:
                pass

    def _fail_pending(self, message: str) -> None:
        with self._pending_lock:
            pending_calls = list(self._pending.values())
            self._pending.clear()
        for pending in pending_calls:
            try:
                pending.response_queue.put_nowait(
                    {
                        "kind": "response",
                        "id": pending.request_id,
                        "ok": False,
                        "error": {"type": "AiEngineUnavailable", "message": message},
                    }
                )
            except queue.Full:
                pass

    def start(self) -> None:
        with self._lifecycle_lock:
            if self.process_alive:
                return
            self._stopping = False
            self._listener_stop.clear()
            self._watchdog_stop.clear()
            self._ready.clear()
            self._generation += 1
            generation = self._generation
            queue_size = max(8, self.asr_queue_size + self.kokoro_queue_size + 4)
            self._command_queue = self._context.Queue(maxsize=queue_size)
            self._result_queue = self._context.Queue(maxsize=queue_size * 2)
            self._process = self._context.Process(
                target=_ai_engine_worker,
                args=(
                    self._command_queue,
                    self._result_queue,
                    self._settings_payload(),
                    self.preload_asr,
                    self.preload_kokoro,
                ),
                name="VerbaNodeAIEngine",
                daemon=True,
            )
            self._listener_thread = threading.Thread(
                target=self._listener_loop,
                args=(generation,),
                name="ai-engine-listener",
                daemon=True,
            )
            self._listener_thread.start()
            try:
                self._process.start()
            except Exception as exc:
                self._listener_stop.set()
                if self._listener_thread is not None:
                    self._listener_thread.join(timeout=1.0)
                self._close_ipc_queues()
                self._process = None
                raise AiEngineUnavailable(
                    f"Could not create the isolated AI Engine process: {exc}"
                ) from exc

            deadline = time.monotonic() + self.startup_timeout
            while not self._ready.wait(timeout=0.10):
                if not self.process_alive or time.monotonic() >= deadline:
                    process = self._process
                    exit_code = process.exitcode if process is not None else None
                    self._listener_stop.set()
                    if process is not None and process.is_alive():
                        process.terminate()
                        process.join(timeout=2.0)
                    if self._listener_thread is not None:
                        self._listener_thread.join(timeout=1.0)
                    self._close_ipc_queues()
                    self._process = None
                    raise AiEngineUnavailable(
                        "The isolated AI Engine did not become ready"
                        + (f" (exit code {exit_code})" if exit_code is not None else "")
                    )
            LOGGER.info("Isolated AI Engine started in process %s", self.pid)
            if self._watchdog_thread is None or not self._watchdog_thread.is_alive():
                self._watchdog_thread = threading.Thread(
                    target=self._watchdog_loop,
                    name="ai-engine-watchdog",
                    daemon=True,
                )
                self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(max(1.0, self.watchdog_interval)):
            if self._stopping:
                return
            if not self.process_alive:
                self.restart("AI process exited")
                continue
            try:
                self.call(
                    "engine.ping",
                    timeout=max(1.0, self.watchdog_interval * 0.75),
                    restart_on_timeout=False,
                )
                self._last_heartbeat = time.monotonic()
            except Exception as exc:
                self.restart(f"watchdog heartbeat failed: {exc}")

    def restart(self, reason: str = "manual restart") -> None:
        with self._lifecycle_lock:
            if self._stopping:
                return
            self._restart_count += 1
            self._last_restart_reason = str(reason)
            LOGGER.warning("Restarting isolated AI Engine: %s", reason)
            self._terminate_current(f"AI Engine restarted: {reason}")
            try:
                self.start()
            except Exception as exc:
                self._last_restart_reason = f"{reason}; restart failed: {exc}"
                LOGGER.exception("Could not restart isolated AI Engine")
                raise

    def _close_ipc_queues(self) -> None:
        for ipc_queue in (self._command_queue, self._result_queue):
            if ipc_queue is None:
                continue
            try:
                ipc_queue.cancel_join_thread()
            except Exception:
                pass
            try:
                ipc_queue.close()
            except Exception:
                pass

    def _terminate_current(self, pending_error: str) -> None:
        process = self._process
        self._listener_stop.set()
        self._fail_pending(pending_error)
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=3.0)
        listener = self._listener_thread
        if listener is not None and listener is not threading.current_thread():
            listener.join(timeout=1.0)
        self._close_ipc_queues()
        self._process = None
        self._command_queue = None
        self._result_queue = None
        self._listener_thread = None
        self._ready.clear()

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stopping = True
            self._watchdog_stop.set()
            try:
                if self.process_alive:
                    self.call(
                        "engine.shutdown",
                        timeout=2.0,
                        ensure_started=False,
                        restart_on_timeout=False,
                    )
            except Exception:
                pass
            process = self._process
            if process is not None:
                process.join(timeout=3.0)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2.0)
            self._terminate_current("AI Engine stopped")
            watchdog = self._watchdog_thread
            if watchdog is not None and watchdog is not threading.current_thread():
                watchdog.join(timeout=1.0)
            self._watchdog_thread = None

    def _reserve_slot(self, operation: str) -> str | None:
        provider = "asr" if operation.startswith("asr.") else "kokoro" if operation.startswith("kokoro.") else None
        if provider is None:
            return None
        with self._inflight_lock:
            if provider == "asr":
                if self._inflight_asr >= self.asr_queue_size:
                    raise AiEngineUnavailable(
                        f"AI Engine ASR queue is full ({self.asr_queue_size} jobs)"
                    )
                self._inflight_asr += 1
            else:
                if self._inflight_kokoro >= self.kokoro_queue_size:
                    raise AiEngineUnavailable(
                        f"AI Engine Kokoro queue is full ({self.kokoro_queue_size} jobs)"
                    )
                self._inflight_kokoro += 1
        return provider

    def _release_slot(self, provider: str | None) -> None:
        if provider is None:
            return
        with self._inflight_lock:
            if provider == "asr":
                self._inflight_asr = max(0, self._inflight_asr - 1)
            else:
                self._inflight_kokoro = max(0, self._inflight_kokoro - 1)

    def call(
        self,
        operation: str,
        *args: Any,
        timeout: float | None = None,
        ensure_started: bool = True,
        restart_on_timeout: bool = True,
        **kwargs: Any,
    ) -> Any:
        if ensure_started:
            self.start()
        if not self.process_alive or self._command_queue is None:
            raise AiEngineUnavailable("The isolated AI Engine is not running")
        provider = self._reserve_slot(operation)
        request_id = uuid.uuid4().hex
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        pending = _PendingCall(request_id, operation, response_queue)
        with self._pending_lock:
            self._pending[request_id] = pending
        effective_timeout = float(timeout or self.command_timeout)
        try:
            self._command_queue.put(
                {
                    "id": request_id,
                    "operation": operation,
                    "args": args,
                    "kwargs": kwargs,
                },
                timeout=min(2.0, effective_timeout),
            )
            try:
                response = response_queue.get(timeout=effective_timeout)
            except queue.Empty as exc:
                message = f"AI Engine operation '{operation}' timed out after {effective_timeout:g} seconds"
                if restart_on_timeout and operation not in {"engine.ping", "engine.status"}:
                    try:
                        self.restart(message)
                    except Exception:
                        pass
                raise AiEngineUnavailable(message) from exc
            if not response.get("ok"):
                error = dict(response.get("error") or {})
                message = str(error.get("message") or "Unknown AI Engine error")
                raise AiEngineUnavailable(message)
            return response.get("result")
        except queue.Full as exc:
            raise AiEngineUnavailable("The AI Engine command queue is full") from exc
        finally:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            self._release_slot(provider)

    def reload_asr(self, model_name: str | None = None) -> dict[str, Any]:
        return dict(
            self.call(
                "asr.reload",
                model_name or self.settings.funasr_model,
                timeout=max(self.command_timeout, 120.0),
            )
        )

    def reload_kokoro(self) -> dict[str, Any]:
        return dict(
            self.call(
                "kokoro.reload",
                timeout=max(self.command_timeout, 120.0),
            )
        )

    def health(self) -> dict[str, Any]:
        remote: dict[str, Any] | None = None
        if self.process_alive:
            try:
                remote = dict(
                    self.call(
                        "engine.status",
                        timeout=2.0,
                        ensure_started=False,
                        restart_on_timeout=False,
                    )
                )
            except Exception as exc:
                remote = {"error": str(exc)}
        with self._inflight_lock:
            inflight = {"asr": self._inflight_asr, "kokoro": self._inflight_kokoro}
        heartbeat_age = (
            round(time.monotonic() - self._last_heartbeat, 1)
            if self._last_heartbeat
            else None
        )
        return {
            "mode": "isolated_process",
            "alive": self.process_alive,
            "pid": self.pid,
            "restart_count": self._restart_count,
            "last_restart_reason": self._last_restart_reason,
            "heartbeat_age_seconds": heartbeat_age,
            "queue_limits": {
                "asr": self.asr_queue_size,
                "kokoro": self.kokoro_queue_size,
            },
            "inflight": inflight,
            "remote": remote,
        }


class AiSttProxy:
    """Expose the existing STT interface through the isolated AI Engine."""

    def __init__(self, engine: AiEngineSupervisor, settings: Settings):
        self.engine = engine
        self.settings = settings
        self._last_requested_model: str | None = None
        self._last_fallback_model: str | None = None
        self._last_fallback_reason: str | None = None

    def transcribe_with_confidence(
        self,
        samples: np.ndarray,
        model_name: str | None = None,
        language: str | None = None,
    ) -> TranscriptionResult:
        timeout = max(2.0, float(self.settings.stt_timeout_seconds) - 1.0)
        requested_model = model_name or self.settings.funasr_model
        requested_language = language or "en"
        self._last_requested_model = requested_model
        self._last_fallback_model = None
        self._last_fallback_reason = None
        audio = np.asarray(samples, dtype=np.float32).reshape(-1).copy()
        try:
            result = dict(
                self.engine.call(
                    "asr.transcribe",
                    audio,
                    requested_model,
                    requested_language,
                    timeout=timeout,
                )
            )
        except AiEngineUnavailable as exc:
            fallback = FunASRService.fallback_model(requested_model, requested_language)
            if fallback is None:
                raise SttUnavailable(f"AI Engine speech recognition failed: {exc}") from exc
            LOGGER.warning(
                "ASR model %s failed for %s; retrying once with %s: %s",
                requested_model,
                requested_language,
                fallback,
                exc,
            )
            self._last_fallback_model = fallback
            self._last_fallback_reason = str(exc)
            try:
                result = dict(
                    self.engine.call(
                        "asr.transcribe",
                        audio,
                        fallback,
                        requested_language,
                        timeout=timeout,
                    )
                )
            except AiEngineUnavailable as fallback_exc:
                raise SttUnavailable(
                    f"AI Engine speech recognition failed with {requested_model} and fallback {fallback}: {fallback_exc}"
                ) from fallback_exc
        return TranscriptionResult(
            str(result.get("text") or ""),
            float(result.get("confidence") or 0.0),
            str(result.get("confidence_source") or "estimated"),
        )

    def transcribe(
        self, samples: np.ndarray, model_name: str | None = None, language: str | None = None
    ) -> str:
        return self.transcribe_with_confidence(samples, model_name, language).text

    def status(self) -> dict[str, Any]:
        health = self.engine.health()
        remote = health.get("remote") or {}
        asr = remote.get("asr") or {}
        cache = FunASRService.whisper_cache_status()
        loaded_model = asr.get("model") or self.settings.funasr_model
        if bool(asr.get("loaded")) and FunASRService._is_whisper_model(str(loaded_model)):
            cached = cache.get("models", {}).get(str(loaded_model))
            if cached is not None:
                cached["downloaded"] = True
                cached["loaded"] = True
        return {
            "provider": "FunASR via AI Engine",
            "installed": asr.get("installed") is not False,
            "loaded": bool(asr.get("loaded")),
            "model": loaded_model,
            "confidence": "estimated",
            "state": asr.get("state") or ("starting" if health.get("alive") else "unavailable"),
            "last_latency_ms": asr.get("last_latency_ms"),
            "model_load_ms": asr.get("model_load_ms"),
            "last_error": asr.get("last_error"),
            "engine_pid": health.get("pid"),
            "requested_model": self._last_requested_model,
            "fallback_model": self._last_fallback_model,
            "fallback_reason": self._last_fallback_reason,
            "whisper_cache": cache,
        }


class AiKokoroProxy:
    """Expose local Kokoro synthesis through the isolated AI Engine."""

    def __init__(self, engine: AiEngineSupervisor, settings: Settings):
        self.engine = engine
        self.settings = settings

    def _paths(self) -> dict[str, Path]:
        base = self.settings.kokoro_dir
        model = next(
            (
                candidate
                for candidate in (base / "model.int8.onnx", base / "model.onnx")
                if candidate.exists()
            ),
            base / "model.int8.onnx",
        )
        return {
            "model": model,
            "voices": base / "voices.bin",
            "tokens": base / "tokens.txt",
            "data_dir": base / "espeak-ng-data",
        }

    def model_ready(self) -> bool:
        paths = self._paths()
        return all(paths[name].exists() for name in ("model", "voices", "tokens", "data_dir"))

    def model_fingerprint(self) -> str:
        model = self._paths()["model"]
        if not model.exists():
            return str(model)
        stat = model.stat()
        return f"{model.name}:{stat.st_size}:{stat.st_mtime_ns}"

    def generate(self, text: str, voice_id: int, speed: float) -> Path:
        try:
            result = dict(
                self.engine.call(
                    "kokoro.generate",
                    text,
                    int(voice_id),
                    float(speed),
                    timeout=float(self.settings.ai_engine_kokoro_timeout_seconds),
                )
            )
        except AiEngineUnavailable as exc:
            raise TtsUnavailable(f"AI Engine Kokoro synthesis failed: {exc}") from exc
        path = Path(str(result.get("path") or ""))
        if not path.exists() or path.stat().st_size <= 0:
            raise TtsUnavailable("AI Engine Kokoro returned no audio file")
        return path

    def status(self) -> dict[str, Any]:
        health = self.engine.health()
        remote = health.get("remote") or {}
        kokoro = remote.get("kokoro") or {}
        return {
            "installed": kokoro.get("installed") is not False,
            "model_ready": self.model_ready(),
            "loaded": bool(kokoro.get("loaded")),
            "state": kokoro.get("state") or ("starting" if health.get("alive") else "unavailable"),
            "last_latency_ms": kokoro.get("last_latency_ms"),
            "model_load_ms": kokoro.get("model_load_ms"),
            "last_error": kokoro.get("last_error"),
            "engine_pid": health.get("pid"),
        }
