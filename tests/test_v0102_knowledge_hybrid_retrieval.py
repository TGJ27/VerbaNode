from __future__ import annotations

from pathlib import Path

import numpy as np

from app.api.client_contract import feature_manifest
from app.config import Settings
from app.db import Database
from app.knowledge import KnowledgeEngine
from app.knowledge.retrieval import EmbeddingUnavailable
from app.migrations import CURRENT_SCHEMA_VERSION
from app.version import APP_VERSION


class KeywordEmbedding:
    name = "test-multilingual-e5"
    dimension = 8

    _groups = {
        0: {"motor", "drive", "shoulder"},
        1: {"microphone", "capture", "audio", "mic"},
        2: {"reset", "restart", "reboot"},
        3: {"voltage", "volt", "24", "power"},
        4: {"servo", "head"},
        5: {"price", "cost", "650", "120"},
        6: {"error", "failure", "failed"},
    }

    def _one(self, text: str) -> np.ndarray:
        value = text.casefold()
        vector = np.zeros(self.dimension, dtype=np.float32)
        for index, words in self._groups.items():
            for word in words:
                if word in value:
                    vector[index] += 1.0
        vector[7] = 0.01
        norm = float(np.linalg.norm(vector)) or 1.0
        return vector / norm

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._one(text) for text in texts], axis=0)

    def embed_query(self, text: str) -> np.ndarray:
        return self._one(text)


class BrokenEmbedding:
    name = "broken-test-embedding"
    dimension = 8

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        raise EmbeddingUnavailable("test embedding runtime unavailable")

    def embed_query(self, text: str) -> np.ndarray:
        raise EmbeddingUnavailable("test embedding runtime unavailable")


def _build(tmp_path: Path, provider=None) -> tuple[Database, KnowledgeEngine]:
    settings = Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
        knowledge_path=tmp_path / "knowledge",
        open_browser=False,
    )
    db = Database(settings)
    db.initialize()
    engine = KnowledgeEngine(
        db,
        settings.knowledge_dir,
        embedding_provider=provider or KeywordEmbedding(),
    )
    return db, engine


def _ingest_text(
    engine: KnowledgeEngine,
    library_id: int,
    tmp_path: Path,
    filename: str,
    text: str,
):
    source = tmp_path / filename
    source.write_text(text, encoding="utf-8")
    staged = engine.new_upload_path(source.name)
    staged.write_bytes(source.read_bytes())
    document, job = engine.register_staged_upload(
        library_id=library_id,
        staged_path=staged,
        source_name=source.name,
        mime_type="text/plain",
    )
    result = engine.ingest_document(int(document["id"]), int(job["id"]))
    return result


def test_phase3_schema_manifest_and_status(tmp_path: Path) -> None:
    db, engine = _build(tmp_path)
    assert APP_VERSION == "0.12.6"
    assert CURRENT_SCHEMA_VERSION >= 14
    assert db.schema_version() == CURRENT_SCHEMA_VERSION

    with db.connect() as conn:
        objects = {
            (row[0], row[1])
            for row in conn.execute(
                "SELECT name,type FROM sqlite_master WHERE name LIKE 'knowledge_%'"
            ).fetchall()
        }
    assert ("knowledge_chunks_fts", "table") in objects
    assert ("knowledge_table_rows", "table") in objects
    assert ("knowledge_table_rows_fts", "table") in objects
    assert ("knowledge_vector_records", "table") in objects
    assert ("knowledge_index_metadata", "table") in objects

    status = engine.status()
    assert status["phase"] == "legacy_information_migrated"
    assert status["retrieval_enabled"] is True
    assert status["retrieval_chat_enabled"] is True
    assert status["legacy_information_injection_active"] is False
    assert status["capabilities"]["bm25"] is True
    assert status["capabilities"]["vector_search"] is True
    assert status["capabilities"]["structured_table_search"] is True
    assert status["capabilities"]["rrf"] is True
    assert status["capabilities"]["reranking"] is True
    assert status["capabilities"]["vlm"] is False

    features = feature_manifest()
    assert features["knowledge_engine_phase"] == "legacy_information_migrated"
    assert features["knowledge_retrieval"] is True
    assert features["knowledge_chat_integration"] is True


def test_hybrid_search_combines_exact_bm25_and_dense_semantics(tmp_path: Path) -> None:
    _db, engine = _build(tmp_path)
    library = engine.create_library({"name": "XR4", "description": "", "enabled": True})
    _ingest_text(
        engine,
        int(library["id"]),
        tmp_path,
        "manual.md",
        "# Audio\nError VN-AE-104 indicates capture initialization failure.\n\n"
        "# Drive\nA low power condition can restart the shoulder drive controller.",
    )

    exact = engine.search("VN-AE-104", mode="hybrid", top_k=3)
    assert exact["channels"]["lexical_candidates"] >= 1
    assert "VN-AE-104" in exact["results"][0]["text"]
    assert "lexical" in exact["results"][0]["ranks"]

    semantic = engine.search("why does the motor reboot when voltage drops", mode="hybrid", top_k=3)
    assert semantic["channels"]["vector_candidates"] >= 1
    assert "shoulder drive" in semantic["results"][0]["text"].lower()
    assert "vector" in semantic["results"][0]["ranks"]


def test_agent_library_filter_is_applied_before_retrieval(tmp_path: Path) -> None:
    db, engine = _build(tmp_path)
    agent = db.list_agents()[0]
    allowed = engine.create_library({"name": "Allowed", "description": "", "enabled": True})
    blocked = engine.create_library({"name": "Blocked", "description": "", "enabled": True})
    _ingest_text(engine, int(allowed["id"]), tmp_path, "allowed.txt", "motor reset procedure alpha")
    _ingest_text(engine, int(blocked["id"]), tmp_path, "blocked.txt", "motor reset procedure secret beta")
    engine.set_agent_libraries(int(agent["id"]), [int(allowed["id"])])

    result = engine.search("motor reset procedure", agent_id=int(agent["id"]), top_k=10)
    assert result["library_ids"] == [int(allowed["id"])]
    assert result["results"]
    assert all(int(item["library_id"]) == int(allowed["id"]) for item in result["results"])
    assert not any("secret beta" in item["text"] for item in result["results"])


def test_structured_table_rows_are_indexed_and_returned(tmp_path: Path) -> None:
    _db, engine = _build(tmp_path)
    library = engine.create_library({"name": "Catalog", "description": "", "enabled": True})
    csv_path = tmp_path / "products.csv"
    csv_path.write_text(
        "SKU,Name,Price\nXR4-A,Shoulder motor,650\nXR4-B,Head servo,120\n",
        encoding="utf-8",
    )
    staged = engine.new_upload_path(csv_path.name)
    staged.write_bytes(csv_path.read_bytes())
    document, job = engine.register_staged_upload(
        library_id=int(library["id"]),
        staged_path=staged,
        source_name=csv_path.name,
        mime_type="text/csv",
    )
    engine.ingest_document(int(document["id"]), int(job["id"]))

    result = engine.search("XR4-B 120", mode="table", top_k=3)
    assert result["channels"]["table_candidates"] == 1
    first = result["results"][0]
    assert first["content_type"] == "table"
    assert first["matched_header"] == ["SKU", "Name", "Price"]
    assert first["matched_cells"] == ["XR4-B", "Head servo", "120"]
    assert "Price: 120" in first["matched_row"]


def test_reingest_removes_old_vector_membership_and_replaces_searchable_content(tmp_path: Path) -> None:
    db, engine = _build(tmp_path)
    library = engine.create_library({"name": "Repair", "description": "", "enabled": True})
    document = _ingest_text(
        engine,
        int(library["id"]),
        tmp_path,
        "repair.txt",
        "motor reset after low voltage",
    )
    document_id = int(document["id"])
    old_ids = set(db.knowledge_chunk_ids(document_id))
    assert old_ids

    stored = engine.root / document["storage_key"]
    stored.write_text("microphone capture startup procedure", encoding="utf-8")
    job = engine.reingest_document(document_id)
    engine.ingest_document(document_id, int(job["id"]))
    new_ids = set(db.knowledge_chunk_ids(document_id))
    assert new_ids
    assert old_ids.isdisjoint(new_ids)

    records = db.knowledge_vector_records(int(library["id"]))
    assert {int(row["chunk_id"]) for row in records} == new_ids
    result = engine.search("motor reset voltage", mode="hybrid", top_k=10)
    assert not any("motor reset" in item["text"].lower() for item in result["results"])


def test_dense_failure_keeps_bm25_search_available(tmp_path: Path) -> None:
    _db, engine = _build(tmp_path, provider=BrokenEmbedding())
    library = engine.create_library({"name": "Offline", "description": "", "enabled": True})
    document = _ingest_text(
        engine,
        int(library["id"]),
        tmp_path,
        "offline.txt",
        "Error VN-AE-104 indicates capture initialization failure.",
    )
    assert document["status"] == "parsed"
    assert document["metadata"]["retrieval_indexed"] is False
    assert "test embedding runtime unavailable" in document["metadata"]["retrieval_error"]

    result = engine.search("VN-AE-104", mode="hybrid", top_k=3)
    assert result["channels"]["lexical_candidates"] >= 1
    assert result["channels"]["vector_candidates"] == 0
    assert any("Dense retrieval unavailable" in warning for warning in result["warnings"])
    assert "VN-AE-104" in result["results"][0]["text"]


def test_phase3_full_install_and_windows_bundle_include_dense_runtime() -> None:
    requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(
        encoding="utf-8"
    )
    spec = (Path(__file__).resolve().parents[1] / "packaging" / "VerbaNode.spec").read_text(
        encoding="utf-8"
    )
    assert "fastembed>=0.8,<0.9" in requirements
    assert "usearch>=2.25,<3.0" in requirements
    assert '"fastembed"' in spec
    assert '"usearch"' in spec
