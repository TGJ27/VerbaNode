from __future__ import annotations

import sys
from types import SimpleNamespace

from app.services.audio import HostAudioRecorder
from app.services.audio_engine import (
    AudioEngineSupervisor,
    AudioEngineUnavailable,
    AudioPlayerProxy,
    AudioRecorderProxy,
)


def test_default_device_info_uses_profile_data_when_default_index_is_temporarily_missing(
    monkeypatch,
) -> None:
    device = {
        "name": "New Bluetooth microphone",
        "hostapi": 0,
        "max_input_channels": 1,
        "max_output_channels": 0,
        "default_samplerate": 48000,
    }
    fake_sd = SimpleNamespace(
        query_devices=lambda device_id=None, kind=None: device,
        query_hostapis=lambda index=None: {"name": "Windows WASAPI"},
        default=SimpleNamespace(device=(-1, -1)),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    info = HostAudioRecorder.device_info(None, "input")

    assert info is not None
    assert info["id"] is None
    assert info["name"] == "New Bluetooth microphone"
    assert info["default_samplerate"] == 48000.0


def test_portaudio_refresh_reinitializes_sounddevice(monkeypatch) -> None:
    calls: list[str] = []
    fake_sd = SimpleNamespace(
        _terminate=lambda: calls.append("terminate"),
        _initialize=lambda: calls.append("initialize"),
        query_devices=lambda: calls.append("query") or [],
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setattr("app.services.audio.time.sleep", lambda seconds: None)

    HostAudioRecorder.refresh_portaudio(settle_seconds=0.0)

    assert calls == ["terminate", "initialize", "query"]


def test_recorder_proxy_recovers_and_retries_failed_hotplug_lock(monkeypatch) -> None:
    engine = AudioEngineSupervisor(
        sample_rate=16000,
        startup_timeout=2.0,
        command_timeout=2.0,
        watchdog_interval=30.0,
    )
    calls: list[tuple[str, object]] = []

    def fake_call(operation, *args, **kwargs):
        calls.append((operation, args[0] if args else None))
        attempts = sum(1 for name, _ in calls if name == "recorder.lock_input")
        if operation == "recorder.lock_input" and attempts == 1:
            raise AudioEngineUnavailable("device not ready")
        if operation == "recorder.lock_input":
            return {"id": 7, "name": "Reconnected mic"}
        raise AssertionError(operation)

    def fake_recover(reason, attempts=3):
        engine._desired_input_device = 7
        calls.append(("recover", reason))
        return {"input_device": 7, "output_device": None}

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(engine, "recover_devices", fake_recover)
    recorder = AudioRecorderProxy(engine, 16000)

    info = recorder.lock_input(3)

    assert info["id"] == 7
    assert [name for name, _ in calls] == ["recorder.lock_input", "recover", "recorder.lock_input"]


def test_player_proxy_recovers_and_retries_failed_hotplug_lock(monkeypatch) -> None:
    engine = AudioEngineSupervisor(
        sample_rate=16000,
        startup_timeout=2.0,
        command_timeout=2.0,
        watchdog_interval=30.0,
    )
    calls: list[tuple[str, object]] = []

    def fake_call(operation, *args, **kwargs):
        calls.append((operation, args[0] if args else None))
        attempts = sum(1 for name, _ in calls if name == "player.lock_output")
        if operation == "player.lock_output" and attempts == 1:
            raise AudioEngineUnavailable("device not ready")
        if operation == "player.lock_output":
            return {"id": 9, "name": "Reconnected speaker"}
        raise AssertionError(operation)

    def fake_recover(reason, attempts=3):
        engine._desired_output_device = 9
        calls.append(("recover", reason))
        return {"input_device": None, "output_device": 9}

    monkeypatch.setattr(engine, "call", fake_call)
    monkeypatch.setattr(engine, "recover_devices", fake_recover)
    player = AudioPlayerProxy(engine, 4)

    info = player.lock_output(4)

    assert info["id"] == 9
    assert [name for name, _ in calls] == ["player.lock_output", "recover", "player.lock_output"]


def test_recovery_callback_can_persist_remapped_device_ids(monkeypatch) -> None:
    engine = AudioEngineSupervisor(
        sample_rate=16000,
        startup_timeout=2.0,
        command_timeout=2.0,
        watchdog_interval=30.0,
    )
    persisted: list[tuple[int | None, int | None]] = []
    engine.set_device_state_callback(lambda input_id, output_id: persisted.append((input_id, output_id)))
    engine._desired_input_device = 7
    engine._desired_output_device = 9
    engine._input_should_be_locked = False
    engine._output_should_be_locked = False

    monkeypatch.setattr(
        engine,
        "refresh_devices",
        lambda **kwargs: {"ok": True, "devices": [{"id": 7}, {"id": 9}]},
    )
    monkeypatch.setattr(engine, "_resolve_desired_devices", lambda: (7, 9))
    monkeypatch.setattr(engine, "call", lambda *args, **kwargs: None)

    result = engine.recover_devices("test remap", attempts=1)

    assert result["input_device"] == 7
    assert result["output_device"] == 9
    assert persisted == [(7, 9)]


def test_hotplug_waits_for_saved_fingerprint_not_just_any_device() -> None:
    engine = AudioEngineSupervisor(
        sample_rate=16000,
        startup_timeout=2.0,
        command_timeout=2.0,
        watchdog_interval=30.0,
    )
    engine.configure_input(
        12,
        fingerprint={
            "name": "USB Conference Mic",
            "hostapi": "Windows WASAPI",
            "direction": "input",
            "channels": 1,
        },
        locked=True,
    )
    built_in_only = [
        {
            "id": 1,
            "name": "Microphone Array",
            "hostapi": "Windows WASAPI",
            "max_input_channels": 2,
            "max_output_channels": 0,
        }
    ]
    with_target = built_in_only + [
        {
            "id": 18,
            "name": "USB Conference Mic",
            "hostapi": "Windows WASAPI",
            "max_input_channels": 1,
            "max_output_channels": 0,
        }
    ]

    assert engine._desired_targets_available(built_in_only) is False
    assert engine._desired_targets_available(with_target) is True
