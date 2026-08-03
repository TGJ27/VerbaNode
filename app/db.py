from __future__ import annotations

import json
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import Settings
from app.defaults import (
    ROPI_CONTEXT_SIZE,
    ROPI_GREETING,
    ROPI_LLM_MODEL,
    ROPI_MAX_TOKENS,
    ROPI_ROLE,
    ROPI_SYSTEM_PROMPT,
    ROPI_TEMPERATURE,
    ROPI_TOP_P,
)
from app.services.kokoro_voices import voice_name


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path = Path(settings.db_path)
        self._write_lock = threading.RLock()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            color TEXT NOT NULL DEFAULT '#6c63ff',
            avatar TEXT NOT NULL DEFAULT 'VA',
            role TEXT NOT NULL,
            system_prompt TEXT NOT NULL,
            greeting TEXT NOT NULL,
            llm_model TEXT NOT NULL,
            temperature REAL NOT NULL DEFAULT 0.4,
            top_p REAL NOT NULL DEFAULT 0.9,
            max_tokens INTEGER NOT NULL DEFAULT 224,
            context_size INTEGER NOT NULL DEFAULT 4096,
            tts_mode TEXT NOT NULL DEFAULT 'edge_fallback',
            edge_voice TEXT NOT NULL DEFAULT 'en-US-AriaNeural',
            kokoro_voice_id INTEGER NOT NULL DEFAULT 0,
            tts_rate REAL NOT NULL DEFAULT 1.0,
            tts_volume REAL NOT NULL DEFAULT 1.0,
            stt_model TEXT NOT NULL DEFAULT 'iic/SenseVoiceSmall',
            tools_enabled TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS information (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_information (
            agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            info_id INTEGER NOT NULL REFERENCES information(id) ON DELETE CASCADE,
            PRIMARY KEY(agent_id, info_id)
        );

        CREATE TABLE IF NOT EXISTS scripts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            text TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS script_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'waiting',
            added_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'chat',
            stt_confidence REAL,
            stt_confidence_source TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);
        CREATE INDEX IF NOT EXISTS idx_conversations_agent ON conversations(agent_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            conversation_id INTEGER REFERENCES conversations(id) ON DELETE CASCADE,
            content TEXT NOT NULL,
            through_message_id INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(agent_id, conversation_id)
        );
        """
        with self._write_lock, self.connect() as conn:
            conn.executescript(schema)
            message_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(messages)").fetchall()
            }
            if "stt_confidence" not in message_columns:
                conn.execute("ALTER TABLE messages ADD COLUMN stt_confidence REAL")
            if "stt_confidence_source" not in message_columns:
                conn.execute("ALTER TABLE messages ADD COLUMN stt_confidence_source TEXT")
            agent_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(agents)").fetchall()
            }
            if "max_tokens" not in agent_columns:
                conn.execute(
                    "ALTER TABLE agents ADD COLUMN max_tokens INTEGER NOT NULL DEFAULT 224"
                )
        self._seed()

    def _seed(self) -> None:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("active_agent_id", "1", now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("interruption_enabled", "false", now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("silence_ms", str(self.settings.silence_ms), now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("max_record_seconds", str(self.settings.max_record_seconds), now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("stt_confidence_filter_enabled", "true", now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("stt_confidence_threshold", "0.88", now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("audio_safety_version", "0", now),
            )
            safety_version_row = conn.execute(
                "SELECT value FROM settings WHERE key='audio_safety_version'"
            ).fetchone()
            try:
                safety_version = int(safety_version_row[0]) if safety_version_row else 0
            except (TypeError, ValueError):
                safety_version = 0
            if safety_version < 1:
                # Older builds enabled full-duplex barge-in by default. On PCs
                # using speakers, the microphone hears TTS and falsely stops it.
                # Migrate once to safe half-duplex; users may explicitly re-enable
                # experimental barge-in from Settings when using a headset.
                conn.execute(
                    "UPDATE settings SET value='false', updated_at=? WHERE key='interruption_enabled'",
                    (now,),
                )
                conn.execute(
                    "UPDATE settings SET value='1', updated_at=? WHERE key='audio_safety_version'",
                    (now,),
                )
            count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            if count == 0:
                conn.execute(
                    """
                    INSERT INTO agents(
                        name,color,avatar,role,system_prompt,greeting,llm_model,
                        temperature,top_p,max_tokens,context_size,tts_mode,edge_voice,
                        kokoro_voice_id,tts_rate,tts_volume,stt_model,tools_enabled,
                        created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        "Ropi",
                        "#6c63ff",
                        "RP",
                        ROPI_ROLE,
                        ROPI_SYSTEM_PROMPT,
                        ROPI_GREETING,
                        ROPI_LLM_MODEL,
                        ROPI_TEMPERATURE,
                        ROPI_TOP_P,
                        ROPI_MAX_TOKENS,
                        ROPI_CONTEXT_SIZE,
                        "edge_fallback",
                        "en-US-AriaNeural",
                        0,
                        1.0,
                        1.0,
                        self.settings.funasr_model,
                        json.dumps([
                            "get_current_time",
                            "get_location",
                            "get_weather",
                            "handle_exit_intent",
                        ]),
                        now,
                        now,
                    ),
                )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("ropi_defaults_version", "0", now),
            )
            ropi_version_row = conn.execute(
                "SELECT value FROM settings WHERE key='ropi_defaults_version'"
            ).fetchone()
            try:
                ropi_version = int(ropi_version_row[0]) if ropi_version_row else 0
            except (TypeError, ValueError):
                ropi_version = 0
            if ropi_version < 2:
                # Apply the requested Ropi defaults to new and existing databases.
                # Preserve voice, greeting, information, tools, chats, and memory.
                conn.execute(
                    """
                    UPDATE agents
                    SET role=?, system_prompt=?, llm_model=?, temperature=?, top_p=?,
                        max_tokens=?, context_size=?, updated_at=?
                    WHERE lower(trim(name))='ropi'
                    """,
                    (
                        ROPI_ROLE,
                        ROPI_SYSTEM_PROMPT,
                        ROPI_LLM_MODEL,
                        ROPI_TEMPERATURE,
                        ROPI_TOP_P,
                        ROPI_MAX_TOKENS,
                        ROPI_CONTEXT_SIZE,
                        now,
                    ),
                )
                conn.execute(
                    "UPDATE settings SET value='0.88', updated_at=? WHERE key='stt_confidence_threshold'",
                    (now,),
                )
                conn.execute(
                    "UPDATE settings SET value='2', updated_at=? WHERE key='ropi_defaults_version'",
                    (now,),
                )
            agent_id = conn.execute("SELECT id FROM agents ORDER BY id LIMIT 1").fetchone()[0]
            conn.execute(
                "UPDATE settings SET value=?, updated_at=? WHERE key='active_agent_id'",
                (str(agent_id), now),
            )
            conv_count = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE agent_id=?", (agent_id,)
            ).fetchone()[0]
            if conv_count == 0:
                conn.execute(
                    "INSERT INTO conversations(agent_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                    (agent_id, "New conversation", now, now),
                )
            script_count = conn.execute("SELECT COUNT(*) FROM scripts").fetchone()[0]
            if script_count == 0:
                conn.execute(
                    "INSERT INTO scripts(title,text,enabled,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                    (
                        "Introduction",
                        "Hello and welcome. This is VerbaNode.",
                        1,
                        0,
                        now,
                        now,
                    ),
                )

    # Settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO settings(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at
                """,
                (key, value, now),
            )

    def get_runtime_settings(self) -> dict[str, Any]:
        keys = [
            "active_agent_id",
            "interruption_enabled",
            "silence_ms",
            "max_record_seconds",
            "stt_confidence_filter_enabled",
            "stt_confidence_threshold",
            "input_device",
            "output_device",
        ]
        result: dict[str, Any] = {}
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT key,value FROM settings WHERE key IN ({','.join('?' for _ in keys)})",
                keys,
            ).fetchall()
        for row in rows:
            value: Any = row["value"]
            if row["key"] in {"interruption_enabled", "stt_confidence_filter_enabled"}:
                value = value.lower() == "true"
            elif row["key"] == "stt_confidence_threshold":
                try:
                    value = max(0.0, min(1.0, float(value)))
                except (TypeError, ValueError):
                    value = 0.88
            elif row["key"] in {"active_agent_id", "silence_ms", "max_record_seconds", "input_device", "output_device"}:
                value = int(value) if value not in {"", "none", "null"} else None
            result[row["key"]] = value
        result.setdefault("interruption_enabled", False)
        result.setdefault("silence_ms", self.settings.silence_ms)
        result.setdefault("max_record_seconds", self.settings.max_record_seconds)
        result.setdefault("stt_confidence_filter_enabled", True)
        result.setdefault("stt_confidence_threshold", 0.88)
        result.setdefault("input_device", None)
        result.setdefault("output_device", None)
        return result

    # Agents
    def _decode_agent(self, data: dict[str, Any]) -> dict[str, Any]:
        data["tools_enabled"] = json.loads(data.get("tools_enabled") or "[]")
        data["info_ids"] = self.agent_info_ids(int(data["id"]))
        data["kokoro_voice_name"] = voice_name(data.get("kokoro_voice_id"))
        return data

    def list_agents(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM agents ORDER BY id").fetchall()
        return [self._decode_agent(dict(row)) for row in rows]

    def get_agent(self, agent_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        return self._decode_agent(dict(row)) if row else None

    def create_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        fields = [
            "name", "color", "avatar", "role", "system_prompt", "greeting", "llm_model",
            "temperature", "top_p", "max_tokens", "context_size", "tts_mode", "edge_voice",
            "kokoro_voice_id", "tts_rate", "tts_volume", "stt_model",
        ]
        values = [payload[field] for field in fields]
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                f"INSERT INTO agents({','.join(fields)},tools_enabled,created_at,updated_at) VALUES({','.join('?' for _ in fields)},?,?,?)",
                (*values, json.dumps(payload.get("tools_enabled", [])), now, now),
            )
            agent_id = int(cur.lastrowid)
            self._set_agent_info_conn(conn, agent_id, payload.get("info_ids", []))
            conn.execute(
                "INSERT INTO conversations(agent_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                (agent_id, "New conversation", now, now),
            )
        return self.get_agent(agent_id) or {}

    def update_agent(self, agent_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        now = utc_now()
        fields = [
            "name", "color", "avatar", "role", "system_prompt", "greeting", "llm_model",
            "temperature", "top_p", "max_tokens", "context_size", "tts_mode", "edge_voice",
            "kokoro_voice_id", "tts_rate", "tts_volume", "stt_model",
        ]
        assignments = ",".join(f"{field}=?" for field in fields)
        values = [payload[field] for field in fields]
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                f"UPDATE agents SET {assignments},tools_enabled=?,updated_at=? WHERE id=?",
                (*values, json.dumps(payload.get("tools_enabled", [])), now, agent_id),
            )
            if cur.rowcount == 0:
                return None
            self._set_agent_info_conn(conn, agent_id, payload.get("info_ids", []))
        return self.get_agent(agent_id)

    def delete_agent(self, agent_id: int) -> bool:
        with self._write_lock, self.connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            if total <= 1:
                raise ValueError("At least one agent must remain")
            cur = conn.execute("DELETE FROM agents WHERE id=?", (agent_id,))
            if cur.rowcount:
                next_id = conn.execute("SELECT id FROM agents ORDER BY id LIMIT 1").fetchone()[0]
                conn.execute(
                    "UPDATE settings SET value=?,updated_at=? WHERE key='active_agent_id'",
                    (str(next_id), utc_now()),
                )
            return bool(cur.rowcount)

    def agent_info_ids(self, agent_id: int) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT info_id FROM agent_information WHERE agent_id=? ORDER BY info_id",
                (agent_id,),
            ).fetchall()
        return [int(row[0]) for row in rows]

    def _set_agent_info_conn(self, conn: sqlite3.Connection, agent_id: int, info_ids: list[int]) -> None:
        conn.execute("DELETE FROM agent_information WHERE agent_id=?", (agent_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO agent_information(agent_id,info_id) VALUES(?,?)",
            [(agent_id, int(info_id)) for info_id in info_ids],
        )

    def enabled_information_for_agent(self, agent_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT i.* FROM information i
                JOIN agent_information ai ON ai.info_id=i.id
                WHERE ai.agent_id=? AND i.enabled=1
                ORDER BY i.id
                """,
                (agent_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # Information
    def list_information(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM information ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]

    def get_information(self, info_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM information WHERE id=?", (info_id,)).fetchone()
        return row_dict(row)

    def create_information(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO information(title,content,enabled,created_at,updated_at) VALUES(?,?,?,?,?)",
                (payload["title"], payload["content"], int(payload["enabled"]), now, now),
            )
            info_id = int(cur.lastrowid)
        return self.get_information(info_id) or {}

    def update_information(self, info_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                "UPDATE information SET title=?,content=?,enabled=?,updated_at=? WHERE id=?",
                (payload["title"], payload["content"], int(payload["enabled"]), utc_now(), info_id),
            )
            if not cur.rowcount:
                return None
        return self.get_information(info_id)

    def delete_information(self, info_id: int) -> bool:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute("DELETE FROM information WHERE id=?", (info_id,))
        return bool(cur.rowcount)

    # Scripts and queue
    def list_scripts(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM scripts ORDER BY sort_order,id").fetchall()
        return [dict(row) for row in rows]

    def get_script(self, script_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM scripts WHERE id=?", (script_id,)).fetchone()
        return row_dict(row)

    def create_script(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            sort_order = conn.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM scripts").fetchone()[0]
            cur = conn.execute(
                "INSERT INTO scripts(title,text,enabled,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (payload["title"], payload["text"], int(payload["enabled"]), sort_order, now, now),
            )
            script_id = int(cur.lastrowid)
        return self.get_script(script_id) or {}

    def update_script(self, script_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                "UPDATE scripts SET title=?,text=?,enabled=?,updated_at=? WHERE id=?",
                (payload["title"], payload["text"], int(payload["enabled"]), utc_now(), script_id),
            )
            if not cur.rowcount:
                return None
        return self.get_script(script_id)

    def delete_script(self, script_id: int) -> bool:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute("DELETE FROM scripts WHERE id=?", (script_id,))
        return bool(cur.rowcount)

    def queue_script(self, script_id: int) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            position = conn.execute("SELECT COALESCE(MAX(position),-1)+1 FROM script_queue").fetchone()[0]
            cur = conn.execute(
                "INSERT INTO script_queue(script_id,position,status,added_at) VALUES(?,?,?,?)",
                (script_id, position, "waiting", now),
            )
            queue_id = int(cur.lastrowid)
        return self.get_queue_item(queue_id) or {}

    def get_queue_item(self, queue_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT q.*,s.title,s.text,s.enabled FROM script_queue q
                JOIN scripts s ON s.id=q.script_id WHERE q.id=?
                """,
                (queue_id,),
            ).fetchone()
        return row_dict(row)

    def list_queue(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT q.*,s.title,s.text,s.enabled FROM script_queue q
                JOIN scripts s ON s.id=q.script_id ORDER BY q.position,q.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def pop_next_queue_item(self) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT q.*,s.title,s.text,s.enabled FROM script_queue q
                JOIN scripts s ON s.id=q.script_id
                WHERE q.status='waiting' ORDER BY q.position,q.id LIMIT 1
                """
            ).fetchone()
            if row:
                conn.execute("UPDATE script_queue SET status='playing' WHERE id=?", (row["id"],))
        return dict(row) if row else None

    def finish_queue_item(self, queue_id: int, remove: bool = True) -> None:
        with self._write_lock, self.connect() as conn:
            if remove:
                conn.execute("DELETE FROM script_queue WHERE id=?", (queue_id,))
            else:
                conn.execute("UPDATE script_queue SET status='waiting' WHERE id=?", (queue_id,))

    def remove_queue_item(self, queue_id: int) -> bool:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute("DELETE FROM script_queue WHERE id=?", (queue_id,))
        return bool(cur.rowcount)

    def clear_queue(self) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute("DELETE FROM script_queue")

    def reorder_queue(self, ordered_ids: list[int]) -> None:
        with self._write_lock, self.connect() as conn:
            conn.executemany(
                "UPDATE script_queue SET position=? WHERE id=?",
                [(index, queue_id) for index, queue_id in enumerate(ordered_ids)],
            )

    # Conversations and messages
    def create_conversation(self, agent_id: int, title: str | None = None) -> dict[str, Any]:
        now = utc_now()
        title = title or "New conversation"
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO conversations(agent_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                (agent_id, title, now, now),
            )
            conversation_id = int(cur.lastrowid)
        return self.get_conversation(conversation_id) or {}

    def list_conversations(self, agent_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT c.*,COUNT(m.id) AS message_count
                FROM conversations c LEFT JOIN messages m ON m.conversation_id=c.id
                WHERE c.agent_id=? GROUP BY c.id ORDER BY c.updated_at DESC,c.id DESC
                """,
                (agent_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_conversation(self, agent_id: int) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM conversations WHERE agent_id=? ORDER BY updated_at DESC,id DESC LIMIT 1",
                (agent_id,),
            ).fetchone()
        return dict(row) if row else self.create_conversation(agent_id)

    def get_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
        return row_dict(row)

    def delete_conversation(self, conversation_id: int) -> bool:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        return bool(cur.rowcount)

    def clear_conversation(self, conversation_id: int) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
            conn.execute("DELETE FROM summaries WHERE conversation_id=?", (conversation_id,))
            conn.execute(
                "UPDATE conversations SET title='New conversation',updated_at=? WHERE id=?",
                (utc_now(), conversation_id),
            )

    def add_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        source: str = "chat",
        stt_confidence: float | None = None,
        stt_confidence_source: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO messages(
                    conversation_id,role,content,source,
                    stt_confidence,stt_confidence_source,created_at
                ) VALUES(?,?,?,?,?,?,?)
                """,
                (
                    conversation_id,
                    role,
                    content,
                    source,
                    stt_confidence,
                    stt_confidence_source,
                    now,
                ),
            )
            message_id = int(cur.lastrowid)
            conn.execute(
                "UPDATE conversations SET updated_at=? WHERE id=?",
                (now, conversation_id),
            )
            if role == "user":
                existing_title = conn.execute(
                    "SELECT title FROM conversations WHERE id=?", (conversation_id,)
                ).fetchone()[0]
                if existing_title == "New conversation":
                    title = content.strip().replace("\n", " ")[:64] or "New conversation"
                    conn.execute("UPDATE conversations SET title=? WHERE id=?", (title, conversation_id))
            row = conn.execute("SELECT * FROM messages WHERE id=?", (message_id,)).fetchone()
        return dict(row)

    def list_messages(self, conversation_id: int, limit: int = 200, after_id: int = 0) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM messages WHERE conversation_id=? AND id>?
                ORDER BY id ASC LIMIT ?
                """,
                (conversation_id, after_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def message_count(self, conversation_id: int) -> int:
        with self.connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?", (conversation_id,)).fetchone()[0])

    def get_summary(self, agent_id: int, conversation_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM summaries WHERE agent_id=? AND conversation_id=?",
                (agent_id, conversation_id),
            ).fetchone()
        return row_dict(row)

    def upsert_summary(self, agent_id: int, conversation_id: int, content: str, through_message_id: int) -> None:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO summaries(agent_id,conversation_id,content,through_message_id,created_at,updated_at)
                VALUES(?,?,?,?,?,?)
                ON CONFLICT(agent_id,conversation_id) DO UPDATE SET
                    content=excluded.content,
                    through_message_id=excluded.through_message_id,
                    updated_at=excluded.updated_at
                """,
                (agent_id, conversation_id, content, through_message_id, now, now),
            )

    def clear_agent_memory(self, agent_id: int) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute(
                "DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE agent_id=?)",
                (agent_id,),
            )
            conn.execute("DELETE FROM summaries WHERE agent_id=?", (agent_id,))
            conn.execute("DELETE FROM conversations WHERE agent_id=?", (agent_id,))
            now = utc_now()
            conn.execute(
                "INSERT INTO conversations(agent_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                (agent_id, "New conversation", now, now),
            )

    # Backup
    def backup_to(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with self._write_lock, self.connect() as conn:
            conn.execute("PRAGMA wal_checkpoint(FULL)")
        shutil.copy2(self.path, destination)
        return destination
