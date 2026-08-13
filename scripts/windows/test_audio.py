from __future__ import annotations

import math
import multiprocessing
import struct
import wave
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import ROOT_DIR, get_settings
from app.db import Database
from app.services.audio import HostAudioPlayer, HostAudioRecorder
from app.services.audio_engine import (
    AudioEngineSupervisor,
    AudioPlayerProxy,
    AudioRecorderProxy,
)


def create_tone(path: Path, frequency: float = 440.0, seconds: float = 0.8) -> None:
    sample_rate = 44100
    amplitude = 0.28
    frame_count = int(sample_rate * seconds)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        frames = bytearray()
        for index in range(frame_count):
            sample = int(32767 * amplitude * math.sin(2 * math.pi * frequency * index / sample_rate))
            frames.extend(struct.pack("<h", sample))
        output.writeframes(frames)


def main() -> None:
    tone = ROOT_DIR / "runtime_audio" / "speaker-test.wav"
    create_tone(tone)
    settings = get_settings()
    db = Database(settings)
    db.initialize()
    runtime = db.get_runtime_settings()
    output_device = runtime.get("output_device")
    output_fingerprint = runtime.get("output_device_fingerprint")

    engine: AudioEngineSupervisor | None = None
    if settings.audio_engine_process:
        engine = AudioEngineSupervisor(
            sample_rate=settings.sample_rate,
            startup_timeout=settings.audio_engine_startup_timeout_seconds,
            command_timeout=settings.audio_engine_command_timeout_seconds,
            watchdog_interval=settings.audio_engine_watchdog_seconds,
        )
        recorder = AudioRecorderProxy(engine, settings.sample_rate)
        player = AudioPlayerProxy(engine, output_device)
        engine.start()
        output_device = recorder.resolve_device_id(
            output_device,
            output_fingerprint,
            "output",
        )
        player.set_output_device(output_device)
        print(f"Audio Engine process {engine.pid} is active.")
    else:
        recorder = HostAudioRecorder(settings.sample_rate)
        output_device = recorder.resolve_device_id(
            output_device,
            output_fingerprint,
            "output",
        )
        player = HostAudioPlayer(output_device)
        print("Audio Engine isolation is disabled; testing in-process audio.")

    try:
        info = recorder.device_info(output_device, "output")
        if info:
            print(
                f"Playing a short test tone through {info['name']} "
                f"({info['hostapi']}, device {output_device})..."
            )
        else:
            print("Playing a short test tone through the Windows default speaker...")
        played = player.play_file(tone, volume=1.0)
        if not played:
            raise SystemExit("The test tone was cancelled or did not complete.")
        print("Playback completed.")
        if engine is not None:
            health = engine.health()
            print(
                "Audio Engine health: "
                f"alive={health['alive']}, restarts={health['restart_count']}, "
                f"state={health.get('remote', {}).get('coordinator_state', 'unknown')}"
            )
        print(
            "If you heard nothing, use Settings > Host audio to select and test "
            "the preferred output device."
        )
    finally:
        if engine is not None:
            engine.stop()
        else:
            player.close()
            recorder.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
