from __future__ import annotations

import sys
from types import SimpleNamespace

from app.services.audio import HostAudioPlayer


class FakeOutputStream:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.active = False
        self.closed = False
        self.__class__.instances.append(self)

    def start(self):
        self.active = True

    def stop(self):
        self.active = False

    def abort(self):
        self.active = False

    def close(self):
        self.active = False
        self.closed = True


def test_selected_output_is_pinned_and_persistent_stream_is_reused(monkeypatch) -> None:
    FakeOutputStream.instances.clear()
    devices = {
        16: {
            "name": "Headphones (JYX-N882)",
            "max_input_channels": 0,
            "max_output_channels": 2,
            "default_samplerate": 48000,
            "hostapi": 0,
        },
        14: {
            "name": "Speakers (Realtek Audio)",
            "max_input_channels": 0,
            "max_output_channels": 2,
            "default_samplerate": 48000,
            "hostapi": 0,
        },
    }
    fake_sd = SimpleNamespace(
        query_devices=lambda device_id=None, kind=None: devices[int(device_id)],
        query_hostapis=lambda index: {"name": "Windows WASAPI"},
        OutputStream=FakeOutputStream,
        default=SimpleNamespace(device=(1, 16)),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    player = HostAudioPlayer(16)
    player.lock_output()
    player.lock_output()

    assert len(FakeOutputStream.instances) == 1
    assert FakeOutputStream.instances[0].kwargs["device"] == 16
    assert player.output_locked is True

    player.set_output_device(14)
    player.lock_output()

    assert len(FakeOutputStream.instances) == 2
    assert FakeOutputStream.instances[0].closed is True
    assert FakeOutputStream.instances[1].kwargs["device"] == 14
