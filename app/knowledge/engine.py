from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.db import Database
from app.knowledge.ingestion import (
    KnowledgeIngestionError,
    normalize_result,
    ocr_available,
    parse_document,
    safe_filename,
    source_sha256,
    supported_formats,
)
from app.knowledge.retrieval import (
    EmbeddingProvider,
    HybridRetriever,
    KnowledgeRetrievalError,
    LocalVectorIndex,
)


class KnowledgeEngineNotFound(LookupError):
    """Requested Knowledge Engine object does not exist."""


class KnowledgeEngineConflict(RuntimeError):
    """Requested Knowledge Engine change conflicts with persisted state."""


class KnowledgeEngineValidation(ValueError):
    """Uploaded knowledge source does not satisfy ingestion rules."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class KnowledgeEngine:
    """Local-first Knowledge Engine service boundary.

    v0.11.0 / Phase 5 connects the intelligent hybrid retrieval pipeline to
    Chat, typed PTT, browser PTT, and continuous Voice through the shared
    ConversationManager. Legacy Information records are retained only for the
    Phase-6 migration and are no longer injected into prompts.
    """

    FOUNDATION_VERSION = 5
    IMPLEMENTATION_PHASE = "chat_voice_cutover"

    def __init__(
        self,
        db: Database,
        root: Path,
        *,
        max_upload_bytes: int = 1073741824,
        embedding_threads: int = 2,
        embedding_provider: EmbeddingProvider | None = None,
        vector_index: LocalVectorIndex | None = None,
    ):
        self.db = db
        self.root = Path(root)
        self.max_upload_bytes = max(1024 * 1024, int(max_upload_bytes))
        self.sources_dir = self.root / "sources"
        self.assets_dir = self.root / "assets"
        self.indexes_dir = self.root / "indexes"
        self.cache_dir = self.root / "cache"
        self.upload_cache_dir = self.cache_dir / "uploads"
        self.initialize_layout()
        self.retrieval = HybridRetriever(
            self.db,
            self.indexes_dir,
            self.cache_dir,
            embedding_provider=embedding_provider,
            vector_index=vector_index,
            embedding_threads=embedding_threads,
        )

    def initialize_layout(self) -> None:
        for path in (
            self.root,
            self.sources_dir,
            self.assets_dir,
            self.indexes_dir,
            self.cache_dir,
            self.upload_cache_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def status(self) -> dict[str, Any]:
        retrieval = self.retrieval.status()
        return {
            "engine_version": self.FOUNDATION_VERSION,
            "phase": self.IMPLEMENTATION_PHASE,
            "backend": "local",
            "ingestion_enabled": True,
            "retrieval_enabled": True,
            "retrieval_chat_enabled": True,
            "legacy_information_injection_active": False,
            "counts": self.db.knowledge_counts(),
            "retrieval": retrieval,
            "supported_formats": supported_formats(),
            "max_upload_bytes": self.max_upload_bytes,
            "capabilities": {
                "libraries": True,
                "document_metadata": True,
                "ingestion_jobs": True,
                "hierarchical_blocks": True,
                "agent_library_permissions": True,
                "parsing": True,
                "ocr": ocr_available(),
                "tables": True,
                "native_pdf": True,
                "native_docx": True,
                "native_xlsx": True,
                "native_pptx": True,
                "images_without_vlm": True,
                "vlm": False,
                "bm25": True,
                "embeddings": True,
                "embedding_model": retrieval["embedding_model"],
                "vector_search": True,
                "hnsw": bool(retrieval["hnsw_available"]),
                "structured_table_search": True,
                "rrf": True,
                "query_routing": True,
                "reranking": True,
                "confidence_fallback": True,
                "deduplication": True,
                "hierarchical_context": True,
                "chat_integration": True,
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
            raise KnowledgeEngineConflict("Knowledge library contains documents; delete its documents first")
        if not self.db.delete_knowledge_library(library_id):
            raise KnowledgeEngineNotFound("Knowledge library not found")
        self.retrieval.delete_library_index(library_id)

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
        self.get_library(int(payload["library_id"]))
        return self.db.register_knowledge_document(payload)

    def new_upload_path(self, source_name: str) -> Path:
        extension = Path(source_name or "").suffix.lower()
        if extension not in set(supported_formats()):
            raise KnowledgeEngineValidation(
                f"Unsupported knowledge file type: {extension or 'unknown'}"
            )
        return self.upload_cache_dir / f"{uuid.uuid4().hex}{extension}"

    def register_staged_upload(
        self,
        *,
        library_id: int,
        staged_path: Path,
        source_name: str,
        mime_type: str | None,
        title: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self.get_library(library_id)
        staged_path = Path(staged_path)
        if not staged_path.exists():
            raise KnowledgeEngineValidation("Staged knowledge upload was not found")
        size = staged_path.stat().st_size
        if size <= 0:
            raise KnowledgeEngineValidation("Knowledge document is empty")
        if size > self.max_upload_bytes:
            raise KnowledgeEngineValidation(
                f"Knowledge document exceeds the {self.max_upload_bytes} byte upload limit"
            )
        source_name = safe_filename(source_name)
        extension = Path(source_name).suffix.lower()
        if extension not in set(supported_formats()):
            raise KnowledgeEngineValidation(f"Unsupported knowledge file type: {extension or 'unknown'}")
        digest = source_sha256(staged_path)
        folder = self.sources_dir / str(library_id) / uuid.uuid4().hex
        folder.mkdir(parents=True, exist_ok=False)
        destination = folder / source_name
        try:
            shutil.move(str(staged_path), destination)
            storage_key = destination.relative_to(self.root).as_posix()
            document = self.register_document(
                {
                    "library_id": library_id,
                    "title": (title or Path(source_name).stem or source_name).strip()[:240],
                    "source_name": source_name,
                    "source_type": extension.lstrip(".") or "unknown",
                    "mime_type": mime_type,
                    "storage_key": storage_key,
                    "size_bytes": size,
                    "sha256": digest,
                    "status": "queued",
                    "metadata": {
                        "phase": 2,
                        "original_extension": extension,
                        "source_sha256": digest,
                    },
                }
            )
            job = self.create_job(int(document["id"]))
            return document, job
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise

    def _resolve_storage_key(self, storage_key: str | None) -> Path:
        if not storage_key:
            raise KnowledgeEngineValidation("Knowledge document has no stored source file")
        target = (self.root / storage_key).resolve()
        root = self.root.resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise KnowledgeEngineValidation("Knowledge document storage path is invalid") from exc
        if not target.is_file():
            raise KnowledgeEngineValidation("Knowledge document source file is missing")
        return target

    def list_jobs(self, document_id: int | None = None) -> list[dict[str, Any]]:
        if document_id is not None:
            self.get_document(document_id)
        return self.db.list_knowledge_ingestion_jobs(document_id)

    def create_job(self, document_id: int, *, job_type: str = "ingest") -> dict[str, Any]:
        self.get_document(document_id)
        return self.db.create_knowledge_ingestion_job(document_id, job_type=job_type)

    def ingest_document(self, document_id: int, job_id: int | None = None) -> dict[str, Any]:
        """Parse one stored source and persist normalized blocks/chunks/assets.

        This method is synchronous so FastAPI BackgroundTasks runs it in its
        threadpool instead of blocking the event loop. It is also directly
        callable by tests, repair tools, and a future durable worker process.
        """
        document = self.get_document(document_id)
        if job_id is None:
            job = self.create_job(document_id)
            job_id = int(job["id"])
        job = self.db.get_knowledge_ingestion_job(job_id)
        if not job or int(job.get("document_id") or 0) != document_id:
            raise KnowledgeEngineNotFound("Knowledge ingestion job not found")
        attempts = int(job.get("attempts") or 0) + 1
        self.db.update_knowledge_ingestion_job(
            job_id,
            status="running",
            stage="parsing",
            progress=0.12,
            attempts=attempts,
            started_at=_utc_now(),
            error=None,
        )
        self.db.update_knowledge_document_status(document_id, status="parsing", error=None)
        source = self._resolve_storage_key(document.get("storage_key"))
        asset_dir = self.assets_dir / str(document_id)
        shutil.rmtree(asset_dir, ignore_errors=True)
        asset_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = parse_document(source, asset_dir)
            if not result.blocks and not result.assets:
                raise KnowledgeIngestionError("No extractable text, tables, or OCR content was found")
            self.db.update_knowledge_ingestion_job(
                job_id,
                status="running",
                stage="normalizing",
                progress=0.64,
                attempts=attempts,
                error=None,
            )
            blocks = normalize_result(result)
            assets: list[dict[str, Any]] = []
            for asset in result.assets:
                storage_key = asset.storage_key
                if storage_key:
                    candidate = asset_dir / storage_key
                    if candidate.exists():
                        storage_key = candidate.relative_to(self.root).as_posix()
                elif asset.metadata.get("source_image"):
                    storage_key = str(document.get("storage_key") or "")
                assets.append(
                    {
                        "asset_type": asset.asset_type,
                        "mime_type": asset.mime_type,
                        "storage_key": storage_key,
                        "label": asset.label,
                        "page_start": asset.page_start,
                        "page_end": asset.page_end,
                        "ocr_text": asset.ocr_text,
                        "metadata": asset.metadata,
                        "parent_ordinal": asset.parent_ordinal,
                    }
                )
            self.db.update_knowledge_ingestion_job(
                job_id,
                status="running",
                stage="persisting",
                progress=0.82,
                attempts=attempts,
                error=None,
            )
            old_chunk_ids = self.db.knowledge_chunk_ids(document_id)
            if old_chunk_ids:
                self.retrieval.remove_chunks(int(document["library_id"]), old_chunk_ids)
            counts = self.db.replace_knowledge_document_content(document_id, blocks, assets)
            self.db.update_knowledge_ingestion_job(
                job_id,
                status="running",
                stage="indexing",
                progress=0.90,
                attempts=attempts,
                error=None,
            )
            try:
                index_result = self.retrieval.index_document(document_id)
            except Exception as index_exc:
                index_result = {
                    "ready": False,
                    "vector_error": str(index_exc).strip() or index_exc.__class__.__name__,
                    "lexical_indexed": 0,
                    "vector_indexed": 0,
                    "table_rows": 0,
                }
            metadata = {
                **(result.metadata or {}),
                "ingestion_version": 2,
                "retrieval_index_version": 1,
                "parser": document.get("source_type") or "unknown",
                "parent_block_count": counts["parent_blocks"],
                "chunk_count": counts["chunks"],
                "asset_count": counts["assets"],
                "retrieval_indexed": bool(index_result.get("ready")),
                "lexical_indexed_chunks": int(index_result.get("lexical_indexed") or 0),
                "vector_indexed_chunks": int(index_result.get("vector_indexed") or 0),
                "structured_table_rows": int(index_result.get("table_rows") or 0),
                "embedding_model": self.retrieval.model_name,
                "retrieval_error": index_result.get("vector_error"),
                "vlm_used": False,
            }
            self.db.update_knowledge_document_metadata(document_id, metadata)
            ready = self.db.update_knowledge_document_status(
                document_id,
                status="parsed",
                error=None,
                indexed_at=_utc_now() if index_result.get("ready") else None,
            ) or self.get_document(document_id)
            self.db.update_knowledge_ingestion_job(
                job_id,
                status="completed",
                stage="indexed" if index_result.get("ready") else "indexed_partial",
                progress=1.0,
                attempts=attempts,
                error=None,
                completed_at=_utc_now(),
            )
            return ready
        except Exception as exc:
            message = str(exc).strip() or exc.__class__.__name__
            self.db.update_knowledge_document_status(document_id, status="failed", error=message)
            self.db.update_knowledge_ingestion_job(
                job_id,
                status="failed",
                stage="failed",
                progress=1.0,
                attempts=attempts,
                error=message,
                completed_at=_utc_now(),
            )
            raise

    def reingest_document(self, document_id: int) -> dict[str, Any]:
        self.get_document(document_id)
        return self.create_job(document_id, job_type="reingest")

    def document_content(self, document_id: int) -> dict[str, Any]:
        document = self.get_document(document_id)
        return {
            "document": document,
            "parent_blocks": self.db.list_knowledge_parent_blocks(document_id),
            "chunks": self.db.list_knowledge_chunks(document_id),
            "assets": self.db.list_knowledge_assets(document_id),
        }

    def delete_document(self, document_id: int) -> None:
        document = self.get_document(document_id)
        storage_key = str(document.get("storage_key") or "")
        chunk_ids = self.db.knowledge_chunk_ids(document_id)
        if chunk_ids:
            self.retrieval.remove_chunks(int(document["library_id"]), chunk_ids)
        if not self.db.delete_knowledge_document(document_id):
            raise KnowledgeEngineNotFound("Knowledge document not found")
        if storage_key:
            source = (self.root / storage_key).resolve()
            root = self.root.resolve()
            try:
                source.relative_to(root)
            except ValueError:
                source = None
            if source:
                folder = source.parent
                shutil.rmtree(folder, ignore_errors=True)
        shutil.rmtree(self.assets_dir / str(document_id), ignore_errors=True)

    def retrieval_status(self) -> dict[str, Any]:
        return {
            **self.retrieval.status(),
            "libraries": self.db.list_knowledge_index_metadata(),
        }

    def search(
        self,
        query: str,
        *,
        library_ids: list[int] | None = None,
        agent_id: int | None = None,
        mode: str = "hybrid",
        top_k: int = 8,
        candidate_k: int = 30,
        adaptive: bool = True,
        build_context: bool = True,
        context_top_k: int = 6,
        context_token_budget: int = 3500,
        neighbor_window: int = 1,
    ) -> dict[str, Any]:
        if agent_id is not None and not self.db.get_agent(agent_id):
            raise KnowledgeEngineNotFound("Agent not found")
        try:
            return self.retrieval.search(
                query,
                library_ids=library_ids,
                agent_id=agent_id,
                mode=mode,
                top_k=top_k,
                candidate_k=candidate_k,
                adaptive=adaptive,
                build_context=build_context,
                context_top_k=context_top_k,
                context_token_budget=context_token_budget,
                neighbor_window=neighbor_window,
            )
        except KnowledgeRetrievalError as exc:
            raise KnowledgeEngineValidation(str(exc)) from exc

    def rebuild_index(self, library_id: int | None = None) -> dict[str, Any]:
        try:
            if library_id is None:
                return self.retrieval.rebuild_all()
            self.get_library(library_id)
            return self.retrieval.rebuild_library(library_id)
        except KnowledgeRetrievalError as exc:
            raise KnowledgeEngineValidation(str(exc)) from exc

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
