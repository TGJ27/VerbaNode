from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from app.config import Settings
from app.services.ai_engine import (
    AiEngineSupervisor,
    AiEngineUnavailable,
    AiKokoroProxy,
    AiSttProxy,
)


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "test.db",
        kokoro_dir=tmp_path / "kokoro",
        tts_cache_path=tmp_path / "cache",
        ai_engine_process=True,
        ai_engine_preload_asr=False,
        ai_engine_preload_kokoro=False,
        ai_engine_watchdog_seconds=30.0,
    )


def make_engine(tmp_path: Path) -> AiEngineSupervisor:
    settings = make_settings(tmp_path)
    return AiEngineSupervisor(
        settings,
        startup_timeout=8.0,
        command_timeout=5.0,
        watchdog_interval=30.0,
        asr_queue_size=2,
        kokoro_queue_size=4,
        preload_asr=False,
        preload_kokoro=False,
    )


def test_ai_engine_process_lifecycle(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        engine.start()
        ping = engine.call("engine.ping", timeout=3.0)
        assert ping["ok"] is True
        assert ping["pid"] == engine.pid
        health = engine.health()
        assert health["mode"] == "isolated_process"
        assert health["alive"] is True
        assert health["remote"]["coordinator_state"] in {"idle", "loading"}
    finally:
        engine.stop()
    assert engine.process_alive is False


def test_ai_engine_explicit_restart_recovers(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        engine.start()
        first_pid = engine.pid
        engine.restart("test restart")
        assert engine.pid is not None
        assert engine.pid != first_pid
        assert engine.call("engine.ping", timeout=3.0)["ok"] is True
        assert engine.health()["restart_count"] == 1
    finally:
        engine.stop()


def test_ai_engine_translates_worker_errors(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    try:
        engine.start()
        with pytest.raises(AiEngineUnavailable, match="Unknown AI-engine operation"):
            engine.call("not.a.real.operation", timeout=3.0)
    finally:
        engine.stop()


def test_ai_engine_queue_limits_are_bounded(tmp_path: Path) -> None:
    engine = make_engine(tmp_path)
    engine._inflight_asr = engine.asr_queue_size
    with pytest.raises(AiEngineUnavailable, match="ASR queue is full"):
        engine._reserve_slot("asr.transcribe")
    engine._inflight_kokoro = engine.kokoro_queue_size
    with pytest.raises(AiEngineUnavailable, match="Kokoro queue is full"):
        engine._reserve_slot("kokoro.generate")


def test_ai_stt_proxy_reconstructs_transcription(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)

    class FakeEngine:
        def call(self, operation, *args, **kwargs):
            assert operation == "asr.transcribe"
            assert isinstance(args[0], np.ndarray)
            return {
                "text": "hello",
                "confidence": 0.91,
                "confidence_source": "estimated",
            }

        def health(self):
            return {
                "alive": True,
                "pid": 123,
                "remote": {"asr": {"state": "ready", "loaded": True, "model": "test"}},
            }

    proxy = AiSttProxy(FakeEngine(), settings)
    result = proxy.transcribe_with_confidence(np.ones(1600, dtype=np.float32))
    assert result.text == "hello"
    assert result.confidence == pytest.approx(0.91)
    assert proxy.status()["loaded"] is True


def test_ai_kokoro_proxy_returns_shared_audio_path(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    output = tmp_path / "generated.wav"
    output.write_bytes(b"RIFF-test")

    class FakeEngine:
        def call(self, operation, *args, **kwargs):
            assert operation == "kokoro.generate"
            return {"path": str(output), "latency_ms": 12}

        def health(self):
            return {
                "alive": True,
                "pid": 456,
                "remote": {"kokoro": {"state": "ready", "loaded": True}},
            }

    proxy = AiKokoroProxy(FakeEngine(), settings)
    assert proxy.generate("hello", 0, 1.0) == output
    assert proxy.status()["loaded"] is True
