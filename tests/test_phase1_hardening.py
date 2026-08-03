from __future__ import annotations

import json
import time

from app.services.audio import HostAudioRecorder
from app.services.pipeline import PipelineMonitor
from app.services.sentence_tts import SentenceChunker


def test_device_fingerprint_recovers_after_portaudio_id_reorder(monkeypatch) -> None:
    devices = [
        {
            "id": 4,
            "name": "DJI Mic",
            "hostapi": "Windows WASAPI",
            "max_input_channels": 1,
            "max_output_channels": 0,
        },
        {
            "id": 9,
            "name": "Headphones (JYX-N882)",
            "hostapi": "Windows WASAPI",
            "max_input_channels": 0,
            "max_output_channels": 2,
        },
    ]
    monkeypatch.setattr(HostAudioRecorder, "list_devices", staticmethod(lambda: devices))
    fingerprint = json.dumps({
        "name": "DJI Mic",
        "hostapi": "Windows WASAPI",
        "direction": "input",
        "channels": 1,
    })

    assert HostAudioRecorder.resolve_device_id(2, fingerprint, "input") == 4


def test_device_resolution_preserves_saved_id_when_enumeration_temporarily_fails(monkeypatch) -> None:
    monkeypatch.setattr(HostAudioRecorder, "list_devices", staticmethod(lambda: []))
    assert HostAudioRecorder.resolve_device_id(16, None, "output") == 16


def test_first_clause_can_be_emitted_before_sentence_finishes() -> None:
    chunker = SentenceChunker(first_clause_min_chars=20, first_clause_max_chars=80)
    chunks = chunker.feed("Certainly, I can help you with that, and then explain the next step")
    assert chunks == ["Certainly, I can help you with that,"]
    assert chunker.flush() == ["and then explain the next step"]


def test_pipeline_monitor_tracks_turn_ids_latency_and_completion() -> None:
    monitor = PipelineMonitor()
    turn = monitor.begin_turn("ptt", audio=True)
    monitor.transition("transcribing")
    monitor.mark("stt_started")
    time.sleep(0.002)
    assert monitor.duration("stt_total", "stt_started") is not None
    monitor.finish_turn()
    snapshot = monitor.snapshot()

    assert turn.capture_id
    assert snapshot["turn_id"] is None
    assert snapshot["counters"]["turns_started"] == 1
    assert snapshot["counters"]["turns_completed"] == 1
    assert snapshot["latency_ms"]["stt_total"] >= 0
