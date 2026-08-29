from __future__ import annotations

import sqlite3
from pathlib import Path

from app.api.client_contract import feature_manifest
from app.config import Settings
from app.db import Database
from app.knowledge import KnowledgeEngine
from app.migrations import CURRENT_SCHEMA_VERSION


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "phase6.db",
        backup_path=tmp_path / "backups",
        knowledge_path=tmp_path / "knowledge",
        open_browser=False,
    )


def _stage_v13_legacy_information(db: Database) -> tuple[int, int]:
    agents = db.list_agents()
    english = next(agent for agent in agents if agent["language"] == "en")
    indonesian = next(agent for agent in agents if agent["language"] == "id")
    now = "2026-01-01T00:00:00+00:00"
    with db.connect() as conn:
        # Remove the fresh-install v14 packaged Knowledge row so this database
        # represents the pre-Phase-6 state we are upgrading from.
        conn.execute("DELETE FROM knowledge_documents")
        conn.execute("DELETE FROM knowledge_libraries")
        conn.execute(
            """
            CREATE TABLE information (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE agent_information (
                agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
                info_id INTEGER NOT NULL REFERENCES information(id) ON DELETE CASCADE,
                PRIMARY KEY(agent_id,info_id)
            )
            """
        )
        rows = [
            ("English only", "ALPHA_PHASE6_EXACT_FACT", 1),
            ("Indonesian only", "BETA_PHASE6_EXACT_FACT", 1),
            ("Disabled shared", "GAMMA_PHASE6_DISABLED_FACT", 0),
            ("Unassigned", "DELTA_PHASE6_UNASSIGNED_FACT", 1),
        ]
        info_ids: list[int] = []
        for title, content, enabled in rows:
            cur = conn.execute(
                "INSERT INTO information(title,content,enabled,created_at,updated_at) VALUES(?,?,?,?,?)",
                (title, content, enabled, now, now),
            )
            info_ids.append(int(cur.lastrowid))
        conn.execute(
            "INSERT INTO agent_information(agent_id,info_id) VALUES(?,?)",
            (english["id"], info_ids[0]),
        )
        conn.execute(
            "INSERT INTO agent_information(agent_id,info_id) VALUES(?,?)",
            (indonesian["id"], info_ids[1]),
        )
        for agent_id in (english["id"], indonesian["id"]):
            conn.execute(
                "INSERT INTO agent_information(agent_id,info_id) VALUES(?,?)",
                (agent_id, info_ids[2]),
            )

        conn.execute("UPDATE settings SET value='13' WHERE key='schema_version'")
        conn.execute("PRAGMA user_version=13")
        conn.execute("DELETE FROM schema_migrations WHERE version=14")
        conn.execute("DELETE FROM settings WHERE key LIKE 'legacy_information_%'")
        conn.execute("DELETE FROM settings WHERE key LIKE 'phase6_static_index_%'")
    return int(english["id"]), int(indonesian["id"])


def test_v14_migrates_every_legacy_row_and_drops_old_tables(tmp_path: Path) -> None:
    db = Database(_settings(tmp_path))
    db.initialize()
    english_id, indonesian_id = _stage_v13_legacy_information(db)

    db.initialize()

    assert db.schema_version() == CURRENT_SCHEMA_VERSION
    assert CURRENT_SCHEMA_VERSION >= 14
    with db.connect() as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
    assert "information" not in tables
    assert "agent_information" not in tables

    documents = [
        item for item in db.list_knowledge_documents()
        if item["source_type"] == "legacy_information"
    ]
    assert len(documents) == 4
    by_title = {item["title"]: item for item in documents}
    assert set(by_title) == {"English only", "Indonesian only", "Disabled shared", "Unassigned"}

    libraries = {item["id"]: item for item in db.list_knowledge_libraries()}
    english = db.get_agent(english_id)
    indonesian = db.get_agent(indonesian_id)
    assert english is not None and indonesian is not None

    english_library = int(by_title["English only"]["library_id"])
    indonesian_library = int(by_title["Indonesian only"]["library_id"])
    disabled_library = int(by_title["Disabled shared"]["library_id"])
    unassigned_library = int(by_title["Unassigned"]["library_id"])

    assert english_library in english["knowledge_library_ids"]
    assert english_library not in indonesian["knowledge_library_ids"]
    assert indonesian_library in indonesian["knowledge_library_ids"]
    assert indonesian_library not in english["knowledge_library_ids"]
    assert disabled_library in english["knowledge_library_ids"]
    assert disabled_library in indonesian["knowledge_library_ids"]
    assert libraries[disabled_library]["enabled"] == 0
    assert libraries[unassigned_library]["agent_count"] == 0

    assert db.get_setting("legacy_information_retired") == "true"
    assert db.get_setting("legacy_information_migrated_count") == "4"
    assert db.get_setting("legacy_information_migrated_libraries") == "4"


def test_migrated_text_is_immediately_bm25_searchable_before_dense_index(tmp_path: Path) -> None:
    db = Database(_settings(tmp_path))
    db.initialize()
    english_id, _indonesian_id = _stage_v13_legacy_information(db)
    db.initialize()

    english = db.get_agent(english_id)
    assert english is not None
    results = db.search_knowledge_lexical(
        '"alpha" OR "phase6" OR "exact" OR "fact"',
        english["knowledge_library_ids"],
        10,
    )
    assert any("ALPHA_PHASE6_EXACT_FACT" in item["text"] for item in results)
    assert not any("BETA_PHASE6_EXACT_FACT" in item["text"] for item in results)


def test_phase6_status_contract_and_fresh_seed_use_only_knowledge(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()
    engine = KnowledgeEngine(db, settings.knowledge_dir)

    status = engine.status()
    features = feature_manifest()
    assert status["phase"] == "legacy_information_migrated"
    assert status["legacy_information_retired"] is True
    assert status["legacy_information_injection_active"] is False
    assert features["knowledge_legacy_information_retired"] is True
    assert features["knowledge_legacy_information_injection"] is False

    documents = db.list_knowledge_documents()
    company = next(item for item in documents if item["title"] == "Sari Teknologi Company Profile")
    assert company["source_type"] == "packaged_default"
    assert all(company["library_id"] in agent["knowledge_library_ids"] for agent in db.list_agents())
    assert not hasattr(db, "list_information")


def test_phase6_dashboard_and_agent_editor_have_no_legacy_information_surface() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    agents_js = (root / "app" / "static" / "js" / "agents.js").read_text(encoding="utf-8")
    app_js = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")

    assert 'data-page="knowledge"' in html
    assert 'id="page-knowledge"' in html
    assert 'data-page="information"' not in html
    assert 'id="agentKnowledgeCheckboxes"' in html
    assert 'id="agentInfoCheckboxes"' not in html
    assert 'name="knowledge_library"' in agents_js
    assert "knowledge_library_ids" in agents_js
    assert "renderKnowledge" in app_js


def test_pre_phase6_agent_update_omission_preserves_knowledge_permissions(tmp_path: Path) -> None:
    from app.schemas import AgentUpdate

    db = Database(_settings(tmp_path))
    db.initialize()
    agent = db.list_agents()[0]
    original = list(agent["knowledge_library_ids"])
    assert original

    # Model an older Android payload: it still sends the full agent form and
    # deprecated info_ids, but has never heard of knowledge_library_ids.
    old_payload = {
        key: value
        for key, value in agent.items()
        if key in AgentUpdate.model_fields and key != "knowledge_library_ids"
    }
    payload = AgentUpdate.model_validate(old_payload)
    assert "knowledge_library_ids" not in payload.model_fields_set

    update = payload.model_dump()
    if "knowledge_library_ids" not in payload.model_fields_set:
        update["knowledge_library_ids"] = None
    saved = db.update_agent(int(agent["id"]), update)
    assert saved is not None
    assert saved["knowledge_library_ids"] == original
