from __future__ import annotations

import io
import wave

import numpy as np

from app.services.audio import decode_pcm_wav


def make_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buffer.getvalue()


def test_browser_pcm_wav_is_resampled_to_16khz() -> None:
    source_rate = 48000
    timeline = np.linspace(0, 1.0, source_rate, endpoint=False)
    payload = make_wav((0.25 * np.sin(2 * np.pi * 440 * timeline)).astype(np.float32), source_rate)
    decoded = decode_pcm_wav(payload, 16000)
    assert decoded.dtype == np.float32
    assert 15990 <= decoded.size <= 16010
    assert float(np.max(np.abs(decoded))) > 0.20


def test_empty_browser_wav_payload_returns_empty_audio() -> None:
    decoded = decode_pcm_wav(b"", 16000)
    assert decoded.size == 0
