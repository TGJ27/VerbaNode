from __future__ import annotations

from pathlib import Path

import pytest

from app.services.audio_engine import AudioEngineUnavailable, AudioPlayerProxy


class _DeadEngine:
    def __init__(self, output_device: int | None = 7) -> None:
        self._desired_output_device = output_device
        self._desired_output_fingerprint = None
        self._output_should_be_locked = False
        self.process_alive = False

    def configure_output(self, device, *, fingerprint=None, locked=None):
        self._desired_output_device = device
        if fingerprint is not None:
            self._desired_output_fingerprint = fingerprint
        if locked is not None:
            self._output_should_be_locked = bool(locked)

    def submit(self, *args, **kwargs):
        raise AudioEngineUnavailable("isolated engine unavailable")

    def recover_devices(self, *args, **kwargs):
        raise AudioEngineUnavailable("device recovery unavailable")

    def call(self, *args, **kwargs):
        raise AudioEngineUnavailable("isolated engine unavailable")


class _FallbackPlayer:
    def __init__(self) -> None:
        self.configured = 7
        self.calls: list[int | None] = []
        self.output_locked = False
        self.is_playing = False

    def set_output_device(self, device):
        self.configured = device

    def play_file(self, path, volume=1.0, output_device=None, cancel_check=None):
        self.calls.append(output_device)
        if output_device == 7:
            raise RuntimeError("saved endpoint cannot open")
        return True

    def stop(self):
        return None

    def close(self):
        return None

    def request_refresh(self):
        return None

    def health(self):
        return {"configured_output_device": self.configured}


def _proxy() -> AudioPlayerProxy:
    proxy = AudioPlayerProxy(_DeadEngine(7), 7)
    proxy._fallback_player = _FallbackPlayer()
    return proxy


def test_shared_playback_falls_back_to_windows_default_after_saved_endpoint_fails(tmp_path: Path) -> None:
    proxy = _proxy()
    path = tmp_path / "tone.wav"
    path.write_bytes(b"not-decoded-by-fake")

    assert proxy.play_file(path) is True
    assert proxy._fallback_player.calls == [7, None]
    assert proxy.health()["local_fallback_active"] is True
    assert proxy.health()["system_default_fallback"] is True

    # Once the session proves the saved endpoint is stale, subsequent shared
    # TTS/Script/Audio-Library playback skips it until the user reselects a device.
    assert proxy.play_file(path) is True
    assert proxy._fallback_player.calls == [7, None, None]


def test_explicit_speaker_test_never_silently_uses_a_different_device(tmp_path: Path) -> None:
    proxy = _proxy()
    path = tmp_path / "tone.wav"
    path.write_bytes(b"not-decoded-by-fake")

    with pytest.raises(AudioEngineUnavailable, match="local fallback also failed"):
        proxy.play_file(path, output_device=7)
    assert proxy._fallback_player.calls == [7]
