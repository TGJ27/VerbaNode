from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

from app.migrations import CURRENT_SCHEMA_VERSION, apply_migrations
from app.schemas import TypeToTalkCreate


class _FailingStopper:
    async def stop(self) -> None:
        raise RuntimeError("stale playback subsystem")


class _FailingIdleConversation:
    _ptt_active = False
    _browser_ptt_active = False

    @property
    def is_conversation_running(self) -> bool:
        return False

    async def stop_current_tts(self) -> None:
        raise RuntimeError("audio engine restarting")


class _AcceptingTypeToTalk:
    state = "idle"

    def __init__(self) -> None:
        self.added: list[str] = []

    async def add(self, text: str) -> dict[str, object]:
        self.added.append(text)
        return {"id": 7, "text": text, "status": "waiting"}


def test_direct_speech_accepts_text_when_all_competing_cleanup_fails(monkeypatch) -> None:
    import app.api.type_to_talk as api

    manager = _AcceptingTypeToTalk()
    fake_state = SimpleNamespace(
        db=SimpleNamespace(),
        conversation=_FailingIdleConversation(),
        script_queue=_FailingStopper(),
        audio_library=_FailingStopper(),
        type_to_talk=manager,
    )
    monkeypatch.setattr(api, "state", fake_state)
    monkeypatch.setattr(api, "get_type_to_talk_settings", lambda _db: {})
    monkeypatch.setattr(api, "save_type_to_talk_settings", lambda _db, values: values)

    result = asyncio.run(api.add_type_to_talk(TypeToTalkCreate(text="still speak"), "token"))

    assert result["text"] == "still speak"
    assert manager.added == ["still speak"]


def test_v8_migration_repairs_missing_type_to_talk_table() -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)")
    conn.execute("INSERT INTO settings VALUES('schema_version','7','now')")
    conn.execute("PRAGMA user_version=7")

    version = apply_migrations(conn)

    assert version == CURRENT_SCHEMA_VERSION == 12
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "type_to_talk_queue" in tables
    indexes = {row[1] for row in conn.execute("PRAGMA index_list(type_to_talk_queue)")}
    assert "idx_type_to_talk_queue_position" in indexes
