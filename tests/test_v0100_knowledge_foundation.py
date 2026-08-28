from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from app.api.client_contract import feature_manifest
from app.config import Settings
from app.db import Database
from app.knowledge import KnowledgeEngine, KnowledgeEngineConflict, KnowledgeEngineNotFound
from app.migrations import CURRENT_SCHEMA_VERSION
from app.version import APP_VERSION


def _build(tmp_path: Path) -> tuple[Database, KnowledgeEngine]:
    settings = Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
        knowledge_path=tmp_path / "knowledge",
        open_browser=False,
    )
    db = Database(settings)
    db.initialize()
    return db, KnowledgeEngine(db, settings.knowledge_dir)


def test_v0100_schema_and_local_layout_foundation(tmp_path: Path) -> None:
    db, engine = _build(tmp_path)

    assert APP_VERSION == "0.10.3"
    assert CURRENT_SCHEMA_VERSION == 13
    assert db.schema_version() == 13
    for directory in (engine.root, engine.sources_dir, engine.assets_dir, engine.indexes_dir, engine.cache_dir):
        assert directory.is_dir()

    with sqlite3.connect(db.path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    assert {
        "knowledge_libraries",
        "knowledge_documents",
        "knowledge_ingestion_jobs",
        "knowledge_parent_blocks",
        "knowledge_chunks",
        "agent_knowledge_libraries",
        "knowledge_document_assets",
    } <= tables

    status = engine.status()
    features = feature_manifest()
    assert features["knowledge_engine"] is True
    assert features["knowledge_engine_phase"] == "intelligent_retrieval"
    assert features["knowledge_retrieval"] is True
    assert status["backend"] == "local"
    assert status["phase"] == "intelligent_retrieval"
    assert status["ingestion_enabled"] is True
    assert status["retrieval_enabled"] is True
    assert status["legacy_information_injection_active"] is True
    assert status["counts"]["libraries"] == 0


def test_v0100_library_crud_and_case_insensitive_uniqueness(tmp_path: Path) -> None:
    _db, engine = _build(tmp_path)

    created = engine.create_library(
        {"name": "XR4 Manuals", "description": "Robot service documentation", "enabled": True}
    )
    assert created["name"] == "XR4 Manuals"
    assert created["document_count"] == 0
    assert created["agent_count"] == 0

    with pytest.raises(KnowledgeEngineConflict, match="already exists"):
        engine.create_library(
            {"name": "xr4 manuals", "description": "duplicate", "enabled": True}
        )

    updated = engine.update_library(
        created["id"],
        {"name": "XR4 Documentation", "description": "Manuals and bulletins", "enabled": False},
    )
    assert updated["enabled"] == 0
    assert updated["description"] == "Manuals and bulletins"

    engine.delete_library(created["id"])
    with pytest.raises(KnowledgeEngineNotFound):
        engine.get_library(created["id"])


def test_v0100_document_job_hierarchy_metadata_is_ready_for_phase2(tmp_path: Path) -> None:
    db, engine = _build(tmp_path)
    library = engine.create_library(
        {"name": "Engineering", "description": "", "enabled": True}
    )
    document = engine.register_document(
        {
            "library_id": library["id"],
            "title": "XR4 Service Manual",
            "source_name": "xr4-service.pdf",
            "source_type": "pdf",
            "mime_type": "application/pdf",
            "storage_key": "sources/1/original.pdf",
            "size_bytes": 123456,
            "sha256": "a" * 64,
            "metadata": {"language": "en", "pages": 120},
        }
    )
    assert document["status"] == "registered"
    assert document["metadata"] == {"language": "en", "pages": 120}

    job = engine.create_job(document["id"])
    assert job["status"] == "queued"
    assert job["stage"] == "queued"
    assert job["progress"] == 0.0

    parent = db.add_knowledge_parent_block(
        {
            "document_id": document["id"],
            "block_type": "section",
            "ordinal": 3,
            "heading_path": "Electrical > Motor Controller",
            "page_start": 42,
            "page_end": 44,
            "text": "Motor controller section",
            "metadata": {"heading_level": 2},
        }
    )
    chunk = db.add_knowledge_chunk(
        {
            "document_id": document["id"],
            "parent_block_id": parent["id"],
            "ordinal": 0,
            "content_type": "text",
            "text": "The left drive controller uses a 24 V supply.",
            "token_count": 11,
            "page_start": 42,
            "page_end": 42,
            "metadata": {"section": "Motor Controller"},
        }
    )
    assert parent["metadata"] == {"heading_level": 2}
    assert chunk["lexical_status"] == "pending"
    assert chunk["vector_status"] == "pending"
    assert chunk["metadata"] == {"section": "Motor Controller"}

    status = engine.status()
    assert status["counts"]["documents"] == 1
    assert status["counts"]["jobs"] == 1
    assert status["counts"]["parent_blocks"] == 1
    assert status["counts"]["chunks"] == 1

    with pytest.raises(KnowledgeEngineConflict, match="contains documents"):
        engine.delete_library(library["id"])


def test_v0100_agent_library_permissions_are_explicit_and_validated(tmp_path: Path) -> None:
    db, engine = _build(tmp_path)
    agent = db.list_agents()[0]
    first = engine.create_library({"name": "Manuals", "description": "", "enabled": True})
    second = engine.create_library({"name": "Policies", "description": "", "enabled": True})

    selected = engine.set_agent_libraries(agent["id"], [second["id"], first["id"], second["id"]])
    assert selected == sorted([first["id"], second["id"]])
    assert engine.agent_library_ids(agent["id"]) == selected
    assert db.get_agent(agent["id"])["knowledge_library_ids"] == selected

    with pytest.raises(KnowledgeEngineNotFound, match="Knowledge library not found"):
        engine.set_agent_libraries(agent["id"], [999999])
    with pytest.raises(KnowledgeEngineNotFound, match="Agent not found"):
        engine.set_agent_libraries(999999, [first["id"]])

    engine.delete_library(first["id"])
    assert engine.agent_library_ids(agent["id"]) == [second["id"]]


def test_v0100_public_router_is_registered_without_replacing_legacy_information() -> None:
    root = Path(__file__).resolve().parents[1]
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    api = (root / "app" / "api" / "knowledge.py").read_text(encoding="utf-8")
    prompts = (root / "app" / "services" / "prompts.py").read_text(encoding="utf-8")

    assert "app.include_router(knowledge_router)" in main
    assert '@router.get("/status")' in api
    assert '@router.post("/libraries")' in api
    assert '@router.put("/agents/{agent_id}/libraries")' in api
    # Phase 1 is additive: prompt cutover/migration happens in later phases.
    assert "information" in prompts.lower()
