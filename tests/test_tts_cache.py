from pathlib import Path

from app.config import Settings
from app.services.tts import TtsService


class FakePlayer:
    is_playing = False

    def __init__(self):
        self.played = []

    def stop(self):
        return None

    def play_file(self, path: Path, volume=1.0, output_device_name=None, cancel_check=None):
        self.played.append(path)
        return not (cancel_check and cancel_check())


def test_script_audio_is_reused_when_text_and_voice_match(tmp_path: Path):
    settings = Settings(db_path=tmp_path / "test.db", tts_cache_path=tmp_path / "cache", open_browser=False)
    service = TtsService(settings, FakePlayer())
    calls = []

    def fake_edge_generate(text, voice, rate):
        calls.append((text, voice, rate))
        path = settings.runtime_audio_dir / f"generated-{len(calls)}.mp3"
        path.write_bytes(b"audio")
        return path

    service.edge.generate = fake_edge_generate
    agent = {
        "tts_mode": "edge",
        "edge_voice": "en-US-AriaNeural",
        "tts_rate": 1.0,
        "tts_volume": 1.0,
    }

    first_id = service.begin_speech()
    first = service.generate_audio_blocking(
        "Welcome to Sari Technology.", agent, first_id, use_cache=True
    )
    assert first is not None
    assert first.cached is False
    assert first.persistent is True
    assert first.path.exists()
    service.play_generated_blocking(first, agent, first_id)
    assert first.path.exists()

    second_id = service.begin_speech()
    second = service.generate_audio_blocking(
        "Welcome to Sari Technology.", agent, second_id, use_cache=True
    )
    assert second is not None
    assert second.cached is True
    assert second.path == first.path
    assert len(calls) == 1


def test_script_cache_changes_when_voice_changes(tmp_path: Path):
    settings = Settings(db_path=tmp_path / "test.db", tts_cache_path=tmp_path / "cache", open_browser=False)
    service = TtsService(settings, FakePlayer())
    calls = []

    def fake_edge_generate(text, voice, rate):
        calls.append(voice)
        path = settings.runtime_audio_dir / f"generated-{len(calls)}.mp3"
        path.write_bytes(b"audio")
        return path

    service.edge.generate = fake_edge_generate
    first_agent = {"tts_mode": "edge", "edge_voice": "en-US-AriaNeural", "tts_rate": 1.0}
    second_agent = {"tts_mode": "edge", "edge_voice": "en-US-JennyNeural", "tts_rate": 1.0}
    first = service.generate_audio_blocking("Same text", first_agent, service.begin_speech(), use_cache=True)
    second = service.generate_audio_blocking("Same text", second_agent, service.begin_speech(), use_cache=True)
    assert first and second
    assert first.path != second.path
    assert calls == ["en-US-AriaNeural", "en-US-JennyNeural"]
