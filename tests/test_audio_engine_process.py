from __future__ import annotations

import queue
import threading
import time

import pytest

from app.services.audio_engine import (
    AudioEngineSupervisor,
    AudioEngineUnavailable,
    AudioPlayerProxy,
    AudioRecorderProxy,
    _PendingCall,
)


def make_engine() -> AudioEngineSupervisor:
    return AudioEngineSupervisor(
        sample_rate=16000,
        startup_timeout=8.0,
        command_timeout=5.0,
        watchdog_interval=30.0,
    )


def test_audio_engine_process_lifecycle() -> None:
    engine = make_engine()
    try:
        engine.start()
        result = engine.call("engine.ping", timeout=3.0)
        assert result["ok"] is True
        assert result["pid"] == engine.pid
        health = engine.health()
        assert health["mode"] == "isolated_process"
        assert health["alive"] is True
    finally:
        engine.stop()
    assert engine.process_alive is False


def test_audio_engine_proxies_report_remote_health() -> None:
    engine = make_engine()
    recorder = AudioRecorderProxy(engine, 16000)
    player = AudioPlayerProxy(engine, None)
    try:
        engine.start()
        assert recorder.health()["engine_alive"] is True
        assert player.health()["engine_alive"] is True
        assert isinstance(recorder.list_devices(), list)
    finally:
        engine.stop()


def test_audio_engine_explicit_restart_recovers() -> None:
    engine = make_engine()
    try:
        engine.start()
        first_pid = engine.pid
        engine.restart("test restart")
        assert engine.process_alive is True
        assert engine.pid is not None
        assert engine.pid != first_pid
        assert engine.call("engine.ping", timeout=3.0)["ok"] is True
        assert engine.health()["restart_count"] == 1
    finally:
        engine.stop()


def test_audio_engine_translates_worker_errors() -> None:
    engine = make_engine()
    try:
        engine.start()
        with pytest.raises(AudioEngineUnavailable, match="Unknown audio-engine operation"):
            engine.call("not.a.real.operation", timeout=3.0)
    finally:
        engine.stop()


def test_audio_engine_event_callback_can_issue_a_command() -> None:
    engine = make_engine()
    callback_finished = threading.Event()
    result: dict[str, object] = {}

    def callback(event: str, data: dict[str, object]) -> None:
        result["event"] = event
        result["ping"] = engine.call("engine.ping", timeout=3.0)
        callback_finished.set()

    try:
        engine.start()
        request_id = "synthetic-event-callback"
        pending = _PendingCall(
            request_id=request_id,
            operation="test.synthetic",
            response_queue=queue.Queue(maxsize=1),
            event_callback=callback,
        )
        with engine._pending_lock:
            engine._pending[request_id] = pending
        engine._result_queue.put(
            {
                "kind": "event",
                "request_id": request_id,
                "event": "speech_started",
                "data": {},
            }
        )
        assert callback_finished.wait(4.0)
        assert result["event"] == "speech_started"
        assert result["ping"]["ok"] is True
    finally:
        with engine._pending_lock:
            engine._pending.pop("synthetic-event-callback", None)
        engine.stop()
