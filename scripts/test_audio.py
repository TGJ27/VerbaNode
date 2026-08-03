from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

from app.config import ROOT_DIR, get_settings
from app.db import Database
from app.services.audio import HostAudioPlayer, HostAudioRecorder


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
    output_device = db.get_runtime_settings().get("output_device")
    info = HostAudioRecorder.device_info(output_device)
    player = HostAudioPlayer(output_device)
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
    print("Playback completed. If you heard nothing, use Settings > Host audio to select and test the JYX output.")


if __name__ == "__main__":
    main()
