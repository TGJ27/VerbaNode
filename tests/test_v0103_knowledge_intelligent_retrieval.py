from __future__ import annotations

from pathlib import Path

import numpy as np

from app.api.client_contract import feature_manifest
from app.config import Settings
from app.db import Database
from app.knowledge import KnowledgeEngine
from app.knowledge.retrieval import plan_query
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
        5: {"price", "cost", "harga", "650", "120"},
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


def _build(tmp_path: Path) -> tuple[Database, KnowledgeEngine, dict]:
    settings = Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
        knowledge_path=tmp_path / "knowledge",
        open_browser=False,
    )
    db = Database(settings)
    db.initialize()
    engine = KnowledgeEngine(db, settings.knowledge_dir, embedding_provider=KeywordEmbedding())
    library = engine.create_library({"name": "Phase 4", "description": "", "enabled": True})
    return db, engine, library


def _ingest(engine: KnowledgeEngine, library_id: int, source: Path, mime: str | None = None):
    staged = engine.new_upload_path(source.name)
    staged.write_bytes(source.read_bytes())
    document, job = engine.register_staged_upload(
        library_id=library_id,
        staged_path=staged,
        source_name=source.name,
        mime_type=mime,
    )
    return engine.ingest_document(int(document["id"]), int(job["id"]))


def test_phase4_status_manifest_and_schema(tmp_path: Path) -> None:
    db, engine, _library = _build(tmp_path)
    assert APP_VERSION == "0.12.3"
    assert CURRENT_SCHEMA_VERSION >= 14
    assert db.schema_version() == CURRENT_SCHEMA_VERSION

    status = engine.status()
    assert status["phase"] == "legacy_information_migrated"
    assert status["retrieval_chat_enabled"] is True
    assert status["legacy_information_injection_active"] is False
    assert status["capabilities"]["query_routing"] is True
    assert status["capabilities"]["reranking"] is True
    assert status["capabilities"]["confidence_fallback"] is True
    assert status["capabilities"]["deduplication"] is True
    assert status["capabilities"]["hierarchical_context"] is True
    assert status["capabilities"]["chat_integration"] is True

    features = feature_manifest()
    assert features["knowledge_engine_phase"] == "legacy_information_migrated"
    assert features["knowledge_retrieval_api_version"] == 2
    assert features["knowledge_query_routing"] is True
    assert features["knowledge_reranking"] is True
    assert features["knowledge_context_builder"] is True
    assert features["knowledge_chat_integration"] is True


def test_query_router_distinguishes_exact_semantic_and_table_questions() -> None:
    exact = plan_query("What is VN-AE-104?")
    assert exact.intent == "exact"
    assert "VN-AE-104" in exact.identifiers
    assert exact.channel_weights["lexical"] > exact.channel_weights["vector"]

    semantic = plan_query("why does the motor reboot when voltage drops")
    assert semantic.intent == "semantic"
    assert semantic.channel_weights["vector"] > semantic.channel_weights["lexical"]

    table = plan_query("which motor has the lowest current")
    assert table.intent == "table"
    assert table.channel_weights["table"] > table.channel_weights["vector"]


def test_adaptive_reranking_confidence_and_safe_context(tmp_path: Path) -> None:
    _db, engine, library = _build(tmp_path)
    source = tmp_path / "manual.md"
    source.write_text(
        "# Audio\nError VN-AE-104 indicates capture initialization failure.\n\n"
        "# Drive\nA low power condition can restart the shoulder drive controller.\n",
        encoding="utf-8",
    )
    _ingest(engine, int(library["id"]), source, "text/markdown")

    semantic = engine.search(
        "why does the motor reboot when voltage drops",
        top_k=3,
        candidate_k=3,
        context_token_budget=500,
    )
    assert semantic["routing"]["intent"] == "semantic"
    assert "shoulder drive" in semantic["results"][0]["text"].casefold()
    assert semantic["results"][0]["rerank_score"] > semantic["results"][1]["rerank_score"]
    assert semantic["confidence"]["label"] in {"medium", "high"}
    assert semantic["context"]["safe_to_inject"] is True
    assert semantic["context"]["evidence_count"] >= 1
    assert semantic["context"]["estimated_tokens"] <= 500
    assert "[K1]" in semantic["context"]["text"]

    unrelated = engine.search(
        "nonsense unrelated telescope",
        top_k=3,
        candidate_k=3,
        context_token_budget=500,
    )
    assert unrelated["confidence"]["label"] == "low"
    assert unrelated["confidence"]["fallback_used"] is True
    assert unrelated["effective_candidate_k"] > unrelated["candidate_k"]
    assert unrelated["context"]["safe_to_inject"] is False


def test_table_routing_keeps_structured_row_evidence(tmp_path: Path) -> None:
    _db, engine, library = _build(tmp_path)
    source = tmp_path / "products.csv"
    source.write_text(
        "SKU,Name,Voltage,Current,Price\n"
        "XR4-A,Shoulder motor,24 V,8 A,650\n"
        "XR4-B,Head servo,12 V,2 A,120\n",
        encoding="utf-8",
    )
    _ingest(engine, int(library["id"]), source, "text/csv")

    result = engine.search("which motor has the lowest current", top_k=3, candidate_k=10)
    assert result["routing"]["intent"] == "table"
    assert result["channels"]["table_candidates"] >= 1
    assert result["results"][0]["content_type"] == "table"
    assert "table" in result["results"][0]["ranks"]
    assert result["context"]["evidence"][0]["content_type"] == "table"


def test_context_builder_uses_neighbor_expansion_and_respects_budget(tmp_path: Path) -> None:
    _db, engine, library = _build(tmp_path)
    filler_before = " ".join(f"calibration preface word{i}" for i in range(300))
    target = "The XR4 shoulder motor reset threshold is exactly 20 volts under sustained load."
    filler_after = " ".join(f"calibration appendix term{i}" for i in range(500))
    source = tmp_path / "long-manual.md"
    source.write_text(
        "# Motor Calibration\n" + filler_before + "\n\n" + target + "\n\n" + filler_after,
        encoding="utf-8",
    )
    _ingest(engine, int(library["id"]), source, "text/markdown")

    result = engine.search(
        "XR4 shoulder motor reset threshold 20 volts",
        top_k=4,
        candidate_k=12,
        context_top_k=3,
        context_token_budget=420,
        neighbor_window=1,
    )
    assert result["context"]["estimated_tokens"] <= 420
    assert result["context"]["evidence_count"] >= 1
    assert any(item["expansion"] in {"neighbors", "matched_chunk"} for item in result["context"]["evidence"])
    assert "20 volts" in result["context"]["text"].casefold()


def test_near_duplicate_chunks_from_same_document_are_suppressed(tmp_path: Path) -> None:
    _db, engine, library = _build(tmp_path)
    repeated = (
        "Calibration torque seventeen newton meters. "
        "Disconnect power before adjustment and verify the shoulder motor encoder alignment."
    )
    source = tmp_path / "duplicates.md"
    source.write_text(
        f"# Procedure A\n{repeated}\n\n# Procedure B\n{repeated}\n",
        encoding="utf-8",
    )
    _ingest(engine, int(library["id"]), source, "text/markdown")

    result = engine.search("calibration torque seventeen newton meters", top_k=10, candidate_k=20)
    matches = [
        item for item in result["results"] if "seventeen newton meters" in item["text"].casefold()
    ]
    assert len(matches) == 1


def test_ci_installs_knowledge_ingestion_dependencies_on_clean_runner() -> None:
    root = Path(__file__).resolve().parents[1]
    dev = (root / "requirements-dev.txt").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    for requirement in (
        "python-docx>=1.1,<2.0",
        "openpyxl>=3.1,<4.0",
        "python-pptx>=1.0,<2.0",
        "pdfplumber>=0.11,<1.0",
        "reportlab>=4.2,<5.0",
    ):
        assert requirement in dev
    assert "pip install -r requirements-dev.txt soundfile sounddevice" in workflow
