import asyncio
from types import SimpleNamespace

import numpy as np

from app.config import Settings
from app.db import Database
from app.services.conversation import ConversationManager
from app.services.stt import FunASRService, TranscriptionResult


def test_estimated_confidence_is_higher_for_clear_speech_like_audio() -> None:
    sample_rate = 16000
    t = np.arange(sample_rate, dtype=np.float32) / sample_rate
    clear = (0.08 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    quiet = (0.0005 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)

    clear_score = FunASRService._estimated_confidence(clear, "What is the weather today?")
    quiet_score = FunASRService._estimated_confidence(quiet, "What is the weather today?")

    assert 0.0 <= quiet_score < clear_score <= 1.0


def test_provider_confidence_is_used_when_present() -> None:
    assert FunASRService._provider_confidence({"confidence": 0.82}) == 0.82
    assert FunASRService._provider_confidence({"score": -0.1}) is not None
    assert FunASRService._provider_confidence({"timestamp": [100, 200]}) is None


def test_low_confidence_transcript_is_shown_but_not_processed() -> None:
    manager = object.__new__(ConversationManager)
    manager.settings = SimpleNamespace(funasr_model="iic/SenseVoiceSmall")
    manager.active_agent = lambda: {"stt_model": "iic/SenseVoiceSmall"}

    class FakeStt:
        @staticmethod
        def transcribe_with_confidence(samples, model_name):
            return TranscriptionResult("possibly incorrect words", 0.42, "estimated")

    class FakeDb:
        @staticmethod
        def get_runtime_settings():
            return {
                "stt_confidence_filter_enabled": True,
                "stt_confidence_threshold": 0.60,
            }

    class FakeEvents:
        def __init__(self):
            self.items = []

        async def broadcast(self, event, data):
            self.items.append((event, data))

    async def must_not_process(**kwargs):
        raise AssertionError("Low-confidence transcript must not reach the LLM")

    manager.stt = FakeStt()
    manager.db = FakeDb()
    manager.events = FakeEvents()
    manager.process_user_text = must_not_process

    result = asyncio.run(
        manager._handle_audio(
            np.ones(1600, dtype=np.float32) * 0.05,
            source="ptt",
            allow_barge_in=False,
        )
    )

    transcript_events = [data for event, data in manager.events.items if event == "transcript"]
    assert result["rejected"] is True
    assert transcript_events[0]["accepted"] is False
    assert transcript_events[0]["confidence_percent"] == 42
    assert transcript_events[0]["threshold_percent"] == 60


def test_accepted_stt_confidence_is_saved_with_message(tmp_path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", open_browser=False)
    db = Database(settings)
    db.initialize()
    agent = db.list_agents()[0]
    conversation = db.latest_conversation(agent["id"])

    message = db.add_message(
        conversation["id"],
        "user",
        "Hello there",
        "ptt",
        stt_confidence=0.87,
        stt_confidence_source="estimated",
    )

    assert message["stt_confidence"] == 0.87
    assert message["stt_confidence_source"] == "estimated"
    runtime = db.get_runtime_settings()
    assert runtime["stt_confidence_filter_enabled"] is True
    assert runtime["stt_confidence_threshold"] == 0.70
