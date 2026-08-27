from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from app.db import Database


class KnowledgeEngineNotFound(LookupError):
    """Requested Knowledge Engine object does not exist."""


class KnowledgeEngineConflict(RuntimeError):
    """Requested Knowledge Engine change conflicts with persisted state."""


class KnowledgeEngine:
    """Local metadata/storage boundary for the phased RAG implementation.

    Phase 1 intentionally does not parse documents or perform retrieval.  All
    callers use this service rather than accessing future FTS/vector backends
    directly, which leaves room for a remote Knowledge backend later without
    changing Chat/Agent APIs.
    """

    FOUNDATION_VERSION = 1
    IMPLEMENTATION_PHASE = "foundation"

    def __init__(self, db: Database, root: Path):
        self.db = db
        self.root = Path(root)
        self.sources_dir = self.root / "sources"
        self.indexes_dir = self.root / "indexes"
        self.cache_dir = self.root / "cache"
        self.initialize_layout()

    def initialize_layout(self) -> None:
        for path in (self.root, self.sources_dir, self.indexes_dir, self.cache_dir):
            path.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        return {
            "engine_version": self.FOUNDATION_VERSION,
            "phase": self.IMPLEMENTATION_PHASE,
            "backend": "local",
            "ingestion_enabled": False,
            "retrieval_enabled": False,
            "legacy_information_injection_active": True,
            "counts": self.db.knowledge_counts(),
            "capabilities": {
                "libraries": True,
                "document_metadata": True,
                "ingestion_jobs": True,
                "hierarchical_blocks": True,
                "agent_library_permissions": True,
                "parsing": False,
                "ocr": False,
                "bm25": False,
                "embeddings": False,
                "vector_search": False,
                "reranking": False,
                "chat_integration": False,
            },
        }

    def list_libraries(self) -> list[dict[str, Any]]:
        return self.db.list_knowledge_libraries()

    def get_library(self, library_id: int) -> dict[str, Any]:
        item = self.db.get_knowledge_library(library_id)
        if not item:
            raise KnowledgeEngineNotFound("Knowledge library not found")
        return item

    def create_library(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.db.create_knowledge_library(payload)
        except sqlite3.IntegrityError as exc:
            if "knowledge_libraries.name" in str(exc) or "UNIQUE constraint failed" in str(exc):
                raise KnowledgeEngineConflict("A knowledge library with this name already exists") from exc
            raise

    def update_library(self, library_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            item = self.db.update_knowledge_library(library_id, payload)
        except sqlite3.IntegrityError as exc:
            if "knowledge_libraries.name" in str(exc) or "UNIQUE constraint failed" in str(exc):
                raise KnowledgeEngineConflict("A knowledge library with this name already exists") from exc
            raise
        if not item:
            raise KnowledgeEngineNotFound("Knowledge library not found")
        return item

    def delete_library(self, library_id: int) -> None:
        library = self.get_library(library_id)
        if int(library.get("document_count") or 0) > 0:
            raise KnowledgeEngineConflict(
                "Knowledge library contains documents; document deletion is introduced in Phase 2"
            )
        if not self.db.delete_knowledge_library(library_id):
            raise KnowledgeEngineNotFound("Knowledge library not found")

    def list_documents(self, library_id: int | None = None) -> list[dict[str, Any]]:
        if library_id is not None:
            self.get_library(library_id)
        return self.db.list_knowledge_documents(library_id)

    def get_document(self, document_id: int) -> dict[str, Any]:
        item = self.db.get_knowledge_document(document_id)
        if not item:
            raise KnowledgeEngineNotFound("Knowledge document not found")
        return item

    def register_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Internal Phase-1 primitive used by the Phase-2 ingestion pipeline."""
        self.get_library(int(payload["library_id"]))
        return self.db.register_knowledge_document(payload)

    def list_jobs(self, document_id: int | None = None) -> list[dict[str, Any]]:
        if document_id is not None:
            self.get_document(document_id)
        return self.db.list_knowledge_ingestion_jobs(document_id)

    def create_job(self, document_id: int, *, job_type: str = "ingest") -> dict[str, Any]:
        self.get_document(document_id)
        return self.db.create_knowledge_ingestion_job(document_id, job_type=job_type)

    def agent_library_ids(self, agent_id: int) -> list[int]:
        if not self.db.get_agent(agent_id):
            raise KnowledgeEngineNotFound("Agent not found")
        return self.db.knowledge_library_ids_for_agent(agent_id)

    def set_agent_libraries(self, agent_id: int, library_ids: list[int]) -> list[int]:
        try:
            return self.db.set_agent_knowledge_libraries(agent_id, library_ids)
        except LookupError as exc:
            raise KnowledgeEngineNotFound(str(exc)) from exc
        except ValueError as exc:
            raise KnowledgeEngineNotFound(str(exc)) from exc
