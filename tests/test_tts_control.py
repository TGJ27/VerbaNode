from pathlib import Path

from app.config import Settings
from app.services.tts import TtsService


class FakePlayer:
    def __init__(self) -> None:
        self.is_playing = False
        self.stop_calls = 0
        self.refresh_calls = 0
        self.play_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1

    def request_refresh(self) -> None:
        self.refresh_calls += 1

    def play_file(self, path: Path, volume: float = 1.0, output_device=None, cancel_check=None) -> bool:
        self.play_calls += 1
        return not (cancel_check and cancel_check())


def test_stop_current_cancels_pending_speech(tmp_path: Path) -> None:
    player = FakePlayer()
    service = TtsService(Settings(db_path=tmp_path / "test.db", open_browser=False), player)
    speech_id = service.begin_speech()
    assert player.stop_calls == 1
    assert player.refresh_calls == 0
    service.stop_current()
    result = service.speak_blocking("This must not play", {"tts_mode": "edge"}, speech_id)
    assert result is False
    assert player.play_calls == 0
