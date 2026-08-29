from __future__ import annotations

from pathlib import Path

from app.api.client_contract import feature_manifest
from app.config import Settings
from app.db import Database
from app.knowledge import KnowledgeEngine
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


def test_phase7_text_documents_are_editable_and_lexically_ready(tmp_path: Path) -> None:
    db, engine = _build(tmp_path)
    library = engine.create_library({"name": "Phase 7", "description": "", "enabled": True})

    document = engine.create_text_document(
        library["id"], title="Motor reset note", text="VN-AE-104 can appear after an undervoltage reset."
    )
    assert document["source_type"] == "manual_text"
    chunks = db.list_knowledge_chunks(document["id"])
    assert chunks
    assert all(chunk["lexical_status"] == "ready" for chunk in chunks)

    result = engine.search("VN-AE-104", library_ids=[library["id"]], mode="lexical")
    assert result["results"]
    assert result["results"][0]["document_title"] == "Motor reset note"

    updated = engine.update_text_document(
        document["id"], title="Motor voltage note", text="XR4 shoulder motor nominal voltage is 24 V."
    )
    assert updated["title"] == "Motor voltage note"
    result = engine.search("shoulder motor 24 V", library_ids=[library["id"]], mode="lexical")
    assert any(item["document_title"] == "Motor voltage note" for item in result["results"])


def test_phase7_management_contract_and_fixed_knowledge_workspace() -> None:
    root = Path(__file__).resolve().parents[1]
    main = (root / "app/main.py").read_text(encoding="utf-8")
    api = (root / "app/api/knowledge.py").read_text(encoding="utf-8")
    html = (root / "app/static/index.html").read_text(encoding="utf-8")
    css = (root / "app/static/styles.css").read_text(encoding="utf-8")
    js = (root / "app/static/js/knowledge.js").read_text(encoding="utf-8")
    features = feature_manifest()

    assert APP_VERSION == "0.12.0"
    assert features["knowledge_management"] is True
    assert features["knowledge_background_indexing"] is True
    assert features["knowledge_text_documents"] is True

    # Dense migration indexing is scheduled after startup instead of awaited by startup.
    assert "asyncio.create_task(_finalize_knowledge_index_background())" in main
    assert "phase6_index = await asyncio.to_thread(state.knowledge.finalize_phase6_static_index)" not in main

    assert '@router.post("/libraries/{library_id}/text-documents")' in api
    assert '@router.put("/documents/{document_id}/text")' in api
    assert '@router.get("/documents/{document_id}/source")' in api

    assert 'id="knowledgeLibraryList"' in html
    assert 'id="knowledgeDocumentList"' in html
    assert 'id="knowledgeSearchInput"' in html
    assert '/static/js/knowledge.js?v=0.12.0' in html
    assert '#page-knowledge.active { height:100%; overflow:hidden;' in css
    assert "knowledgePageSlice" in js
    assert "uploadKnowledgeFiles" in js
    assert "runKnowledgeSearch" in js
