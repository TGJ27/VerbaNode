from __future__ import annotations

import sys
from types import SimpleNamespace

from app.services.audio import HostAudioRecorder


class FakeInputStream:
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


def test_microphone_uses_native_rate_and_stream_is_reused(monkeypatch):
    FakeInputStream.instances.clear()
    device = {
        "name": "Headset (DJI Mic Mini Hands-Free)",
        "max_input_channels": 1,
        "max_output_channels": 0,
        "default_samplerate": 48000,
        "hostapi": 0,
    }
    fake_sd = SimpleNamespace(
        query_devices=lambda device_id=None, kind=None: device,
        query_hostapis=lambda index: {"name": "Windows WASAPI"},
        InputStream=FakeInputStream,
        default=SimpleNamespace(device=(20, 16)),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)

    recorder = HostAudioRecorder(16000)
    recorder.lock_input(20)
    recorder.lock_input(20)

    assert len(FakeInputStream.instances) == 1
    stream = FakeInputStream.instances[0]
    assert stream.kwargs["samplerate"] == 48000
    assert stream.kwargs["blocksize"] == 1536
    assert recorder.input_locked is True

    recorder.unlock_input()
    assert stream.closed is True
