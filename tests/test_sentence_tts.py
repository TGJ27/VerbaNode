import asyncio
from pathlib import Path

from app.services.sentence_tts import SentenceChunker, StreamingTtsSession
from app.services.tts import GeneratedSpeech


class FakeEvents:
    def __init__(self):
        self.events = []

    async def broadcast(self, name, payload):
        self.events.append((name, payload))


class FakeTts:
    def __init__(self, tmp_path: Path):
        self.tmp_path = tmp_path
        self.spoken = []
        self.generated = []
        self.stop_calls = 0
        self.speech_id = 0

    def begin_speech(self):
        self.speech_id += 1
        return self.speech_id

    def stop_current(self):
        self.stop_calls += 1

    def generate_audio_blocking(self, text, agent, speech_id):
        self.generated.append(text)
        path = self.tmp_path / f"{len(self.generated)}.wav"
        path.write_bytes(b"wave")
        return GeneratedSpeech(path=path, provider="fake", text=text)

    def play_generated_blocking(self, generated, agent, speech_id):
        self.spoken.append(generated.text)
        self.cleanup_generated(generated)
        return True

    @staticmethod
    def cleanup_generated(generated):
        if generated and not generated.persistent:
            generated.path.unlink(missing_ok=True)


def test_sentence_chunker_streams_sentences_and_protects_decimals():
    chunker = SentenceChunker()
    assert chunker.feed("The value is 3.") == []
    assert chunker.feed("14. This is correct. ") == ["The value is 3.14.", "This is correct."]
    assert chunker.feed("Ask Dr. Smith for help. ") == ["Ask Dr. Smith for help."]


def test_streaming_tts_plays_chunks_in_order(tmp_path: Path):
    async def run():
        tts = FakeTts(tmp_path)
        events = FakeEvents()
        session = StreamingTtsSession(tts=tts, events=events, agent={})
        await session.feed("First sentence. Second ")
        await session.feed("sentence! ")
        await session.wait_finished()
        return tts, events

    tts, events = asyncio.run(run())
    assert tts.generated == ["First sentence.", "Second sentence!"]
    assert tts.spoken == ["First sentence.", "Second sentence!"]
    assert [name for name, _ in events.events].count("tts_started") == 1
    assert [name for name, _ in events.events].count("tts_chunk") == 2
    assert [name for name, _ in events.events].count("tts_stopped") == 1


def test_first_sentence_starts_before_llm_stream_closes(tmp_path: Path):
    async def run():
        tts = FakeTts(tmp_path)
        session = StreamingTtsSession(tts=tts, events=FakeEvents(), agent={})
        await session.feed("Speak this first. The second sentence is not complete")
        for _ in range(50):
            if tts.spoken:
                break
            await asyncio.sleep(0.01)
        assert tts.spoken == ["Speak this first."]
        await session.feed(" yet. ")
        await session.wait_finished()
        return tts

    tts = asyncio.run(run())
    assert tts.spoken == ["Speak this first.", "The second sentence is not complete yet."]


def test_stop_before_first_sentence_prevents_later_playback(tmp_path: Path):
    async def run():
        tts = FakeTts(tmp_path)
        session = StreamingTtsSession(tts=tts, events=FakeEvents(), agent={})
        await session.feed("unfinished")
        await session.cancel()
        await session.feed(" sentence. ")
        await session.wait_finished()
        return tts

    tts = asyncio.run(run())
    assert tts.spoken == []
    assert tts.stop_calls >= 1
