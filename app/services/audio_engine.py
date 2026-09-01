from __future__ import annotations

import json
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
from typing import Any, Callable

import numpy as np

from app.services.audio import AudioUnavailable, HostAudioPlayer, HostAudioRecorder

LOGGER = logging.getLogger(__name__)


class AudioEngineUnavailable(AudioUnavailable):
    """Raised when the isolated audio process cannot complete a command."""


_CONTROL_OPERATIONS = {
    "engine.ping",
    "engine.status",
    "engine.shutdown",
    "engine.refresh_devices",
    "recorder.health",
    "recorder.input_locked",
    "recorder.locked_input_device",
    "recorder.cancel_capture",
    "recorder.cancel_ptt",
    "recorder.unlock_input",
    "player.health",
    "player.configured_output_device",
    "player.output_locked",
    "player.is_playing",
    "player.stop",
    "player.close",
    "player.request_refresh",
}


def _serialize_error(exc: BaseException) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }


def _audio_engine_worker(
    command_queue: Any,
    result_queue: Any,
    sample_rate: int,
) -> None:
    """Own all PortAudio objects inside one child process.

    The command loop stays responsive while capture/playback run in worker
    threads. This lets stop/cancel and watchdog commands interrupt long native
    audio operations without involving the FastAPI process.
    """

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] [%(processName)s] %(name)s - %(message)s",
    )
    recorder = HostAudioRecorder(sample_rate)
    player = HostAudioPlayer()
    closing = threading.Event()
    operation_threads: set[threading.Thread] = set()
    operation_lock = threading.RLock()

    def emit(payload: dict[str, Any]) -> None:
        try:
            result_queue.put(payload)
        except Exception:
            pass

    def execute(request: dict[str, Any]) -> None:
        request_id = str(request.get("id") or "")
        operation = str(request.get("operation") or "")
        args = list(request.get("args") or [])
        kwargs = dict(request.get("kwargs") or {})
        try:
            if operation == "engine.ping":
                result: Any = {
                    "ok": True,
                    "pid": os.getpid(),
                    "time": time.monotonic(),
                }
            elif operation == "engine.status":
                recorder_health = recorder.health()
                player_health = player.health()
                if player_health.get("playing"):
                    coordinator_state = "speaking"
                elif recorder_health.get("ptt_active"):
                    coordinator_state = "recording"
                elif recorder_health.get("capture_active"):
                    coordinator_state = "listening"
                else:
                    coordinator_state = "idle"
                result = {
                    "pid": os.getpid(),
                    "coordinator_state": coordinator_state,
                    "recorder": recorder_health,
                    "player": player_health,
                }
            elif operation == "engine.refresh_devices":
                settle_seconds = float(kwargs.get("settle_seconds", 0.45))
                recorder.cancel_capture(wait=True, timeout=2.0)
                recorder.cancel_ptt()
                player.stop()
                recorder.unlock_input()
                player.close()
                HostAudioRecorder.refresh_portaudio(settle_seconds=settle_seconds)
                devices = HostAudioRecorder.list_devices()
                result = {
                    "ok": True,
                    "devices": devices,
                    "device_count": len(devices),
                    "time": time.monotonic(),
                }
            elif operation == "recorder.list_devices":
                result = HostAudioRecorder.list_devices()
            elif operation == "recorder.device_info":
                result = HostAudioRecorder.device_info(*args, **kwargs)
            elif operation == "recorder.resolve_device_id":
                result = HostAudioRecorder.resolve_device_id(*args, **kwargs)
            elif operation == "recorder.health":
                result = recorder.health()
            elif operation == "recorder.input_locked":
                result = recorder.input_locked
            elif operation == "recorder.locked_input_device":
                result = recorder.locked_input_device
            elif operation == "recorder.lock_input":
                result = recorder.lock_input(*args, **kwargs)
            elif operation == "recorder.unlock_input":
                result = recorder.unlock_input()
            elif operation == "recorder.test_input":
                result = recorder.test_input(*args, **kwargs)
            elif operation == "recorder.start_ptt":
                result = recorder.start_ptt(*args, **kwargs)
            elif operation == "recorder.stop_ptt":
                result = recorder.stop_ptt(*args, **kwargs)
            elif operation == "recorder.cancel_ptt":
                result = recorder.cancel_ptt()
            elif operation == "recorder.cancel_capture":
                result = recorder.cancel_capture(*args, **kwargs)
            elif operation == "recorder.capture_until_silence":
                kwargs.pop("cancel_event", None)
                kwargs["on_speech_start"] = lambda: emit(
                    {
                        "kind": "event",
                        "request_id": request_id,
                        "event": "speech_started",
                        "data": {},
                    }
                )
                result = recorder.capture_until_silence(*args, **kwargs)
            elif operation == "recorder.close":
                result = recorder.close()
            elif operation == "player.health":
                result = player.health()
            elif operation == "player.configured_output_device":
                result = player.configured_output_device
            elif operation == "player.output_locked":
                result = player.output_locked
            elif operation == "player.is_playing":
                result = player.is_playing
            elif operation == "player.set_output_device":
                result = player.set_output_device(*args, **kwargs)
            elif operation == "player.lock_output":
                result = player.lock_output(*args, **kwargs)
            elif operation == "player.stop":
                result = player.stop()
            elif operation == "player.request_refresh":
                result = player.request_refresh()
            elif operation == "player.play_file":
                kwargs.pop("cancel_check", None)
                result = player.play_file(*args, **kwargs)
            elif operation == "player.close":
                result = player.close()
            else:
                raise ValueError(f"Unknown audio-engine operation: {operation}")
            emit({"kind": "response", "id": request_id, "ok": True, "result": result})
        except BaseException as exc:  # keep the process alive after a failed device operation
            emit(
                {
                    "kind": "response",
                    "id": request_id,
                    "ok": False,
                    "error": _serialize_error(exc),
                }
            )
        finally:
            current = threading.current_thread()
            with operation_lock:
                operation_threads.discard(current)

    emit({"kind": "engine", "event": "ready", "pid": os.getpid()})
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
                try:
                    recorder.cancel_capture(wait=False)
                    recorder.cancel_ptt()
                    player.stop()
                except Exception:
                    pass
                emit(
                    {
                        "kind": "response",
                        "id": str(request.get("id") or ""),
                        "ok": True,
                        "result": True,
                    }
                )
                break
            if operation in _CONTROL_OPERATIONS:
                execute(request)
                continue
            thread = threading.Thread(
                target=execute,
                args=(request,),
                name=f"audio-op-{operation}-{str(request.get('id', ''))[:8]}",
                daemon=True,
            )
            with operation_lock:
                operation_threads.add(thread)
            thread.start()
    finally:
        closing.set()
        try:
            recorder.cancel_capture(wait=False)
            recorder.cancel_ptt()
            player.stop()
        except Exception:
            pass
        with operation_lock:
            threads = list(operation_threads)
        for thread in threads:
            thread.join(timeout=0.5)
        try:
            recorder.close()
        except Exception:
            pass
        try:
            player.close()
        except Exception:
            pass
        emit({"kind": "engine", "event": "stopped", "pid": os.getpid()})


@dataclass
class _PendingCall:
    request_id: str
    operation: str
    response_queue: queue.Queue[dict[str, Any]]
    event_callback: Callable[[str, dict[str, Any]], None] | None = None


class AudioEngineSupervisor:
    """Supervise one isolated process that owns microphone and speaker handles."""

    def __init__(
        self,
        *,
        sample_rate: int,
        startup_timeout: float = 8.0,
        command_timeout: float = 15.0,
        watchdog_interval: float = 3.0,
    ):
        self.sample_rate = int(sample_rate)
        self.startup_timeout = float(startup_timeout)
        self.command_timeout = float(command_timeout)
        self.watchdog_interval = float(watchdog_interval)
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
        self._desired_input_device: int | None = None
        self._desired_output_device: int | None = None
        self._desired_input_fingerprint: str | dict | None = None
        self._desired_output_fingerprint: str | dict | None = None
        self._input_should_be_locked = False
        self._output_should_be_locked = False
        self._device_refresh_count = 0
        self._device_recovery_count = 0
        self._last_device_recovery_reason: str | None = None
        self._device_state_callback: Callable[[int | None, int | None], None] | None = None
        self._recovery_lock = threading.RLock()
        self._stopping = False

    @property
    def process_alive(self) -> bool:
        process = self._process
        return bool(process is not None and process.is_alive())

    @property
    def pid(self) -> int | None:
        process = self._process
        return int(process.pid) if process is not None and process.pid else None

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
            kind = payload.get("kind")
            if kind == "engine":
                if payload.get("event") == "ready":
                    self._last_heartbeat = time.monotonic()
                    self._ready.set()
                continue
            request_id = str(payload.get("id") or payload.get("request_id") or "")
            with self._pending_lock:
                pending = self._pending.get(request_id)
            if pending is None:
                continue
            if kind == "event":
                callback = pending.event_callback
                if callback is not None:
                    event_name = str(payload.get("event") or "")
                    event_data = dict(payload.get("data") or {})

                    def run_callback() -> None:
                        try:
                            callback(event_name, event_data)
                        except Exception:
                            LOGGER.exception("Audio-engine event callback failed")

                    # Never execute callbacks on the result-listener thread. A
                    # speech-start callback may synchronously send STOP_PLAYBACK
                    # back to the Audio Engine and needs this listener to remain
                    # free to deliver that response.
                    threading.Thread(
                        target=run_callback,
                        name=f"audio-engine-event-{event_name}",
                        daemon=True,
                    ).start()
                continue
            if kind == "response":
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
                        "error": {"type": "AudioEngineUnavailable", "message": message},
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
            self._command_queue = self._context.Queue(maxsize=64)
            self._result_queue = self._context.Queue(maxsize=64)
            self._process = self._context.Process(
                target=_audio_engine_worker,
                args=(self._command_queue, self._result_queue, self.sample_rate),
                name="VerbaNodeAudioEngine",
                daemon=True,
            )
            self._listener_thread = threading.Thread(
                target=self._listener_loop,
                args=(generation,),
                name="audio-engine-listener",
                daemon=True,
            )
            self._listener_thread.start()
            try:
                self._process.start()
            except Exception as exc:
                self._listener_stop.set()
                listener = self._listener_thread
                if listener is not None:
                    listener.join(timeout=1.0)
                self._close_ipc_queues()
                self._process = None
                self._command_queue = None
                self._result_queue = None
                self._listener_thread = None
                raise AudioEngineUnavailable(
                    f"Could not create the isolated Audio Engine process: {exc}"
                ) from exc

            deadline = time.monotonic() + self.startup_timeout
            while not self._ready.wait(timeout=0.10):
                if not self.process_alive or time.monotonic() >= deadline:
                    process = self._process
                    exit_code = process.exitcode if process is not None else None
                    self._listener_stop.set()
                    if process and process.is_alive():
                        process.terminate()
                        process.join(timeout=2.0)
                    listener = self._listener_thread
                    if listener is not None:
                        listener.join(timeout=1.0)
                    self._close_ipc_queues()
                    self._process = None
                    self._command_queue = None
                    self._result_queue = None
                    self._listener_thread = None
                    raise AudioEngineUnavailable(
                        "The isolated Audio Engine did not become ready"
                        + (f" (exit code {exit_code})" if exit_code is not None else "")
                    )
            LOGGER.info("Isolated Audio Engine started in process %s", self.pid)
            if self._watchdog_thread is None or not self._watchdog_thread.is_alive():
                self._watchdog_thread = threading.Thread(
                    target=self._watchdog_loop,
                    name="audio-engine-watchdog",
                    daemon=True,
                )
                self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        while not self._watchdog_stop.wait(max(1.0, self.watchdog_interval)):
            if self._stopping:
                return
            if not self.process_alive:
                self.restart("audio process exited")
                continue
            try:
                self.call("engine.ping", timeout=max(1.0, self.watchdog_interval * 0.75))
                self._last_heartbeat = time.monotonic()
            except Exception as exc:
                self.restart(f"watchdog heartbeat failed: {exc}")

    def restart(self, reason: str) -> None:
        with self._lifecycle_lock:
            if self._stopping:
                return
            self._restart_count += 1
            self._last_restart_reason = str(reason)
            LOGGER.warning("Restarting isolated Audio Engine: %s", reason)
            self._terminate_current(f"Audio Engine restarted: {reason}")
            try:
                self.start()
                self._restore_device_state()
            except Exception as exc:
                self._last_restart_reason = f"{reason}; restart failed: {exc}"
                LOGGER.exception("Could not restart isolated Audio Engine")

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
            process.join(timeout=2.0)
        listener = self._listener_thread
        if listener is not None and listener is not threading.current_thread():
            listener.join(timeout=1.0)
        self._close_ipc_queues()
        self._process = None
        self._command_queue = None
        self._result_queue = None
        self._listener_thread = None
        self._ready.clear()

    def _resolve_desired_devices(self) -> tuple[int | None, int | None]:
        resolved_input = self.call(
            "recorder.resolve_device_id",
            self._desired_input_device,
            self._desired_input_fingerprint,
            "input",
            timeout=8.0,
            ensure_started=False,
        )
        resolved_output = self.call(
            "recorder.resolve_device_id",
            self._desired_output_device,
            self._desired_output_fingerprint,
            "output",
            timeout=8.0,
            ensure_started=False,
        )
        self._desired_input_device = int(resolved_input) if resolved_input is not None else None
        self._desired_output_device = int(resolved_output) if resolved_output is not None else None
        return self._desired_input_device, self._desired_output_device

    def _restore_device_state(self) -> None:
        try:
            self._resolve_desired_devices()
            self.call(
                "player.set_output_device",
                self._desired_output_device,
                timeout=self.command_timeout,
                ensure_started=False,
            )
            if self._output_should_be_locked:
                self.call(
                    "player.lock_output",
                    self._desired_output_device,
                    timeout=self.command_timeout,
                    ensure_started=False,
                )
            if self._input_should_be_locked:
                self.call(
                    "recorder.lock_input",
                    self._desired_input_device,
                    timeout=self.command_timeout,
                    ensure_started=False,
                )
        except Exception as exc:
            LOGGER.warning("Audio Engine restarted but device state could not be fully restored: %s", exc)

    @staticmethod
    def _fingerprint_matches_device(
        device: dict[str, Any], fingerprint: str | dict | None, direction: str
    ) -> bool:
        if not fingerprint:
            return False
        try:
            expected = (
                json.loads(fingerprint)
                if isinstance(fingerprint, str)
                else dict(fingerprint)
            )
        except Exception:
            return False
        channel_key = "max_input_channels" if direction == "input" else "max_output_channels"
        if int(device.get(channel_key, 0)) <= 0:
            return False
        return (
            str(device.get("name", "")).strip().casefold()
            == str(expected.get("name", "")).strip().casefold()
            and str(device.get("hostapi", "")).strip().casefold()
            == str(expected.get("hostapi", "")).strip().casefold()
        )

    def _desired_targets_available(self, devices: list[dict[str, Any]]) -> bool:
        def available(
            desired_id: int | None, fingerprint: str | dict | None, direction: str, required: bool
        ) -> bool:
            channel_key = (
                "max_input_channels" if direction == "input" else "max_output_channels"
            )
            candidates = [d for d in devices if int(d.get(channel_key, 0)) > 0]
            if fingerprint:
                return any(
                    self._fingerprint_matches_device(d, fingerprint, direction)
                    for d in candidates
                )
            if desired_id is not None:
                return any(int(d.get("id", -1)) == int(desired_id) for d in candidates)
            return bool(candidates) if required else True

        return available(
            self._desired_input_device,
            self._desired_input_fingerprint,
            "input",
            self._input_should_be_locked,
        ) and available(
            self._desired_output_device,
            self._desired_output_fingerprint,
            "output",
            self._output_should_be_locked,
        )

    def refresh_devices(
        self,
        *,
        attempts: int = 4,
        settle_seconds: float = 0.60,
        reason: str = "manual device refresh",
    ) -> dict[str, Any]:
        """Reinitialize PortAudio and rebuild the child process device snapshot."""
        with self._recovery_lock:
            self.start()
            last_result: dict[str, Any] = {"ok": False, "devices": []}
            last_error: Exception | None = None
            for attempt in range(max(1, int(attempts))):
                if attempt:
                    time.sleep(min(3.0, 1.0 * attempt))
                try:
                    last_result = dict(
                        self.call(
                            "engine.refresh_devices",
                            settle_seconds=float(settle_seconds),
                            timeout=max(self.command_timeout, 8.0),
                            ensure_started=False,
                        )
                    )
                    self._device_refresh_count += 1
                    devices = list(last_result.get("devices") or [])
                    # Existing built-in endpoints can make the list non-empty while
                    # the requested Bluetooth/USB profile is still registering.
                    # Wait for the saved fingerprint or selected ID, not merely any
                    # device, before ending the staged hot-plug retry window.
                    if self._desired_targets_available(devices):
                        return last_result
                    if attempt + 1 >= max(1, int(attempts)):
                        return last_result
                    LOGGER.info(
                        "Requested Windows audio endpoint is not visible yet; "
                        "waiting for hot-plug registration (%d/%d)",
                        attempt + 1,
                        max(1, int(attempts)),
                    )
                except Exception as exc:
                    last_error = exc
                    LOGGER.warning(
                        "Windows audio refresh attempt %d/%d failed (%s): %s",
                        attempt + 1,
                        max(1, int(attempts)),
                        reason,
                        exc,
                    )
                    if attempt == 0 and self.process_alive:
                        self.restart(f"device refresh failed: {reason}")
            if last_error is not None:
                raise AudioEngineUnavailable(
                    f"Could not refresh Windows audio devices: {last_error}"
                ) from last_error
            return last_result

    def recover_devices(
        self,
        reason: str,
        *,
        attempts: int = 4,
    ) -> dict[str, Any]:
        """Refresh, remap saved fingerprints, and restore requested locks."""
        with self._recovery_lock:
            self._last_device_recovery_reason = str(reason)
            LOGGER.warning("Recovering Windows audio devices: %s", reason)
            refresh = self.refresh_devices(attempts=attempts, reason=reason)
            resolved_input, resolved_output = self._resolve_desired_devices()
            self.call(
                "player.set_output_device",
                resolved_output,
                timeout=self.command_timeout,
                ensure_started=False,
            )
            restored_output = None
            restored_input = None
            errors: list[str] = []
            if self._output_should_be_locked:
                try:
                    restored_output = self.call(
                        "player.lock_output",
                        resolved_output,
                        timeout=self.command_timeout,
                        ensure_started=False,
                    )
                except Exception as exc:
                    errors.append(f"speaker: {exc}")
            if self._input_should_be_locked:
                try:
                    restored_input = self.call(
                        "recorder.lock_input",
                        resolved_input,
                        timeout=self.command_timeout,
                        ensure_started=False,
                    )
                except Exception as exc:
                    errors.append(f"microphone: {exc}")
            if errors:
                # Some Windows backends keep stale native handles even after
                # Pa_Terminate/Pa_Initialize. A fresh child process is the final
                # recovery boundary because it recreates Python, PortAudio, and
                # every callback/stream object together.
                first_errors = "; ".join(errors)
                LOGGER.warning(
                    "Audio endpoints still unavailable after PortAudio refresh; "
                    "restarting the Audio Engine once: %s",
                    first_errors,
                )
                self.restart(f"hot-plug reopen failed: {first_errors}")
                refresh = self.refresh_devices(
                    attempts=2, settle_seconds=0.75, reason=f"post-restart {reason}"
                )
                resolved_input, resolved_output = self._resolve_desired_devices()
                self.call(
                    "player.set_output_device",
                    resolved_output,
                    timeout=self.command_timeout,
                    ensure_started=False,
                )
                restored_output = None
                restored_input = None
                retry_errors: list[str] = []
                if self._output_should_be_locked:
                    try:
                        restored_output = self.call(
                            "player.lock_output",
                            resolved_output,
                            timeout=self.command_timeout,
                            ensure_started=False,
                        )
                    except Exception as exc:
                        retry_errors.append(f"speaker: {exc}")
                if self._input_should_be_locked:
                    try:
                        restored_input = self.call(
                            "recorder.lock_input",
                            resolved_input,
                            timeout=self.command_timeout,
                            ensure_started=False,
                        )
                    except Exception as exc:
                        retry_errors.append(f"microphone: {exc}")
                if retry_errors:
                    raise AudioEngineUnavailable(
                        "Windows audio devices were refreshed and the Audio Engine "
                        "was restarted, but the endpoints still could not be opened ("
                        + "; ".join(retry_errors)
                        + ")"
                    )
            self._device_recovery_count += 1
            callback = self._device_state_callback
            if callback is not None:
                try:
                    callback(resolved_input, resolved_output)
                except Exception:
                    LOGGER.exception("Could not persist remapped audio device IDs")
            LOGGER.info(
                "Windows audio recovery completed: input=%s output=%s",
                resolved_input if resolved_input is not None else "default",
                resolved_output if resolved_output is not None else "default",
            )
            return {
                "ok": True,
                "refresh": refresh,
                "input_device": resolved_input,
                "output_device": resolved_output,
                "input": restored_input,
                "output": restored_output,
            }

    def submit(
        self,
        operation: str,
        *args: Any,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
        ensure_started: bool = True,
        **kwargs: Any,
    ) -> _PendingCall:
        if ensure_started:
            self.start()
        if not self.process_alive or self._command_queue is None:
            raise AudioEngineUnavailable("The isolated audio engine is not running")
        request_id = uuid.uuid4().hex
        pending = _PendingCall(request_id, operation, queue.Queue(maxsize=1), event_callback)
        with self._pending_lock:
            self._pending[request_id] = pending
        payload = {
            "id": request_id,
            "operation": operation,
            "args": args,
            "kwargs": kwargs,
        }
        try:
            self._command_queue.put(payload, timeout=1.0)
        except Exception as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise AudioEngineUnavailable(f"Could not send command to Audio Engine: {exc}") from exc
        return pending

    def wait(self, pending: _PendingCall, timeout: float | None = None) -> Any:
        timeout = self.command_timeout if timeout is None else float(timeout)
        try:
            response = pending.response_queue.get(timeout=max(0.05, timeout))
        except queue.Empty as exc:
            message = (
                f"Audio Engine command {pending.operation} timed out "
                f"after {timeout:.1f} seconds"
            )
            if (
                pending.operation not in {"engine.ping", "engine.status"}
                and self.process_alive
                and not self._stopping
            ):
                self.restart(message)
            raise AudioEngineUnavailable(message) from exc
        finally:
            with self._pending_lock:
                self._pending.pop(pending.request_id, None)
        if response.get("ok"):
            return response.get("result")
        error = dict(response.get("error") or {})
        message = str(error.get("message") or "Unknown Audio Engine failure")
        error_type = str(error.get("type") or "AudioEngineUnavailable")
        if error_type in {"AudioUnavailable", "AudioEngineUnavailable"}:
            raise AudioEngineUnavailable(message)
        raise AudioEngineUnavailable(f"{error_type}: {message}")

    def call(
        self,
        operation: str,
        *args: Any,
        timeout: float | None = None,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
        ensure_started: bool = True,
        **kwargs: Any,
    ) -> Any:
        pending = self.submit(
            operation,
            *args,
            event_callback=event_callback,
            ensure_started=ensure_started,
            **kwargs,
        )
        return self.wait(pending, timeout=timeout)

    def set_device_state_callback(
        self, callback: Callable[[int | None, int | None], None] | None
    ) -> None:
        self._device_state_callback = callback

    def configure_input(
        self,
        device: int | None,
        *,
        fingerprint: str | dict | None = None,
        locked: bool | None = None,
    ) -> None:
        self._desired_input_device = int(device) if device is not None else None
        if fingerprint is not None:
            self._desired_input_fingerprint = fingerprint
        if locked is not None:
            self._input_should_be_locked = bool(locked)

    def configure_output(
        self,
        device: int | None,
        *,
        fingerprint: str | dict | None = None,
        locked: bool | None = None,
    ) -> None:
        self._desired_output_device = int(device) if device is not None else None
        if fingerprint is not None:
            self._desired_output_fingerprint = fingerprint
        if locked is not None:
            self._output_should_be_locked = bool(locked)

    def health(self) -> dict[str, Any]:
        remote: dict[str, Any] = {}
        if self.process_alive:
            try:
                remote = dict(self.call("engine.status", timeout=2.0))
            except Exception as exc:
                remote = {"error": str(exc)}
        return {
            "mode": "isolated_process",
            "alive": self.process_alive,
            "pid": self.pid,
            "restart_count": self._restart_count,
            "last_restart_reason": self._last_restart_reason,
            "device_refresh_count": self._device_refresh_count,
            "device_recovery_count": self._device_recovery_count,
            "last_device_recovery_reason": self._last_device_recovery_reason,
            "seconds_since_heartbeat": (
                round(time.monotonic() - self._last_heartbeat, 2)
                if self._last_heartbeat
                else None
            ),
            "remote": remote,
        }

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stopping = True
            self._watchdog_stop.set()
            if self.process_alive:
                try:
                    self.call("engine.shutdown", timeout=3.0, ensure_started=False)
                except Exception:
                    pass
            process = self._process
            if process is not None:
                process.join(timeout=3.0)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2.0)
            self._listener_stop.set()
            self._fail_pending("Audio Engine stopped")
            listener = self._listener_thread
            if listener is not None and listener is not threading.current_thread():
                listener.join(timeout=1.0)
            watchdog = self._watchdog_thread
            if watchdog is not None and watchdog is not threading.current_thread():
                watchdog.join(timeout=2.0)
            self._close_ipc_queues()
            self._process = None
            self._command_queue = None
            self._result_queue = None
            self._listener_thread = None
            self._watchdog_thread = None
            LOGGER.info("Isolated Audio Engine stopped")


class AudioRecorderProxy:
    """Recorder-compatible proxy whose implementation lives in Audio Engine."""

    def __init__(self, engine: AudioEngineSupervisor, sample_rate: int = 16000):
        self.engine = engine
        self.sample_rate = int(sample_rate)

    @staticmethod
    def device_fingerprint(device: dict | None, direction: str) -> str | None:
        return HostAudioRecorder.device_fingerprint(device, direction)

    def resolve_device_id(
        self,
        preferred_id: int | None,
        fingerprint: str | dict | None,
        direction: str,
    ) -> int | None:
        value = self.engine.call(
            "recorder.resolve_device_id",
            preferred_id,
            fingerprint,
            direction,
            timeout=8.0,
        )
        return int(value) if value is not None else None

    def list_devices(self) -> list[dict]:
        return list(self.engine.call("recorder.list_devices", timeout=8.0))

    def device_info(self, device_id: int | None, direction: str | None = None) -> dict | None:
        result = self.engine.call("recorder.device_info", device_id, direction, timeout=5.0)
        return dict(result) if result else None

    def health(self) -> dict:
        try:
            result = dict(self.engine.call("recorder.health", timeout=2.0, ensure_started=False))
        except Exception as exc:
            result = {"input_locked": False, "error": str(exc)}
        result["engine_alive"] = self.engine.process_alive
        return result

    @property
    def input_locked(self) -> bool:
        try:
            return bool(self.engine.call("recorder.input_locked", timeout=2.0, ensure_started=False))
        except Exception:
            return False

    @property
    def locked_input_device(self) -> int | None:
        try:
            value = self.engine.call("recorder.locked_input_device", timeout=2.0, ensure_started=False)
            return int(value) if value is not None else None
        except Exception:
            return None

    def lock_input(self, input_device: int | None = None) -> dict:
        self.engine.configure_input(input_device, locked=True)
        try:
            return dict(self.engine.call("recorder.lock_input", input_device, timeout=15.0))
        except AudioEngineUnavailable as first_error:
            recovery = self.engine.recover_devices(
                f"microphone lock failed: {first_error}",
                attempts=4,
            )
            resolved = recovery.get("input_device")
            return dict(self.engine.call("recorder.lock_input", resolved, timeout=15.0))

    def unlock_input(self) -> None:
        self.engine.configure_input(self.engine._desired_input_device, locked=False)
        self.engine.call("recorder.unlock_input", timeout=5.0)

    def test_input(self, input_device: int | None = None, seconds: float = 1.5) -> dict:
        timeout = max(8.0, float(seconds) + 5.0)
        try:
            return dict(
                self.engine.call(
                    "recorder.test_input",
                    input_device,
                    seconds,
                    timeout=timeout,
                )
            )
        except AudioEngineUnavailable as first_error:
            self.engine.configure_input(input_device, locked=False)
            recovery = self.engine.recover_devices(
                f"microphone test failed: {first_error}", attempts=4
            )
            return dict(
                self.engine.call(
                    "recorder.test_input",
                    recovery.get("input_device"),
                    seconds,
                    timeout=timeout,
                )
            )

    def start_ptt(self, input_device: int | None = None) -> None:
        # Lock first so hot-plug recovery runs before the PTT operation starts.
        self.lock_input(input_device)
        try:
            self.engine.call("recorder.start_ptt", self.engine._desired_input_device, timeout=8.0)
        except AudioEngineUnavailable as first_error:
            recovery = self.engine.recover_devices(
                f"PTT microphone start failed: {first_error}", attempts=4
            )
            self.engine.call(
                "recorder.start_ptt", recovery.get("input_device"), timeout=8.0
            )

    def stop_ptt(self, minimum_seconds: float = 0.12) -> np.ndarray:
        result = self.engine.call("recorder.stop_ptt", minimum_seconds, timeout=8.0)
        return np.asarray(result, dtype=np.float32)

    def cancel_ptt(self) -> None:
        self.engine.call("recorder.cancel_ptt", timeout=3.0)

    def cancel_capture(self, wait: bool = True, timeout: float = 2.0) -> bool:
        return bool(
            self.engine.call(
                "recorder.cancel_capture",
                wait,
                timeout,
                timeout=max(3.0, float(timeout) + 1.0),
            )
        )

    def capture_until_silence(
        self,
        *,
        silence_ms: int,
        max_seconds: int,
        input_device: int | None = None,
        cancel_event: threading.Event | None = None,
        on_speech_start: Callable[[], None] | None = None,
    ) -> np.ndarray:
        # Ensure the endpoint is open before starting the long capture command.
        # This is where hot-plug recovery and fingerprint remapping are applied.
        self.lock_input(input_device)

        def event_callback(event: str, data: dict[str, Any]) -> None:
            if event == "speech_started" and on_speech_start is not None:
                on_speech_start()

        pending = self.engine.submit(
            "recorder.capture_until_silence",
            silence_ms=silence_ms,
            max_seconds=max_seconds,
            input_device=input_device,
            event_callback=event_callback,
        )
        deadline = time.monotonic() + float(max_seconds) + 10.0
        cancel_sent = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                try:
                    self.cancel_capture(wait=False)
                except Exception:
                    pass
                with self.engine._pending_lock:
                    self.engine._pending.pop(pending.request_id, None)
                message = "Microphone capture timed out inside Audio Engine"
                self.engine.restart(message)
                raise AudioEngineUnavailable(message)
            if cancel_event is not None and cancel_event.is_set() and not cancel_sent:
                cancel_sent = True
                try:
                    self.cancel_capture(wait=False)
                except Exception:
                    pass
            try:
                response = pending.response_queue.get(timeout=min(0.10, remaining))
            except queue.Empty:
                continue
            with self.engine._pending_lock:
                self.engine._pending.pop(pending.request_id, None)
            if response.get("ok"):
                return np.asarray(response.get("result"), dtype=np.float32)
            error = dict(response.get("error") or {})
            raise AudioEngineUnavailable(str(error.get("message") or "Audio capture failed"))

    def close(self) -> None:
        try:
            self.engine.configure_input(self.engine._desired_input_device, locked=False)
            self.engine.call("recorder.close", timeout=5.0)
        except Exception:
            pass


class AudioPlayerProxy:
    """Player-compatible proxy whose implementation lives in Audio Engine."""

    def __init__(
        self,
        engine: AudioEngineSupervisor,
        output_device: int | None = None,
        output_fingerprint: str | dict | None = None,
    ):
        self.engine = engine
        self.engine.configure_output(
            output_device, fingerprint=output_fingerprint, locked=False
        )
        # Playback normally lives in the isolated Audio Engine. Keep a dormant
        # in-process player as a last-resort output path for Windows systems where
        # the child process or a stale saved PortAudio endpoint cannot open. This
        # fallback is activated only after isolated-engine recovery is exhausted.
        self._fallback_player = HostAudioPlayer(output_device)
        self._using_local_fallback = False
        self._session_default_fallback = False
        self._last_fallback_reason: str | None = None

    @property
    def configured_output_device(self) -> int | None:
        try:
            value = self.engine.call("player.configured_output_device", timeout=2.0, ensure_started=False)
            return int(value) if value is not None else None
        except Exception:
            return self.engine._desired_output_device

    @property
    def output_locked(self) -> bool:
        if self._using_local_fallback:
            return self._fallback_player.output_locked
        try:
            return bool(self.engine.call("player.output_locked", timeout=2.0, ensure_started=False))
        except Exception:
            return self._fallback_player.output_locked

    @property
    def is_playing(self) -> bool:
        if self._using_local_fallback:
            return self._fallback_player.is_playing
        try:
            return bool(self.engine.call("player.is_playing", timeout=2.0, ensure_started=False))
        except Exception:
            return self._fallback_player.is_playing

    def health(self) -> dict:
        try:
            result = dict(self.engine.call("player.health", timeout=2.0, ensure_started=False))
        except Exception as exc:
            result = {"output_locked": False, "playing": False, "error": str(exc)}
        result["engine_alive"] = self.engine.process_alive
        result["local_fallback_active"] = self._using_local_fallback
        result["system_default_fallback"] = self._session_default_fallback
        result["fallback_reason"] = self._last_fallback_reason
        if self._using_local_fallback:
            result["local_fallback"] = self._fallback_player.health()
        return result

    def set_output_device(self, output_device: int | None) -> None:
        # An explicit user selection ends any session-only automatic fallback.
        self._session_default_fallback = False
        self._using_local_fallback = False
        self._last_fallback_reason = None
        self._fallback_player.set_output_device(output_device)
        self.engine.configure_output(output_device)
        self.engine.call("player.set_output_device", output_device, timeout=8.0)

    def lock_output(self, output_device: int | None = None) -> dict:
        selected = self.engine._desired_output_device if output_device is None else output_device
        self.engine.configure_output(selected, locked=True)
        try:
            return dict(self.engine.call("player.lock_output", selected, timeout=15.0))
        except AudioEngineUnavailable as first_error:
            recovery = self.engine.recover_devices(
                f"speaker lock failed: {first_error}", attempts=4
            )
            resolved = recovery.get("output_device")
            return dict(self.engine.call("player.lock_output", resolved, timeout=15.0))

    def stop(self) -> None:
        try:
            self.engine.call("player.stop", timeout=3.0, ensure_started=False)
        except Exception:
            pass
        try:
            self._fallback_player.stop()
        except Exception:
            pass

    def request_refresh(self) -> None:
        self._using_local_fallback = False
        self._session_default_fallback = False
        self._last_fallback_reason = None
        self._fallback_player.request_refresh()
        self.engine.configure_output(self.engine._desired_output_device, locked=False)
        self.engine.call("player.request_refresh", timeout=5.0)

    def _play_local_fallback(
        self,
        path: Path,
        volume: float,
        selected: int | None,
        *,
        allow_system_default: bool,
        cancel_check: Callable[[], bool] | None,
        reason: str,
    ) -> bool:
        candidates = [selected]
        if allow_system_default and selected is not None:
            candidates.append(None)
        last_error: Exception | None = None
        for candidate in candidates:
            try:
                self._fallback_player.set_output_device(candidate)
                played = self._fallback_player.play_file(
                    Path(path), volume, candidate, cancel_check=cancel_check
                )
                if played:
                    self._using_local_fallback = True
                    self._session_default_fallback = candidate is None and selected is not None
                    self._last_fallback_reason = reason
                    LOGGER.warning(
                        "Audio playback recovered through %s fallback after isolated Audio Engine failure: %s",
                        "Windows system default" if candidate is None else f"local device {candidate}",
                        reason,
                    )
                    return True
                return False
            except Exception as exc:
                last_error = exc
                LOGGER.warning(
                    "Local audio fallback failed on %s: %s",
                    "Windows system default" if candidate is None else f"device {candidate}",
                    exc,
                )
        raise AudioEngineUnavailable(
            f"Audio Engine playback failed ({reason}); local fallback also failed: {last_error}"
        )

    def play_file(
        self,
        path: Path,
        volume: float = 1.0,
        output_device: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> bool:
        explicit_device = output_device is not None
        selected = self.engine._desired_output_device if output_device is None else output_device

        # Once a stale saved endpoint has been proven unusable and the Windows
        # default successfully played, stay on that safe session fallback until
        # the user explicitly selects/refreshes a device. Do not persist the
        # automatic fallback; it is intentionally reversible.
        if self._session_default_fallback and not explicit_device:
            return self._play_local_fallback(
                Path(path),
                volume,
                None,
                allow_system_default=False,
                cancel_check=cancel_check,
                reason=self._last_fallback_reason or "previous speaker recovery",
            )

        self.engine.configure_output(selected, locked=True)
        last_error: AudioEngineUnavailable | None = None

        for attempt in range(2):
            current = self.engine._desired_output_device
            try:
                pending = self.engine.submit(
                    "player.play_file",
                    Path(path),
                    volume,
                    current,
                )
            except AudioEngineUnavailable as exc:
                last_error = exc
                if attempt == 0:
                    try:
                        self.engine.recover_devices(
                            f"speaker command could not start: {exc}", attempts=4
                        )
                        continue
                    except Exception as recovery_exc:
                        last_error = AudioEngineUnavailable(str(recovery_exc))
                break

            deadline = time.monotonic() + 600.0
            cancel_sent = False
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        self.stop()
                        with self.engine._pending_lock:
                            self.engine._pending.pop(pending.request_id, None)
                        message = "Audio playback timed out inside Audio Engine"
                        self.engine.restart(message)
                        raise AudioEngineUnavailable(message)
                    if cancel_check is not None and cancel_check() and not cancel_sent:
                        cancel_sent = True
                        self.stop()
                    try:
                        response = pending.response_queue.get(timeout=min(0.05, remaining))
                    except queue.Empty:
                        continue
                    with self.engine._pending_lock:
                        self.engine._pending.pop(pending.request_id, None)
                    if response.get("ok"):
                        self._using_local_fallback = False
                        self._last_fallback_reason = None
                        return bool(response.get("result"))
                    error = dict(response.get("error") or {})
                    raise AudioEngineUnavailable(
                        str(error.get("message") or "Audio playback failed")
                    )
            except AudioEngineUnavailable as first_error:
                with self.engine._pending_lock:
                    self.engine._pending.pop(pending.request_id, None)
                if cancel_sent or (cancel_check is not None and cancel_check()):
                    return False
                last_error = first_error
                if attempt == 0:
                    try:
                        self.engine.recover_devices(
                            f"speaker playback failed: {first_error}", attempts=4
                        )
                        continue
                    except Exception as recovery_exc:
                        last_error = AudioEngineUnavailable(str(recovery_exc))
                break

        reason = str(last_error or "isolated Audio Engine playback failed")
        return self._play_local_fallback(
            Path(path),
            volume,
            selected,
            allow_system_default=not explicit_device,
            cancel_check=cancel_check,
            reason=reason,
        )

    def close(self) -> None:
        try:
            self.engine.configure_output(self.engine._desired_output_device, locked=False)
            self.engine.call("player.close", timeout=5.0)
        except Exception:
            pass
        try:
            self._fallback_player.close()
        except Exception:
            pass
        self._using_local_fallback = False
