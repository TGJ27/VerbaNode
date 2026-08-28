from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import Settings
from app.defaults import (
    DEFAULT_COMPANY_INFO_CONTENT,
    DEFAULT_COMPANY_INFO_TITLE,
    DEFAULT_INTRO_EN_TEXT,
    DEFAULT_INTRO_EN_TITLE,
    DEFAULT_INTRO_ID_TEXT,
    DEFAULT_INTRO_ID_TITLE,
    ROPI_CONTEXT_SIZE,
    ROPI_GREETING,
    ROPI_ID_EDGE_VOICE,
    ROPI_ID_GREETING,
    ROPI_ID_ROLE,
    ROPI_ID_STT_MODEL,
    ROPI_ID_SYSTEM_PROMPT,
    ROPI_LLM_MODEL,
    ROPI_MAX_TOKENS,
    ROPI_ROLE,
    ROPI_SYSTEM_PROMPT,
    ROPI_TEMPERATURE,
    ROPI_TOP_P,
)
from app.migrations import (
    CURRENT_SCHEMA_VERSION,
    MigrationError,
    VERBANODE_APPLICATION_ID,
    apply_migrations,
    read_schema_version,
    repair_type_to_talk_queue_schema,
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
        preexisting = self.path.exists() and self.path.stat().st_size > 0
        if preexisting:
            self._validate_existing_identity()
        pre_migration_version = self.schema_version() if preexisting else CURRENT_SCHEMA_VERSION
        if preexisting and pre_migration_version < CURRENT_SCHEMA_VERSION:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            recovery_path = self.settings.backup_dir / (
                f"pre-migration-v{pre_migration_version}-to-v{CURRENT_SCHEMA_VERSION}-{stamp}.db"
            )
            self.backup_to(recovery_path)
            self.prune_recovery_backups()

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
            language TEXT NOT NULL DEFAULT 'en',
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
            language TEXT NOT NULL DEFAULT 'en',
            tts_mode TEXT NOT NULL DEFAULT 'edge',
            edge_voice TEXT NOT NULL DEFAULT 'en-US-AriaNeural',
            kokoro_voice_id INTEGER NOT NULL DEFAULT 0,
            tts_rate REAL NOT NULL DEFAULT 1.0,
            tts_volume REAL NOT NULL DEFAULT 1.0,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS script_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            script_id INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'waiting',
            pause_after_seconds REAL NOT NULL DEFAULT 0,
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
            apply_migrations(conn)
            # Health-check the direct-speech queue on every startup, even when
            # schema metadata already says the database is current. This is
            # deliberately independent of migration versioning so a stale
            # trigger/object cannot survive a hand-copied or interrupted update.
            repair_type_to_talk_queue_schema(conn)
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
                ("stt_confidence_threshold", "0.70", now),
            )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("show_rejected_stt_transcripts", "true", now),
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
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("pipeline_safety_version", "0", now),
            )
            pipeline_version_row = conn.execute(
                "SELECT value FROM settings WHERE key='pipeline_safety_version'"
            ).fetchone()
            try:
                pipeline_version = int(pipeline_version_row[0]) if pipeline_version_row else 0
            except (TypeError, ValueError):
                pipeline_version = 0
            if pipeline_version < 1:
                # v0.2.6 used 88% as a hard gate even when SenseVoice exposed
                # only VerbaNode's heuristic quality estimate. Migrate only the
                # old default so deliberate user thresholds remain unchanged.
                conn.execute(
                    """
                    UPDATE settings SET value='0.70', updated_at=?
                    WHERE key='stt_confidence_threshold' AND value IN ('0.88','0.880','88')
                    """,
                    (now,),
                )
                conn.execute(
                    "UPDATE settings SET value='1', updated_at=? WHERE key='pipeline_safety_version'",
                    (now,),
                )
            count = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            if count == 0:
                conn.execute(
                    """
                    INSERT INTO agents(
                        name,color,avatar,role,system_prompt,greeting,llm_model,
                        temperature,top_p,max_tokens,context_size,language,tts_mode,edge_voice,
                        kokoro_voice_id,tts_rate,tts_volume,stt_model,tools_enabled,
                        created_at,updated_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                        "en",
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
            if ropi_version < 3:
                # Preserve the v0.3.1 reliability migration for databases that
                # upgrade directly from v0.2.6 or earlier. Voice, greeting,
                # information, chats, memory, extra tools, and the user's STT
                # threshold are preserved.
                conn.execute(
                    """
                    UPDATE agents
                    SET role=?, system_prompt=?, llm_model=?, temperature=?, top_p=?,
                        max_tokens=?, context_size=?, updated_at=?
                    WHERE lower(trim(name))='ropi' AND language='en'
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
                core_tools = [
                    "get_current_time",
                    "get_location",
                    "get_weather",
                    "handle_exit_intent",
                ]
                ropi_rows = conn.execute(
                    "SELECT id, tools_enabled FROM agents WHERE lower(trim(name))='ropi' AND language='en'"
                ).fetchall()
                for row in ropi_rows:
                    try:
                        enabled_tools = json.loads(row["tools_enabled"] or "[]")
                    except (TypeError, json.JSONDecodeError):
                        enabled_tools = []
                    for tool_name in core_tools:
                        if tool_name not in enabled_tools:
                            enabled_tools.append(tool_name)
                    conn.execute(
                        "UPDATE agents SET tools_enabled=?, updated_at=? WHERE id=?",
                        (json.dumps(enabled_tools), now, row["id"]),
                    )
                ropi_version = 3

            if ropi_version < 4:
                # v0.3.2 separates the editable Ropi character from hidden
                # VerbaNode operating policies. Replace only the known v0.3.1
                # operational prompt, preserving genuinely customized prompts.
                conn.execute(
                    """
                    UPDATE agents
                    SET role=?, system_prompt=?, updated_at=?
                    WHERE lower(trim(name))='ropi' AND language='en'
                      AND (
                        system_prompt LIKE '%Mandatory live-data and tool rules:%'
                        OR system_prompt LIKE '%Tools are the only source of truth%'
                      )
                    """,
                    (ROPI_ROLE, ROPI_SYSTEM_PROMPT, now),
                )
                conn.execute(
                    "UPDATE settings SET value='4', updated_at=? WHERE key='ropi_defaults_version'",
                    (now,),
                )
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("indonesian_agent_seed_version", "0", now),
            )
            id_seed_row = conn.execute(
                "SELECT value FROM settings WHERE key='indonesian_agent_seed_version'"
            ).fetchone()
            try:
                id_seed_version = int(id_seed_row[0]) if id_seed_row else 0
            except (TypeError, ValueError):
                id_seed_version = 0
            if id_seed_version < 1:
                existing_id = conn.execute(
                    "SELECT id FROM agents WHERE lower(trim(name)) IN ('ropi indonesia','ropi id') LIMIT 1"
                ).fetchone()
                if not existing_id:
                    cur = conn.execute(
                        """
                        INSERT INTO agents(
                            name,color,avatar,role,system_prompt,greeting,llm_model,
                            temperature,top_p,max_tokens,context_size,language,tts_mode,edge_voice,
                            kokoro_voice_id,tts_rate,tts_volume,stt_model,tools_enabled,
                            created_at,updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            "Ropi", "#ef6c35", "RI", ROPI_ID_ROLE,
                            ROPI_ID_SYSTEM_PROMPT, ROPI_ID_GREETING, ROPI_LLM_MODEL,
                            ROPI_TEMPERATURE, ROPI_TOP_P, ROPI_MAX_TOKENS,
                            ROPI_CONTEXT_SIZE, "id", "edge", ROPI_ID_EDGE_VOICE,
                            0, 1.0, 1.0, ROPI_ID_STT_MODEL,
                            json.dumps([
                                "get_current_time", "get_location",
                                "get_weather", "handle_exit_intent",
                            ]),
                            now, now,
                        ),
                    )
                    indonesian_agent_id = int(cur.lastrowid)
                    conn.execute(
                        "INSERT INTO conversations(agent_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                        (indonesian_agent_id, "Percakapan baru", now, now),
                    )
                conn.execute(
                    "UPDATE settings SET value='1', updated_at=? WHERE key='indonesian_agent_seed_version'",
                    (now,),
                )

            # Preserve the operator's last selected agent across application restarts.
            # Older builds reset active_agent_id to the first agent on every startup.
            first_agent_row = conn.execute("SELECT id FROM agents ORDER BY id LIMIT 1").fetchone()
            if first_agent_row is None:
                raise RuntimeError("No agents configured after database seed")
            first_agent_id = int(first_agent_row[0])
            active_row = conn.execute(
                "SELECT value FROM settings WHERE key='active_agent_id'"
            ).fetchone()
            try:
                active_agent_id = int(active_row[0]) if active_row else first_agent_id
            except (TypeError, ValueError):
                active_agent_id = first_agent_id
            active_exists = conn.execute(
                "SELECT 1 FROM agents WHERE id=?", (active_agent_id,)
            ).fetchone()
            if not active_exists:
                active_agent_id = first_agent_id
                conn.execute(
                    "UPDATE settings SET value=?, updated_at=? WHERE key='active_agent_id'",
                    (str(active_agent_id), now),
                )
            agent_id = active_agent_id
            conv_count = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE agent_id=?", (agent_id,)
            ).fetchone()[0]
            if conv_count == 0:
                conn.execute(
                    "INSERT INTO conversations(agent_id,title,created_at,updated_at) VALUES(?,?,?,?)",
                    (agent_id, "New conversation", now, now),
                )
            # v0.7.5 packaged defaults. Keep this idempotent so upgrades never
            # duplicate content or overwrite operator-created agents/scripts/info.
            conn.execute(
                "INSERT OR IGNORE INTO settings(key,value,updated_at) VALUES(?,?,?)",
                ("packaged_defaults_version", "0", now),
            )
            packaged_row = conn.execute(
                "SELECT value FROM settings WHERE key='packaged_defaults_version'"
            ).fetchone()
            try:
                packaged_version = int(packaged_row[0]) if packaged_row else 0
            except (TypeError, ValueError):
                packaged_version = 0

            if packaged_version < 1:
                # Upgrade the originally seeded Indonesian agent to the requested
                # production identity. Only the known seed names are migrated;
                # unrelated custom Indonesian agents are left untouched.
                conn.execute(
                    """
                    UPDATE agents
                    SET name='Ropi', color='#ef6c35', avatar='RI', role=?,
                        system_prompt=?, greeting=?, updated_at=?
                    WHERE language='id'
                      AND lower(trim(name)) IN ('ropi indonesia','ropi id')
                    """,
                    (ROPI_ID_ROLE, ROPI_ID_SYSTEM_PROMPT, ROPI_ID_GREETING, now),
                )

                # Refresh only the exact legacy English seed text. Any script
                # the operator edited remains untouched.
                conn.execute(
                    """
                    UPDATE scripts SET text=?,updated_at=?
                    WHERE language='en'
                      AND lower(trim(title))='introduction'
                      AND text='Hello and welcome. This is the VerbaNode standalone voice assistant.'
                    """,
                    (DEFAULT_INTRO_EN_TEXT, now),
                )

                # Seed both direct-speech introductions independently. Existing
                # scripts with the same language/title are preserved.
                script_defaults = [
                    (DEFAULT_INTRO_EN_TITLE, DEFAULT_INTRO_EN_TEXT, "en", "edge", "en-US-AriaNeural", 0),
                    (DEFAULT_INTRO_ID_TITLE, DEFAULT_INTRO_ID_TEXT, "id", "edge", ROPI_ID_EDGE_VOICE, 1),
                ]
                for title, text, language, tts_mode, edge_voice, sort_order in script_defaults:
                    existing_script = conn.execute(
                        "SELECT id FROM scripts WHERE language=? AND lower(trim(title))=lower(trim(?)) LIMIT 1",
                        (language, title),
                    ).fetchone()
                    if not existing_script:
                        conn.execute(
                            """
                            INSERT INTO scripts(
                                title,text,enabled,language,tts_mode,edge_voice,kokoro_voice_id,
                                tts_rate,tts_volume,sort_order,created_at,updated_at
                            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                            """,
                            (
                                title, text, 1, language, tts_mode, edge_voice,
                                0, 1.0, 1.0, sort_order, now, now,
                            ),
                        )

                # Seed the company profile once and assign it to every existing
                # agent so both English and Indonesian Ropi can use it. If the
                # operator already has an item with this title, preserve its text.
                info_row = conn.execute(
                    "SELECT id FROM information WHERE lower(trim(title))=lower(trim(?)) LIMIT 1",
                    (DEFAULT_COMPANY_INFO_TITLE,),
                ).fetchone()
                if info_row:
                    info_id = int(info_row[0])
                else:
                    cur = conn.execute(
                        "INSERT INTO information(title,content,enabled,created_at,updated_at) VALUES(?,?,?,?,?)",
                        (DEFAULT_COMPANY_INFO_TITLE, DEFAULT_COMPANY_INFO_CONTENT, 1, now, now),
                    )
                    info_id = int(cur.lastrowid)
                agent_rows = conn.execute("SELECT id FROM agents ORDER BY id").fetchall()
                conn.executemany(
                    "INSERT OR IGNORE INTO agent_information(agent_id,info_id) VALUES(?,?)",
                    [(int(row[0]), info_id) for row in agent_rows],
                )

                conn.execute(
                    "UPDATE settings SET value='1',updated_at=? WHERE key='packaged_defaults_version'",
                    (now,),
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
            "show_rejected_stt_transcripts",
            "input_device",
            "output_device",
            "input_device_fingerprint",
            "output_device_fingerprint",
        ]
        result: dict[str, Any] = {}
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT key,value FROM settings WHERE key IN ({','.join('?' for _ in keys)})",
                keys,
            ).fetchall()
        for row in rows:
            value: Any = row["value"]
            if row["key"] in {"interruption_enabled", "stt_confidence_filter_enabled", "show_rejected_stt_transcripts"}:
                value = value.lower() == "true"
            elif row["key"] == "stt_confidence_threshold":
                try:
                    value = max(0.0, min(1.0, float(value)))
                except (TypeError, ValueError):
                    value = 0.70
            elif row["key"] in {"active_agent_id", "silence_ms", "max_record_seconds", "input_device", "output_device"}:
                value = int(value) if value not in {"", "none", "null"} else None
            result[row["key"]] = value
        result.setdefault("interruption_enabled", False)
        result.setdefault("silence_ms", self.settings.silence_ms)
        result.setdefault("max_record_seconds", self.settings.max_record_seconds)
        result.setdefault("stt_confidence_filter_enabled", True)
        result.setdefault("stt_confidence_threshold", 0.70)
        result.setdefault("show_rejected_stt_transcripts", True)
        result.setdefault("input_device", None)
        result.setdefault("output_device", None)
        result.setdefault("input_device_fingerprint", None)
        result.setdefault("output_device_fingerprint", None)
        return result

    # Agents
    def _decode_agent(self, data: dict[str, Any]) -> dict[str, Any]:
        data["language"] = str(data.get("language") or "en")
        data["tools_enabled"] = json.loads(data.get("tools_enabled") or "[]")
        data["info_ids"] = self.agent_info_ids(int(data["id"]))
        data["knowledge_library_ids"] = self.knowledge_library_ids_for_agent(int(data["id"]))
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
            "temperature", "top_p", "max_tokens", "context_size", "language", "tts_mode", "edge_voice",
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
            "temperature", "top_p", "max_tokens", "context_size", "language", "tts_mode", "edge_voice",
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
            active_row = conn.execute(
                "SELECT value FROM settings WHERE key='active_agent_id'"
            ).fetchone()
            try:
                active_id = int(active_row[0]) if active_row else None
            except (TypeError, ValueError):
                active_id = None
            cur = conn.execute("DELETE FROM agents WHERE id=?", (agent_id,))
            if cur.rowcount and active_id == agent_id:
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

    # Knowledge Engine foundation
    @staticmethod
    def _decode_metadata_json(data: dict[str, Any]) -> dict[str, Any]:
        raw = data.pop("metadata_json", "{}")
        try:
            decoded = json.loads(raw or "{}")
            data["metadata"] = decoded if isinstance(decoded, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            data["metadata"] = {}
        return data

    def list_knowledge_libraries(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT l.*,
                       COUNT(DISTINCT d.id) AS document_count,
                       COUNT(DISTINCT ak.agent_id) AS agent_count
                FROM knowledge_libraries l
                LEFT JOIN knowledge_documents d ON d.library_id=l.id
                LEFT JOIN agent_knowledge_libraries ak
                       ON ak.library_id=l.id AND ak.enabled=1
                GROUP BY l.id
                ORDER BY lower(l.name),l.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def get_knowledge_library(self, library_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT l.*,
                       (SELECT COUNT(*) FROM knowledge_documents d WHERE d.library_id=l.id) AS document_count,
                       (SELECT COUNT(*) FROM agent_knowledge_libraries ak
                        WHERE ak.library_id=l.id AND ak.enabled=1) AS agent_count
                FROM knowledge_libraries l
                WHERE l.id=?
                """,
                (library_id,),
            ).fetchone()
        return row_dict(row)

    def create_knowledge_library(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO knowledge_libraries(name,description,enabled,created_at,updated_at) VALUES(?,?,?,?,?)",
                (
                    str(payload["name"]).strip(),
                    str(payload.get("description") or "").strip(),
                    int(bool(payload.get("enabled", True))),
                    now,
                    now,
                ),
            )
            library_id = int(cur.lastrowid)
        return self.get_knowledge_library(library_id) or {}

    def update_knowledge_library(
        self, library_id: int, payload: dict[str, Any]
    ) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                "UPDATE knowledge_libraries SET name=?,description=?,enabled=?,updated_at=? WHERE id=?",
                (
                    str(payload["name"]).strip(),
                    str(payload.get("description") or "").strip(),
                    int(bool(payload.get("enabled", True))),
                    utc_now(),
                    library_id,
                ),
            )
            if not cur.rowcount:
                return None
        return self.get_knowledge_library(library_id)

    def delete_knowledge_library(self, library_id: int) -> bool:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute("DELETE FROM knowledge_libraries WHERE id=?", (library_id,))
        return bool(cur.rowcount)

    def list_knowledge_documents(
        self, library_id: int | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM knowledge_documents"
        params: tuple[Any, ...] = ()
        if library_id is not None:
            sql += " WHERE library_id=?"
            params = (library_id,)
        sql += " ORDER BY id DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._decode_metadata_json(dict(row)) for row in rows]

    def get_knowledge_document(self, document_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_documents WHERE id=?", (document_id,)
            ).fetchone()
        return self._decode_metadata_json(dict(row)) if row else None

    def register_knowledge_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        metadata = payload.get("metadata") or {}
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO knowledge_documents(
                    library_id,title,source_name,source_type,mime_type,storage_key,
                    size_bytes,sha256,status,error,metadata_json,indexed_at,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    int(payload["library_id"]),
                    str(payload["title"]).strip(),
                    str(payload["source_name"]).strip(),
                    str(payload.get("source_type") or "unknown"),
                    payload.get("mime_type"),
                    payload.get("storage_key"),
                    max(0, int(payload.get("size_bytes") or 0)),
                    payload.get("sha256"),
                    str(payload.get("status") or "registered"),
                    payload.get("error"),
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                    payload.get("indexed_at"),
                    now,
                    now,
                ),
            )
            document_id = int(cur.lastrowid)
        return self.get_knowledge_document(document_id) or {}

    def update_knowledge_document_status(
        self,
        document_id: int,
        *,
        status: str,
        error: str | None = None,
        indexed_at: str | None = None,
    ) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                "UPDATE knowledge_documents SET status=?,error=?,indexed_at=?,updated_at=? WHERE id=?",
                (status, error, indexed_at, utc_now(), document_id),
            )
            if not cur.rowcount:
                return None
        return self.get_knowledge_document(document_id)

    def create_knowledge_ingestion_job(
        self, document_id: int, *, job_type: str = "ingest"
    ) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO knowledge_ingestion_jobs(
                    document_id,job_type,status,stage,progress,attempts,error,queued_at,
                    started_at,completed_at,created_at,updated_at
                ) VALUES(?,?,'queued','queued',0.0,0,NULL,?,NULL,NULL,?,?)
                """,
                (document_id, job_type, now, now, now),
            )
            job_id = int(cur.lastrowid)
        return self.get_knowledge_ingestion_job(job_id) or {}

    def get_knowledge_ingestion_job(self, job_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_ingestion_jobs WHERE id=?", (job_id,)
            ).fetchone()
        return row_dict(row)

    def list_knowledge_ingestion_jobs(
        self, document_id: int | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM knowledge_ingestion_jobs"
        params: tuple[Any, ...] = ()
        if document_id is not None:
            sql += " WHERE document_id=?"
            params = (document_id,)
        sql += " ORDER BY id DESC"
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def update_knowledge_ingestion_job(
        self,
        job_id: int,
        *,
        status: str,
        stage: str,
        progress: float,
        error: str | None = None,
        attempts: int | None = None,
        started_at: str | None = None,
        completed_at: str | None = None,
    ) -> dict[str, Any] | None:
        progress = max(0.0, min(1.0, float(progress)))
        with self._write_lock, self.connect() as conn:
            existing = conn.execute(
                "SELECT attempts,started_at,completed_at FROM knowledge_ingestion_jobs WHERE id=?",
                (job_id,),
            ).fetchone()
            if not existing:
                return None
            cur = conn.execute(
                """
                UPDATE knowledge_ingestion_jobs
                SET status=?,stage=?,progress=?,error=?,attempts=?,started_at=?,completed_at=?,updated_at=?
                WHERE id=?
                """,
                (
                    status,
                    stage,
                    progress,
                    error,
                    int(existing[0] if attempts is None else attempts),
                    existing[1] if started_at is None else started_at,
                    existing[2] if completed_at is None else completed_at,
                    utc_now(),
                    job_id,
                ),
            )
            if not cur.rowcount:
                return None
        return self.get_knowledge_ingestion_job(job_id)

    def add_knowledge_parent_block(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO knowledge_parent_blocks(
                    document_id,parent_block_id,block_type,ordinal,heading_path,page_start,page_end,
                    text,metadata_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    int(payload["document_id"]),
                    payload.get("parent_block_id"),
                    str(payload.get("block_type") or "section"),
                    int(payload.get("ordinal") or 0),
                    str(payload.get("heading_path") or ""),
                    payload.get("page_start"),
                    payload.get("page_end"),
                    str(payload.get("text") or ""),
                    json.dumps(payload.get("metadata") or {}, ensure_ascii=False, sort_keys=True),
                    now,
                ),
            )
            block_id = int(cur.lastrowid)
            row = conn.execute(
                "SELECT * FROM knowledge_parent_blocks WHERE id=?", (block_id,)
            ).fetchone()
        return self._decode_metadata_json(dict(row)) if row else {}

    def add_knowledge_chunk(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO knowledge_chunks(
                    document_id,parent_block_id,ordinal,content_type,text,token_count,page_start,page_end,
                    metadata_json,lexical_status,vector_status,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    int(payload["document_id"]),
                    payload.get("parent_block_id"),
                    int(payload.get("ordinal") or 0),
                    str(payload.get("content_type") or "text"),
                    str(payload.get("text") or ""),
                    max(0, int(payload.get("token_count") or 0)),
                    payload.get("page_start"),
                    payload.get("page_end"),
                    json.dumps(payload.get("metadata") or {}, ensure_ascii=False, sort_keys=True),
                    str(payload.get("lexical_status") or "pending"),
                    str(payload.get("vector_status") or "pending"),
                    now,
                    now,
                ),
            )
            chunk_id = int(cur.lastrowid)
            row = conn.execute(
                "SELECT * FROM knowledge_chunks WHERE id=?", (chunk_id,)
            ).fetchone()
        return self._decode_metadata_json(dict(row)) if row else {}

    def list_knowledge_parent_blocks(self, document_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_parent_blocks WHERE document_id=? ORDER BY ordinal,id",
                (document_id,),
            ).fetchall()
        return [self._decode_metadata_json(dict(row)) for row in rows]

    def list_knowledge_chunks(self, document_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_chunks WHERE document_id=? ORDER BY ordinal,id",
                (document_id,),
            ).fetchall()
        return [self._decode_metadata_json(dict(row)) for row in rows]

    def list_knowledge_assets(self, document_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_document_assets WHERE document_id=? ORDER BY ordinal,id",
                (document_id,),
            ).fetchall()
        return [self._decode_metadata_json(dict(row)) for row in rows]

    def update_knowledge_document_metadata(
        self, document_id: int, metadata: dict[str, Any]
    ) -> dict[str, Any] | None:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            existing = conn.execute(
                "SELECT metadata_json FROM knowledge_documents WHERE id=?", (document_id,)
            ).fetchone()
            if not existing:
                return None
            try:
                current = json.loads(existing[0] or "{}")
                if not isinstance(current, dict):
                    current = {}
            except (TypeError, ValueError, json.JSONDecodeError):
                current = {}
            current.update(metadata or {})
            conn.execute(
                "UPDATE knowledge_documents SET metadata_json=?,updated_at=? WHERE id=?",
                (json.dumps(current, ensure_ascii=False, sort_keys=True), now, document_id),
            )
        return self.get_knowledge_document(document_id)

    def replace_knowledge_document_content(
        self,
        document_id: int,
        blocks: list[dict[str, Any]],
        assets: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Atomically replace normalized Phase-2 content for a document."""
        now = utc_now()
        chunk_count = 0
        with self._write_lock, self.connect() as conn:
            if not conn.execute(
                "SELECT 1 FROM knowledge_documents WHERE id=?", (document_id,)
            ).fetchone():
                raise LookupError("Knowledge document not found")
            conn.execute("DELETE FROM knowledge_document_assets WHERE document_id=?", (document_id,))
            conn.execute("DELETE FROM knowledge_chunks WHERE document_id=?", (document_id,))
            conn.execute("DELETE FROM knowledge_parent_blocks WHERE document_id=?", (document_id,))

            parent_by_ordinal: dict[int, int] = {}
            global_chunk_ordinal = 0
            for block in blocks:
                ordinal = int(block.get("ordinal") or 0)
                cur = conn.execute(
                    """
                    INSERT INTO knowledge_parent_blocks(
                        document_id,parent_block_id,block_type,ordinal,heading_path,page_start,page_end,
                        text,metadata_json,created_at
                    ) VALUES(?,NULL,?,?,?,?,?,?,?,?)
                    """,
                    (
                        document_id,
                        str(block.get("block_type") or "section"),
                        ordinal,
                        str(block.get("heading_path") or ""),
                        block.get("page_start"),
                        block.get("page_end"),
                        str(block.get("text") or ""),
                        json.dumps(block.get("metadata") or {}, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
                parent_id = int(cur.lastrowid)
                parent_by_ordinal[ordinal] = parent_id
                for chunk in block.get("chunks") or []:
                    conn.execute(
                        """
                        INSERT INTO knowledge_chunks(
                            document_id,parent_block_id,ordinal,content_type,text,token_count,page_start,page_end,
                            metadata_json,lexical_status,vector_status,created_at,updated_at
                        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            document_id,
                            parent_id,
                            global_chunk_ordinal,
                            str(chunk.get("content_type") or "text"),
                            str(chunk.get("text") or ""),
                            max(0, int(chunk.get("token_count") or 0)),
                            chunk.get("page_start"),
                            chunk.get("page_end"),
                            json.dumps(chunk.get("metadata") or {}, ensure_ascii=False, sort_keys=True),
                            str(chunk.get("lexical_status") or "pending"),
                            str(chunk.get("vector_status") or "pending"),
                            now,
                            now,
                        ),
                    )
                    chunk_count += 1
                    global_chunk_ordinal += 1

            for ordinal, asset in enumerate(assets):
                parent_ordinal = asset.get("parent_ordinal")
                parent_id = parent_by_ordinal.get(int(parent_ordinal)) if parent_ordinal is not None else None
                conn.execute(
                    """
                    INSERT INTO knowledge_document_assets(
                        document_id,parent_block_id,ordinal,asset_type,mime_type,storage_key,label,
                        page_start,page_end,ocr_text,metadata_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        document_id,
                        parent_id,
                        ordinal,
                        str(asset.get("asset_type") or "image"),
                        asset.get("mime_type"),
                        asset.get("storage_key"),
                        str(asset.get("label") or ""),
                        asset.get("page_start"),
                        asset.get("page_end"),
                        str(asset.get("ocr_text") or ""),
                        json.dumps(asset.get("metadata") or {}, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
        return {"parent_blocks": len(blocks), "chunks": chunk_count, "assets": len(assets)}

    def delete_knowledge_document(self, document_id: int) -> bool:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute("DELETE FROM knowledge_documents WHERE id=?", (document_id,))
        return bool(cur.rowcount)

    def knowledge_library_ids_for_agent(self, agent_id: int) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT library_id FROM agent_knowledge_libraries
                WHERE agent_id=? AND enabled=1
                ORDER BY library_id
                """,
                (agent_id,),
            ).fetchall()
        return [int(row[0]) for row in rows]

    def set_agent_knowledge_libraries(
        self, agent_id: int, library_ids: list[int]
    ) -> list[int]:
        unique_ids = sorted({int(value) for value in library_ids})
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            agent = conn.execute("SELECT id FROM agents WHERE id=?", (agent_id,)).fetchone()
            if not agent:
                raise LookupError("Agent not found")
            if unique_ids:
                placeholders = ",".join("?" for _ in unique_ids)
                existing = {
                    int(row[0])
                    for row in conn.execute(
                        f"SELECT id FROM knowledge_libraries WHERE id IN ({placeholders})",
                        tuple(unique_ids),
                    ).fetchall()
                }
                missing = [value for value in unique_ids if value not in existing]
                if missing:
                    raise ValueError(
                        "Knowledge library not found: " + ", ".join(str(value) for value in missing)
                    )
            conn.execute("DELETE FROM agent_knowledge_libraries WHERE agent_id=?", (agent_id,))
            conn.executemany(
                "INSERT INTO agent_knowledge_libraries(agent_id,library_id,enabled,created_at) VALUES(?,?,1,?)",
                [(agent_id, library_id, now) for library_id in unique_ids],
            )
        return unique_ids

    def knowledge_enabled_library_ids(self) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM knowledge_libraries WHERE enabled=1 ORDER BY id"
            ).fetchall()
        return [int(row[0]) for row in rows]

    def knowledge_chunk_ids(self, document_id: int) -> list[int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM knowledge_chunks WHERE document_id=? ORDER BY id",
                (document_id,),
            ).fetchall()
        return [int(row[0]) for row in rows]

    def knowledge_chunks_for_index(
        self,
        *,
        library_id: int | None = None,
        document_id: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if library_id is not None:
            clauses.append("d.library_id=?")
            params.append(int(library_id))
        if document_id is not None:
            clauses.append("c.document_id=?")
            params.append(int(document_id))
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.*,d.library_id,d.title AS document_title,d.source_name,
                       l.name AS library_name,l.enabled AS library_enabled,
                       COALESCE(p.heading_path,'') AS heading_path,
                       p.block_type AS parent_block_type
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id=c.document_id
                JOIN knowledge_libraries l ON l.id=d.library_id
                LEFT JOIN knowledge_parent_blocks p ON p.id=c.parent_block_id
                {where}
                ORDER BY d.library_id,c.document_id,c.ordinal,c.id
                """,
                tuple(params),
            ).fetchall()
        return [self._decode_metadata_json(dict(row)) for row in rows]

    def knowledge_chunks_by_ids(self, chunk_ids: list[int]) -> list[dict[str, Any]]:
        ids = sorted({int(value) for value in chunk_ids if int(value) > 0})
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.*,c.id AS chunk_id,d.library_id,d.title AS document_title,d.source_name,
                       l.name AS library_name,l.enabled AS library_enabled,
                       COALESCE(p.heading_path,'') AS heading_path,
                       p.block_type AS parent_block_type
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id=c.document_id
                JOIN knowledge_libraries l ON l.id=d.library_id
                LEFT JOIN knowledge_parent_blocks p ON p.id=c.parent_block_id
                WHERE c.id IN ({placeholders})
                """,
                tuple(ids),
            ).fetchall()
        return [self._decode_metadata_json(dict(row)) for row in rows]

    def mark_knowledge_chunks_lexical(
        self, chunk_ids: list[int], *, status: str, indexed_at: str | None
    ) -> None:
        ids = sorted({int(value) for value in chunk_ids if int(value) > 0})
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._write_lock, self.connect() as conn:
            conn.execute(
                f"UPDATE knowledge_chunks SET lexical_status=?,lexical_indexed_at=?,updated_at=? "
                f"WHERE id IN ({placeholders})",
                (status, indexed_at, utc_now(), *ids),
            )

    def mark_knowledge_chunks_vector(
        self,
        chunk_ids: list[int],
        *,
        status: str,
        model_name: str,
        indexed_at: str | None,
    ) -> None:
        ids = sorted({int(value) for value in chunk_ids if int(value) > 0})
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._write_lock, self.connect() as conn:
            conn.execute(
                f"UPDATE knowledge_chunks SET vector_status=?,embedding_model=?,vector_indexed_at=?,updated_at=? "
                f"WHERE id IN ({placeholders})",
                (status, model_name, indexed_at, utc_now(), *ids),
            )

    def rebuild_knowledge_lexical_index(self) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute("INSERT INTO knowledge_chunks_fts(knowledge_chunks_fts) VALUES('rebuild')")

    def replace_knowledge_table_rows(
        self, document_id: int, rows: list[dict[str, Any]]
    ) -> int:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            conn.execute("DELETE FROM knowledge_table_rows WHERE document_id=?", (document_id,))
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO knowledge_table_rows(
                        chunk_id,document_id,library_id,row_number,header_json,cells_json,
                        row_text,metadata_json,created_at
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        int(row["chunk_id"]),
                        int(row["document_id"]),
                        int(row["library_id"]),
                        int(row.get("row_number") or 0),
                        json.dumps(row.get("header") or [], ensure_ascii=False),
                        json.dumps(row.get("cells") or [], ensure_ascii=False),
                        str(row.get("row_text") or ""),
                        json.dumps(row.get("metadata") or {}, ensure_ascii=False, sort_keys=True),
                        now,
                    ),
                )
        return len(rows)

    def knowledge_table_row_count(self, *, library_id: int | None = None) -> int:
        sql = "SELECT COUNT(*) FROM knowledge_table_rows"
        params: tuple[Any, ...] = ()
        if library_id is not None:
            sql += " WHERE library_id=?"
            params = (int(library_id),)
        with self.connect() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    def search_knowledge_lexical(
        self, fts_query: str, library_ids: list[int], limit: int
    ) -> list[dict[str, Any]]:
        ids = sorted({int(value) for value in library_ids if int(value) > 0})
        if not fts_query or not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        params: list[Any] = [fts_query, *ids, max(1, int(limit))]
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.*,c.id AS chunk_id,d.library_id,d.title AS document_title,d.source_name,
                       l.name AS library_name,COALESCE(p.heading_path,'') AS heading_path,
                       p.block_type AS parent_block_type,
                       bm25(knowledge_chunks_fts) AS lexical_bm25
                FROM knowledge_chunks_fts
                JOIN knowledge_chunks c ON c.id=knowledge_chunks_fts.rowid
                JOIN knowledge_documents d ON d.id=c.document_id
                JOIN knowledge_libraries l ON l.id=d.library_id
                LEFT JOIN knowledge_parent_blocks p ON p.id=c.parent_block_id
                WHERE knowledge_chunks_fts MATCH ?
                  AND d.library_id IN ({placeholders})
                  AND l.enabled=1
                ORDER BY lexical_bm25 ASC,c.id ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            item = self._decode_metadata_json(dict(row))
            raw = float(item.pop("lexical_bm25", 0.0) or 0.0)
            item["lexical_score"] = -raw
            results.append(item)
        return results

    def search_knowledge_table_rows(
        self, fts_query: str, library_ids: list[int], limit: int
    ) -> list[dict[str, Any]]:
        ids = sorted({int(value) for value in library_ids if int(value) > 0})
        if not fts_query or not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        params: list[Any] = [fts_query, *ids, max(1, int(limit))]
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT c.*,c.id AS chunk_id,d.library_id,d.title AS document_title,d.source_name,
                       l.name AS library_name,COALESCE(p.heading_path,'') AS heading_path,
                       p.block_type AS parent_block_type,
                       r.row_number,r.row_text,r.header_json,r.cells_json,
                       bm25(knowledge_table_rows_fts) AS table_bm25
                FROM knowledge_table_rows_fts
                JOIN knowledge_table_rows r ON r.id=knowledge_table_rows_fts.rowid
                JOIN knowledge_chunks c ON c.id=r.chunk_id
                JOIN knowledge_documents d ON d.id=c.document_id
                JOIN knowledge_libraries l ON l.id=d.library_id
                LEFT JOIN knowledge_parent_blocks p ON p.id=c.parent_block_id
                WHERE knowledge_table_rows_fts MATCH ?
                  AND r.library_id IN ({placeholders})
                  AND l.enabled=1
                ORDER BY table_bm25 ASC,r.id ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        results: list[dict[str, Any]] = []
        seen: set[int] = set()
        for row in rows:
            item = self._decode_metadata_json(dict(row))
            chunk_id = int(item.get("chunk_id") or item.get("id") or 0)
            if chunk_id in seen:
                continue
            seen.add(chunk_id)
            raw = float(item.pop("table_bm25", 0.0) or 0.0)
            item["table_score"] = -raw
            item["matched_row"] = item.pop("row_text", "")
            item["matched_row_number"] = int(item.pop("row_number", 0) or 0)
            try:
                item["matched_header"] = json.loads(item.pop("header_json", "[]") or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                item["matched_header"] = []
            try:
                item["matched_cells"] = json.loads(item.pop("cells_json", "[]") or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                item["matched_cells"] = []
            results.append(item)
        return results

    def upsert_knowledge_vector_records(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return
        with self._write_lock, self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO knowledge_vector_records(
                    chunk_id,document_id,library_id,model_name,dimension,backend,text_sha256,indexed_at
                ) VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    document_id=excluded.document_id,
                    library_id=excluded.library_id,
                    model_name=excluded.model_name,
                    dimension=excluded.dimension,
                    backend=excluded.backend,
                    text_sha256=excluded.text_sha256,
                    indexed_at=excluded.indexed_at
                """,
                [
                    (
                        int(row["chunk_id"]), int(row["document_id"]), int(row["library_id"]),
                        str(row["model_name"]), int(row["dimension"]), str(row["backend"]),
                        str(row["text_sha256"]), str(row["indexed_at"]),
                    )
                    for row in records
                ],
            )

    def replace_knowledge_vector_records(
        self, library_id: int, records: list[dict[str, Any]]
    ) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute("DELETE FROM knowledge_vector_records WHERE library_id=?", (library_id,))
            if records:
                conn.executemany(
                    """
                    INSERT INTO knowledge_vector_records(
                        chunk_id,document_id,library_id,model_name,dimension,backend,text_sha256,indexed_at
                    ) VALUES(?,?,?,?,?,?,?,?)
                    """,
                    [
                        (
                            int(row["chunk_id"]), int(row["document_id"]), int(row["library_id"]),
                            str(row["model_name"]), int(row["dimension"]), str(row["backend"]),
                            str(row["text_sha256"]), str(row["indexed_at"]),
                        )
                        for row in records
                    ],
                )

    def delete_knowledge_vector_records(self, chunk_ids: list[int]) -> None:
        ids = sorted({int(value) for value in chunk_ids if int(value) > 0})
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._write_lock, self.connect() as conn:
            conn.execute(
                f"DELETE FROM knowledge_vector_records WHERE chunk_id IN ({placeholders})",
                tuple(ids),
            )

    def knowledge_vector_records(self, library_id: int) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_vector_records WHERE library_id=? ORDER BY chunk_id",
                (library_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_knowledge_index_metadata(
        self,
        library_id: int,
        *,
        embedding_model: str | None,
        embedding_dimension: int | None,
        vector_backend: str | None,
        vector_index_path: Any,
        vector_count: int,
        table_row_count: int,
        status: str,
        error: str | None,
    ) -> None:
        path_value = (
            json.dumps(vector_index_path, ensure_ascii=False, sort_keys=True)
            if isinstance(vector_index_path, (dict, list))
            else (str(vector_index_path) if vector_index_path else None)
        )
        with self._write_lock, self.connect() as conn:
            conn.execute(
                """
                INSERT INTO knowledge_index_metadata(
                    library_id,embedding_model,embedding_dimension,vector_backend,vector_index_path,
                    vector_count,table_row_count,status,error,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(library_id) DO UPDATE SET
                    embedding_model=excluded.embedding_model,
                    embedding_dimension=excluded.embedding_dimension,
                    vector_backend=excluded.vector_backend,
                    vector_index_path=excluded.vector_index_path,
                    vector_count=excluded.vector_count,
                    table_row_count=excluded.table_row_count,
                    status=excluded.status,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    library_id, embedding_model, embedding_dimension, vector_backend, path_value,
                    max(0, int(vector_count)), max(0, int(table_row_count)), status, error, utc_now(),
                ),
            )

    def clear_knowledge_index_metadata(self, library_id: int) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute("DELETE FROM knowledge_index_metadata WHERE library_id=?", (library_id,))

    def list_knowledge_index_metadata(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT m.*,l.name AS library_name
                FROM knowledge_index_metadata m
                JOIN knowledge_libraries l ON l.id=m.library_id
                ORDER BY m.library_id
                """
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            raw = item.get("vector_index_path")
            if raw:
                try:
                    item["vector_index"] = json.loads(raw)
                except (TypeError, ValueError, json.JSONDecodeError):
                    item["vector_index"] = raw
            item.pop("vector_index_path", None)
            result.append(item)
        return result

    def knowledge_retrieval_counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {
                "chunks": int(conn.execute("SELECT COUNT(*) FROM knowledge_chunks").fetchone()[0]),
                "lexical_ready": int(conn.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks WHERE lexical_status='ready'"
                ).fetchone()[0]),
                "vector_ready": int(conn.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks WHERE vector_status='ready'"
                ).fetchone()[0]),
                "vector_error": int(conn.execute(
                    "SELECT COUNT(*) FROM knowledge_chunks WHERE vector_status='error'"
                ).fetchone()[0]),
                "vector_records": int(conn.execute(
                    "SELECT COUNT(*) FROM knowledge_vector_records"
                ).fetchone()[0]),
                "table_rows": int(conn.execute(
                    "SELECT COUNT(*) FROM knowledge_table_rows"
                ).fetchone()[0]),
            }

    def knowledge_counts(self) -> dict[str, int]:
        tables = {
            "libraries": "knowledge_libraries",
            "documents": "knowledge_documents",
            "jobs": "knowledge_ingestion_jobs",
            "parent_blocks": "knowledge_parent_blocks",
            "chunks": "knowledge_chunks",
            "agent_links": "agent_knowledge_libraries",
            "assets": "knowledge_document_assets",
            "table_rows": "knowledge_table_rows",
            "vector_records": "knowledge_vector_records",
        }
        with self.connect() as conn:
            return {
                key: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for key, table in tables.items()
            }

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
                """
                INSERT INTO scripts(
                    title,text,enabled,language,tts_mode,edge_voice,kokoro_voice_id,
                    tts_rate,tts_volume,sort_order,created_at,updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    payload["title"], payload["text"], int(payload.get("enabled", True)),
                    str(payload.get("language") or "en"),
                    str(payload.get("tts_mode") or "edge"),
                    str(payload.get("edge_voice") or "en-US-AriaNeural"),
                    int(payload.get("kokoro_voice_id") or 0),
                    float(payload.get("tts_rate") or 1.0),
                    float(1.0 if payload.get("tts_volume") is None else payload.get("tts_volume")),
                    sort_order, now, now,
                ),
            )
            script_id = int(cur.lastrowid)
        return self.get_script(script_id) or {}

    def update_script(self, script_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE scripts SET title=?,text=?,enabled=?,language=?,tts_mode=?,
                    edge_voice=?,kokoro_voice_id=?,tts_rate=?,tts_volume=?,updated_at=?
                WHERE id=?
                """,
                (
                    payload["title"], payload["text"], int(payload.get("enabled", True)),
                    str(payload.get("language") or "en"),
                    str(payload.get("tts_mode") or "edge"),
                    str(payload.get("edge_voice") or "en-US-AriaNeural"),
                    int(payload.get("kokoro_voice_id") or 0),
                    float(payload.get("tts_rate") or 1.0),
                    float(1.0 if payload.get("tts_volume") is None else payload.get("tts_volume")),
                    utc_now(), script_id,
                ),
            )
            if not cur.rowcount:
                return None
        return self.get_script(script_id)

    def delete_script(self, script_id: int) -> bool:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute("DELETE FROM scripts WHERE id=?", (script_id,))
        return bool(cur.rowcount)

    def queue_script(self, script_id: int, pause_after_seconds: float = 0.0) -> dict[str, Any]:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            position = conn.execute("SELECT COALESCE(MAX(position),-1)+1 FROM script_queue").fetchone()[0]
            cur = conn.execute(
                "INSERT INTO script_queue(script_id,position,status,pause_after_seconds,added_at) VALUES(?,?,?,?,?)",
                (script_id, position, "waiting", max(0.0, min(3600.0, float(pause_after_seconds))), now),
            )
            queue_id = int(cur.lastrowid)
        return self.get_queue_item(queue_id) or {}

    def get_queue_item(self, queue_id: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT q.*,s.title,s.text,s.enabled,s.language,s.tts_mode,s.edge_voice,s.kokoro_voice_id,s.tts_rate,s.tts_volume FROM script_queue q
                JOIN scripts s ON s.id=q.script_id WHERE q.id=?
                """,
                (queue_id,),
            ).fetchone()
        return row_dict(row)

    def list_queue(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT q.*,s.title,s.text,s.enabled,s.language,s.tts_mode,s.edge_voice,s.kokoro_voice_id,s.tts_rate,s.tts_volume FROM script_queue q
                JOIN scripts s ON s.id=q.script_id ORDER BY q.position,q.id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def pop_next_queue_item(self) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as conn:
            row = conn.execute(
                """
                SELECT q.*,s.title,s.text,s.enabled,s.language,s.tts_mode,s.edge_voice,s.kokoro_voice_id,s.tts_rate,s.tts_volume FROM script_queue q
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

    def requeue_queue_item(self, queue_id: int) -> None:
        with self._write_lock, self.connect() as conn:
            position = conn.execute("SELECT COALESCE(MAX(position),-1)+1 FROM script_queue").fetchone()[0]
            conn.execute(
                "UPDATE script_queue SET status='waiting', position=? WHERE id=?",
                (position, queue_id),
            )

    def update_queue_item_pause(self, queue_id: int, pause_after_seconds: float) -> dict[str, Any] | None:
        value = max(0.0, min(3600.0, float(pause_after_seconds)))
        with self._write_lock, self.connect() as conn:
            cur = conn.execute(
                "UPDATE script_queue SET pause_after_seconds=? WHERE id=?",
                (value, queue_id),
            )
            if not cur.rowcount:
                return None
        return self.get_queue_item(queue_id)

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

    # Type-to-talk queue
    def list_type_to_talk_queue(self) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM type_to_talk_queue ORDER BY position,id"
            ).fetchall()
        return [dict(row) for row in rows]

    def _add_type_to_talk_once(self, text: str) -> int:
        now = utc_now()
        with self._write_lock, self.connect() as conn:
            position = conn.execute(
                "SELECT COALESCE(MAX(position),-1)+1 FROM type_to_talk_queue"
            ).fetchone()[0]
            cur = conn.execute(
                "INSERT INTO type_to_talk_queue(text,position,status,created_at) VALUES(?,?,?,?)",
                (str(text).strip(), position, "waiting", now),
            )
            return int(cur.lastrowid)

    @staticmethod
    def _is_type_to_talk_schema_error(exc: sqlite3.DatabaseError) -> bool:
        message = str(exc).lower()
        return "type_to_talk_queue" in message and any(
            marker in message
            for marker in (
                "no column named",
                "no such column",
                "no such table",
                "malformed",
                "schema",
            )
        )

    def repair_type_to_talk_queue(self, *, force_rebuild: bool = True) -> None:
        """Repair direct-speech queue objects without changing schema metadata.

        This is the request-time escape hatch for installations whose migration
        version is already current but whose SQLite objects are not.
        """
        with self._write_lock, self.connect() as conn:
            repair_type_to_talk_queue_schema(conn, force_rebuild=force_rebuild)

    def add_type_to_talk(self, text: str) -> dict[str, Any]:
        try:
            item_id = self._add_type_to_talk_once(text)
        except sqlite3.DatabaseError as exc:
            if not self._is_type_to_talk_schema_error(exc):
                raise
            # Do not require another application restart. Repair the queue from
            # the failing Send request itself, then retry the production INSERT
            # exactly once.
            self.repair_type_to_talk_queue(force_rebuild=True)
            item_id = self._add_type_to_talk_once(text)

        with self.connect() as conn:
            row = conn.execute("SELECT * FROM type_to_talk_queue WHERE id=?", (item_id,)).fetchone()
        return dict(row) if row else {}

    def pop_next_type_to_talk(self) -> dict[str, Any] | None:
        with self._write_lock, self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM type_to_talk_queue WHERE status='waiting' ORDER BY position,id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE type_to_talk_queue SET status='playing' WHERE id=?", (row["id"],))
            result = dict(row)
            result["status"] = "playing"
            return result

    def reset_type_to_talk_playing(self) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute("UPDATE type_to_talk_queue SET status='waiting' WHERE status='playing'")

    def remove_type_to_talk(self, item_id: int) -> bool:
        with self._write_lock, self.connect() as conn:
            cur = conn.execute("DELETE FROM type_to_talk_queue WHERE id=?", (item_id,))
        return bool(cur.rowcount)

    def clear_type_to_talk(self) -> None:
        with self._write_lock, self.connect() as conn:
            conn.execute("DELETE FROM type_to_talk_queue")

    def reorder_type_to_talk(self, ordered_ids: list[int]) -> None:
        with self._write_lock, self.connect() as conn:
            conn.executemany(
                "UPDATE type_to_talk_queue SET position=? WHERE id=?",
                [(index, item_id) for index, item_id in enumerate(ordered_ids)],
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

    def list_recent_messages(
        self,
        conversation_id: int,
        limit: int = 20,
        before_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return the newest messages in chronological order.

        ``list_messages`` intentionally preserves its older API semantics. This
        helper avoids sending the first messages of a long conversation when
        only recent short-term context is required.
        """
        limit = max(1, int(limit))
        with self.connect() as conn:
            if before_id is None:
                rows = conn.execute(
                    """
                    SELECT * FROM messages WHERE conversation_id=?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (conversation_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM messages WHERE conversation_id=? AND id<?
                    ORDER BY id DESC LIMIT ?
                    """,
                    (conversation_id, int(before_id), limit),
                ).fetchall()
        return [dict(row) for row in reversed(rows)]

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

    # Backup / recovery
    def _validate_existing_identity(self) -> None:
        """Refuse to initialize over a database that is clearly not VerbaNode."""
        try:
            with sqlite3.connect(self.path) as conn:
                application_id = int(conn.execute("PRAGMA application_id").fetchone()[0])
                if application_id not in {0, VERBANODE_APPLICATION_ID}:
                    raise MigrationError(
                        "Database application_id belongs to a different application"
                    )
                tables = {
                    str(row[0])
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                # An existing empty SQLite file is safe to initialize. Any populated
                # legacy VerbaNode database must already contain both core tables.
                if tables and not {"settings", "agents"}.issubset(tables):
                    raise MigrationError(
                        "Existing database does not look like a VerbaNode database"
                    )
        except MigrationError:
            raise
        except sqlite3.DatabaseError as exc:
            raise MigrationError("Existing database is not valid SQLite") from exc

    def prune_recovery_backups(self, keep: int | None = None) -> None:
        if keep is None:
            keep = self.settings.recovery_backup_retention_count
        candidates = sorted(
            (
                path
                for path in self.settings.backup_dir.glob("pre-*.db")
                if path.is_file()
            ),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in candidates[max(1, int(keep)) :]:
            stale.unlink(missing_ok=True)

    def schema_version(self) -> int:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return 0
        try:
            with sqlite3.connect(self.path) as conn:
                return read_schema_version(conn)
        except sqlite3.DatabaseError:
            return 0

    def backup_to(self, destination: Path) -> Path:
        """Create a consistent SQLite snapshot, including databases using WAL."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        with self._write_lock:
            source = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
            target = sqlite3.connect(destination)
            try:
                source.execute("PRAGMA busy_timeout=30000")
                source.backup(target)
                target.commit()
                integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise sqlite3.DatabaseError(
                        f"SQLite backup failed integrity check: {integrity}"
                    )
            finally:
                target.close()
                source.close()
        return destination

    def restore_from(self, source_path: Path, safety_path: Path | None = None) -> Path | None:
        """Restore a validated SQLite database using SQLite's online backup API.

        The existing database is snapshotted first when ``safety_path`` is supplied.
        If initialization/migration fails, that snapshot is restored automatically.
        """
        source_path = Path(source_path)
        if not source_path.is_file():
            raise FileNotFoundError(source_path)
        with self._write_lock:
            if safety_path is not None and self.path.exists():
                self.backup_to(safety_path)
            try:
                source = sqlite3.connect(source_path)
                destination = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
                try:
                    source.backup(destination)
                    destination.commit()
                finally:
                    destination.close()
                    source.close()
                self.initialize()
            except Exception:
                if safety_path is not None and Path(safety_path).is_file():
                    recovery = sqlite3.connect(safety_path)
                    destination = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
                    try:
                        recovery.backup(destination)
                        destination.commit()
                    finally:
                        destination.close()
                        recovery.close()
                    self.initialize()
                raise
        return safety_path
