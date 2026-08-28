from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

import numpy as np

from app.db import Database, utc_now


DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_EMBEDDING_DIMENSION = 384
RRF_K = 60


class KnowledgeRetrievalError(RuntimeError):
    """Base error for the Phase-3 retrieval subsystem."""


class EmbeddingUnavailable(KnowledgeRetrievalError):
    """Dense embedding provider cannot currently produce vectors."""


class VectorIndexUnavailable(KnowledgeRetrievalError):
    """Persistent vector index cannot currently be opened or updated."""


class EmbeddingProvider(Protocol):
    name: str
    dimension: int

    def embed_passages(self, texts: list[str]) -> np.ndarray: ...

    def embed_query(self, text: str) -> np.ndarray: ...


@dataclass(slots=True)
class VectorMatch:
    chunk_id: int
    distance: float

    @property
    def similarity(self) -> float:
        return max(-1.0, min(1.0, 1.0 - float(self.distance)))


class FastEmbedMultilingualE5Small:
    """CPU-only multilingual E5 embeddings through FastEmbed/ONNX Runtime.

    The model is loaded lazily so starting VerbaNode never downloads a model or
    pays model-load cost. The first dense indexing/search operation may download
    the model into the Knowledge cache. Queries/passages receive the E5 prefixes
    explicitly so retrieval behavior is stable across FastEmbed versions.
    """

    name = DEFAULT_EMBEDDING_MODEL
    dimension = DEFAULT_EMBEDDING_DIMENSION

    def __init__(self, cache_dir: Path, *, threads: int = 2, batch_size: int = 32):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.threads = max(1, int(threads))
        self.batch_size = max(1, int(batch_size))
        self._model: Any | None = None
        self._lock = threading.RLock()

    @staticmethod
    def dependency_available() -> bool:
        return importlib.util.find_spec("fastembed") is not None

    def _load(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                from fastembed import TextEmbedding
                from fastembed.common.model_description import ModelSource, PoolingType
            except ImportError as exc:
                raise EmbeddingUnavailable(
                    "FastEmbed is not installed. Install the full VerbaNode requirements to enable dense retrieval."
                ) from exc

            supported = {
                str(item.get("model") or "").lower()
                for item in TextEmbedding.list_supported_models()
                if isinstance(item, dict)
            }
            if self.name.lower() not in supported:
                try:
                    TextEmbedding.add_custom_model(
                        model=self.name,
                        pooling=PoolingType.MEAN,
                        normalization=True,
                        sources=ModelSource(hf=self.name),
                        dim=self.dimension,
                        model_file="onnx/model.onnx",
                    )
                except ValueError as exc:
                    # Registration can legitimately race with another engine
                    # instance in the same process; retry construction below.
                    if "already" not in str(exc).lower():
                        raise

            try:
                self._model = TextEmbedding(
                    model_name=self.name,
                    cache_dir=str(self.cache_dir),
                    threads=self.threads,
                    providers=["CPUExecutionProvider"],
                    lazy_load=True,
                )
            except Exception as exc:
                raise EmbeddingUnavailable(f"Unable to load embedding model {self.name}: {exc}") from exc
            return self._model

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        model = self._load()
        prepared = [f"passage: {text.strip()}" for text in texts]
        try:
            vectors = list(model.embed(prepared, batch_size=self.batch_size))
        except Exception as exc:
            raise EmbeddingUnavailable(f"Embedding passages failed: {exc}") from exc
        result = np.asarray(vectors, dtype=np.float32)
        return _normalize_matrix(result, expected_dim=self.dimension)

    def embed_query(self, text: str) -> np.ndarray:
        model = self._load()
        prepared = f"query: {text.strip()}"
        try:
            vectors = list(model.embed([prepared], batch_size=1))
        except Exception as exc:
            raise EmbeddingUnavailable(f"Embedding query failed: {exc}") from exc
        result = np.asarray(vectors, dtype=np.float32)
        result = _normalize_matrix(result, expected_dim=self.dimension)
        return result[0]


def _normalize_matrix(values: np.ndarray, *, expected_dim: int) -> np.ndarray:
    matrix = np.asarray(values, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2 or matrix.shape[1] != expected_dim:
        raise EmbeddingUnavailable(
            f"Embedding model returned shape {tuple(matrix.shape)}; expected (*, {expected_dim})"
        )
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


def _slug_model(model_name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", model_name).strip("-._")
    return value[:100] or "embedding"


class LocalVectorIndex:
    """Per-library persistent ANN store with a NumPy exact-search fallback.

    USearch is preferred and provides HNSW. The fallback exists so a partially
    installed/offline Core still has deterministic dense-search behavior rather
    than failing the whole Knowledge API. Status surfaces which backend is in use.
    """

    def __init__(self, root: Path, *, dtype: str = "f16"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.dtype = dtype
        self._lock = threading.RLock()

    @staticmethod
    def hnsw_available() -> bool:
        return importlib.util.find_spec("usearch") is not None

    @property
    def preferred_backend(self) -> str:
        return "usearch-hnsw" if self.hnsw_available() else "numpy-flat-fallback"

    def _base(self, library_id: int, model_name: str) -> Path:
        return self.root / f"library-{int(library_id)}-{_slug_model(model_name)}"

    def _meta_path(self, library_id: int, model_name: str) -> Path:
        return self._base(library_id, model_name).with_suffix(".json")

    def _hnsw_path(self, library_id: int, model_name: str) -> Path:
        return self._base(library_id, model_name).with_suffix(".usearch")

    def _flat_path(self, library_id: int, model_name: str) -> Path:
        return self._base(library_id, model_name).with_suffix(".npz")

    def metadata(self, library_id: int, model_name: str) -> dict[str, Any] | None:
        path = self._meta_path(library_id, model_name)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def _write_metadata(
        self,
        library_id: int,
        model_name: str,
        *,
        dimension: int,
        backend: str,
        count: int,
    ) -> dict[str, Any]:
        data = {
            "library_id": int(library_id),
            "model_name": model_name,
            "dimension": int(dimension),
            "backend": backend,
            "count": int(count),
            "updated_at": utc_now(),
        }
        path = self._meta_path(library_id, model_name)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(temp, path)
        return data

    def _compatible(self, meta: dict[str, Any] | None, model_name: str, dimension: int) -> bool:
        return bool(
            meta
            and str(meta.get("model_name") or "") == model_name
            and int(meta.get("dimension") or 0) == int(dimension)
        )

    def replace(
        self,
        library_id: int,
        model_name: str,
        dimension: int,
        keys: Iterable[int],
        vectors: np.ndarray,
    ) -> dict[str, Any]:
        key_array = np.asarray(list(keys), dtype=np.uint64)
        matrix = _normalize_matrix(np.asarray(vectors, dtype=np.float32), expected_dim=dimension)
        if len(key_array) != len(matrix):
            raise VectorIndexUnavailable("Vector key/value count mismatch")
        with self._lock:
            if self.hnsw_available():
                try:
                    return self._replace_hnsw(library_id, model_name, dimension, key_array, matrix)
                except Exception:
                    # Fall back to the portable exact store. Dense retrieval is
                    # more useful than failing completely because of a native ABI.
                    pass
            return self._replace_flat(library_id, model_name, dimension, key_array, matrix)

    def upsert(
        self,
        library_id: int,
        model_name: str,
        dimension: int,
        keys: Iterable[int],
        vectors: np.ndarray,
    ) -> dict[str, Any]:
        key_array = np.asarray(list(keys), dtype=np.uint64)
        matrix = _normalize_matrix(np.asarray(vectors, dtype=np.float32), expected_dim=dimension)
        if not len(key_array):
            return self.metadata(library_id, model_name) or {
                "backend": self.preferred_backend,
                "count": 0,
            }
        if len(key_array) != len(matrix):
            raise VectorIndexUnavailable("Vector key/value count mismatch")
        with self._lock:
            meta = self.metadata(library_id, model_name)
            if not self._compatible(meta, model_name, dimension):
                return self.replace(library_id, model_name, dimension, key_array, matrix)
            backend = str(meta.get("backend") or "")
            if backend == "usearch-hnsw" and self._hnsw_path(library_id, model_name).is_file():
                try:
                    from usearch.index import Index

                    index = Index.restore(str(self._hnsw_path(library_id, model_name)), view=False)
                    for key in key_array:
                        try:
                            index.remove(int(key))
                        except Exception:
                            pass
                    index.add(key_array, matrix, threads=0, copy=True)
                    self._save_hnsw(index, self._hnsw_path(library_id, model_name))
                    return self._write_metadata(
                        library_id,
                        model_name,
                        dimension=dimension,
                        backend="usearch-hnsw",
                        count=len(index),
                    )
                except Exception as exc:
                    # Never silently replace a populated HNSW library with only
                    # the current document. A full rebuild has all vectors and
                    # can safely choose the portable fallback if native loading
                    # is unavailable.
                    raise VectorIndexUnavailable(
                        f"Unable to update HNSW index for library {library_id}: {exc}"
                    ) from exc
            return self._upsert_flat(library_id, model_name, dimension, key_array, matrix)

    def remove(self, library_id: int, model_name: str, keys: Iterable[int]) -> None:
        wanted = [int(value) for value in keys]
        if not wanted:
            return
        with self._lock:
            meta = self.metadata(library_id, model_name)
            if not meta:
                return
            backend = str(meta.get("backend") or "")
            if backend == "usearch-hnsw" and self._hnsw_path(library_id, model_name).is_file():
                try:
                    from usearch.index import Index

                    index = Index.restore(str(self._hnsw_path(library_id, model_name)), view=False)
                    for key in wanted:
                        try:
                            index.remove(key)
                        except Exception:
                            pass
                    self._save_hnsw(index, self._hnsw_path(library_id, model_name))
                    self._write_metadata(
                        library_id,
                        model_name,
                        dimension=int(meta.get("dimension") or 0),
                        backend="usearch-hnsw",
                        count=len(index),
                    )
                    return
                except Exception:
                    pass
            flat = self._load_flat(library_id, model_name)
            if flat is None:
                return
            flat_keys, vectors = flat
            mask = ~np.isin(flat_keys, np.asarray(wanted, dtype=np.uint64))
            self._replace_flat(
                library_id,
                model_name,
                int(meta.get("dimension") or vectors.shape[1]),
                flat_keys[mask],
                vectors[mask],
            )

    def search(
        self,
        library_id: int,
        model_name: str,
        dimension: int,
        query_vector: np.ndarray,
        count: int,
    ) -> list[VectorMatch]:
        count = max(1, int(count))
        query = _normalize_matrix(
            np.asarray(query_vector, dtype=np.float32).reshape(1, -1), expected_dim=dimension
        )[0]
        with self._lock:
            meta = self.metadata(library_id, model_name)
            if not self._compatible(meta, model_name, dimension):
                return []
            backend = str(meta.get("backend") or "")
            if backend == "usearch-hnsw" and self._hnsw_path(library_id, model_name).is_file():
                try:
                    from usearch.index import Index

                    index = Index.restore(str(self._hnsw_path(library_id, model_name)), view=True)
                    matches = index.search(query, min(count, max(1, len(index))))
                    return [
                        VectorMatch(int(match.key), float(match.distance))
                        for match in matches
                        if not math.isnan(float(match.distance))
                    ]
                except Exception:
                    return []
            flat = self._load_flat(library_id, model_name)
            if flat is None:
                return []
            keys, vectors = flat
            if not len(keys):
                return []
            similarities = np.asarray(vectors, dtype=np.float32) @ query
            order = np.argsort(-similarities)[: min(count, len(keys))]
            return [
                VectorMatch(int(keys[index]), float(1.0 - similarities[index]))
                for index in order
            ]

    def delete_library(self, library_id: int) -> None:
        with self._lock:
            for path in self.root.glob(f"library-{int(library_id)}-*"):
                if path.is_file():
                    path.unlink(missing_ok=True)

    def _replace_hnsw(
        self,
        library_id: int,
        model_name: str,
        dimension: int,
        keys: np.ndarray,
        vectors: np.ndarray,
    ) -> dict[str, Any]:
        from usearch.index import Index

        index = Index(
            ndim=dimension,
            metric="cos",
            dtype=self.dtype,
            connectivity=16,
            expansion_add=128,
            expansion_search=64,
        )
        if len(keys):
            index.add(keys, vectors, threads=0, copy=True)
        self._save_hnsw(index, self._hnsw_path(library_id, model_name))
        self._flat_path(library_id, model_name).unlink(missing_ok=True)
        return self._write_metadata(
            library_id,
            model_name,
            dimension=dimension,
            backend="usearch-hnsw",
            count=len(index),
        )

    @staticmethod
    def _save_hnsw(index: Any, path: Path) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.unlink(missing_ok=True)
        index.save(str(temp))
        os.replace(temp, path)

    def _replace_flat(
        self,
        library_id: int,
        model_name: str,
        dimension: int,
        keys: np.ndarray,
        vectors: np.ndarray,
    ) -> dict[str, Any]:
        path = self._flat_path(library_id, model_name)
        temp = path.with_suffix(path.suffix + ".tmp")
        with temp.open("wb") as handle:
            np.savez_compressed(
                handle,
                keys=np.asarray(keys, dtype=np.uint64),
                vectors=np.asarray(vectors, dtype=np.float16),
            )
        os.replace(temp, path)
        self._hnsw_path(library_id, model_name).unlink(missing_ok=True)
        return self._write_metadata(
            library_id,
            model_name,
            dimension=dimension,
            backend="numpy-flat-fallback",
            count=len(keys),
        )

    def _upsert_flat(
        self,
        library_id: int,
        model_name: str,
        dimension: int,
        keys: np.ndarray,
        vectors: np.ndarray,
    ) -> dict[str, Any]:
        existing = self._load_flat(library_id, model_name)
        if existing is None:
            return self._replace_flat(library_id, model_name, dimension, keys, vectors)
        old_keys, old_vectors = existing
        keep = ~np.isin(old_keys, keys)
        merged_keys = np.concatenate([old_keys[keep], keys])
        merged_vectors = np.concatenate([old_vectors[keep], vectors.astype(np.float32)], axis=0)
        return self._replace_flat(library_id, model_name, dimension, merged_keys, merged_vectors)

    def _load_flat(self, library_id: int, model_name: str) -> tuple[np.ndarray, np.ndarray] | None:
        path = self._flat_path(library_id, model_name)
        if not path.is_file():
            return None
        try:
            with np.load(path, allow_pickle=False) as data:
                keys = np.asarray(data["keys"], dtype=np.uint64)
                vectors = np.asarray(data["vectors"], dtype=np.float32)
            return keys, vectors
        except Exception:
            return None


def _fts_query(text: str) -> str:
    # FTS syntax is deliberately generated rather than accepting raw MATCH
    # expressions from clients. This avoids syntax errors/injection-like query
    # operators while still preserving codes such as VN-AE-104 as useful tokens.
    tokens = re.findall(r"[^\W_]+", text.casefold(), flags=re.UNICODE)
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token not in seen:
            seen.add(token)
            deduped.append(token)
    if not deduped:
        return ""
    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in deduped[:32])


def _split_table_line(line: str) -> list[str]:
    line = line.strip().strip("|")
    return [cell.strip() for cell in line.split("|")]


def table_rows_from_chunk(chunk: dict[str, Any]) -> list[dict[str, Any]]:
    if str(chunk.get("content_type") or "") != "table":
        return []
    lines = [line.strip() for line in str(chunk.get("text") or "").splitlines() if line.strip()]
    separator = -1
    for index, line in enumerate(lines):
        cells = _split_table_line(line)
        if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            separator = index
            break
    if separator <= 0:
        return []
    header = _split_table_line(lines[separator - 1])
    rows: list[dict[str, Any]] = []
    row_number = 0
    for line in lines[separator + 1 :]:
        cells = _split_table_line(line)
        if not any(cells):
            continue
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        cells = cells[: max(len(header), len(cells))]
        pairs = [
            f"{header[index] if index < len(header) else f'column_{index + 1}'}: {value}"
            for index, value in enumerate(cells)
            if value
        ]
        row_number += 1
        rows.append(
            {
                "chunk_id": int(chunk["id"]),
                "document_id": int(chunk["document_id"]),
                "library_id": int(chunk["library_id"]),
                "row_number": row_number,
                "header": header,
                "cells": cells,
                "row_text": " | ".join(pairs),
                "metadata": {
                    "page_start": chunk.get("page_start"),
                    "page_end": chunk.get("page_end"),
                    "heading_path": chunk.get("heading_path") or "",
                },
            }
        )
    return rows


class HybridRetriever:
    """Phase-3 retrieval orchestrator: BM25 + dense ANN + table rows + RRF."""

    def __init__(
        self,
        db: Database,
        indexes_dir: Path,
        cache_dir: Path,
        *,
        embedding_provider: EmbeddingProvider | None = None,
        vector_index: LocalVectorIndex | None = None,
        embedding_threads: int = 2,
    ):
        self.db = db
        self.indexes_dir = Path(indexes_dir)
        self.cache_dir = Path(cache_dir)
        self.embedding_provider: EmbeddingProvider = embedding_provider or FastEmbedMultilingualE5Small(
            self.cache_dir / "embeddings", threads=embedding_threads
        )
        self.vector_index = vector_index or LocalVectorIndex(self.indexes_dir / "vectors")
        self._lock = threading.RLock()

    @property
    def model_name(self) -> str:
        return str(self.embedding_provider.name)

    @property
    def dimension(self) -> int:
        return int(self.embedding_provider.dimension)

    def status(self) -> dict[str, Any]:
        counts = self.db.knowledge_retrieval_counts()
        return {
            "phase": "hybrid_retrieval",
            "retrieval_enabled": True,
            "chat_integration": False,
            "embedding_model": self.model_name,
            "embedding_dimension": self.dimension,
            "embedding_runtime_available": (
                FastEmbedMultilingualE5Small.dependency_available()
                if isinstance(self.embedding_provider, FastEmbedMultilingualE5Small)
                else True
            ),
            "vector_backend_preferred": self.vector_index.preferred_backend,
            "hnsw_available": self.vector_index.hnsw_available(),
            "rrf_k": RRF_K,
            "counts": counts,
        }

    def remove_chunks(self, library_id: int, chunk_ids: Iterable[int]) -> None:
        ids = [int(value) for value in chunk_ids]
        if not ids:
            return
        try:
            self.vector_index.remove(library_id, self.model_name, ids)
        finally:
            self.db.delete_knowledge_vector_records(ids)

    def delete_library_index(self, library_id: int) -> None:
        self.vector_index.delete_library(library_id)
        self.db.clear_knowledge_index_metadata(library_id)

    def index_document(self, document_id: int) -> dict[str, Any]:
        document = self.db.get_knowledge_document(document_id)
        if not document:
            raise KnowledgeRetrievalError("Knowledge document not found")
        library_id = int(document["library_id"])
        chunks = self.db.knowledge_chunks_for_index(document_id=document_id)
        now = utc_now()

        # FTS5 is kept current by database triggers. Marking lexical status here
        # records that Phase-3 indexing has observed this chunk and lets status/UI
        # distinguish migrated Phase-2 content from indexed content.
        chunk_ids = [int(chunk["id"]) for chunk in chunks]
        self.db.mark_knowledge_chunks_lexical(chunk_ids, status="ready", indexed_at=now)

        table_rows: list[dict[str, Any]] = []
        for chunk in chunks:
            table_rows.extend(table_rows_from_chunk(chunk))
        self.db.replace_knowledge_table_rows(document_id, table_rows)

        vector_error: str | None = None
        vector_backend = self.vector_index.preferred_backend
        if chunks:
            existing_meta = self.vector_index.metadata(library_id, self.model_name)
            all_library_chunks = self.db.knowledge_chunks_for_index(library_id=library_id)
            compatible = bool(
                existing_meta
                and str(existing_meta.get("model_name") or "") == self.model_name
                and int(existing_meta.get("dimension") or 0) == self.dimension
            )
            # Upgrading from Phase 2 can leave a populated library with no ANN
            # file. Never create an index containing only the newly ingested
            # document; rebuild the whole library once so older chunks become
            # dense-searchable too.
            if not compatible and len(all_library_chunks) > len(chunks):
                rebuilt = self.rebuild_library(library_id)
                return {
                    "document_id": document_id,
                    "library_id": library_id,
                    "chunks": len(chunks),
                    "lexical_indexed": len(chunks),
                    "table_rows": len(table_rows),
                    "vector_indexed": len(chunks) if rebuilt.get("ready") else 0,
                    "vector_backend": rebuilt.get("vector_backend"),
                    "embedding_model": self.model_name,
                    "vector_error": rebuilt.get("vector_error"),
                    "ready": bool(rebuilt.get("ready")),
                }
            texts = [str(chunk.get("text") or "") for chunk in chunks]
            try:
                vectors = self.embedding_provider.embed_passages(texts)
                meta = self.vector_index.upsert(
                    library_id,
                    self.model_name,
                    self.dimension,
                    chunk_ids,
                    vectors,
                )
                vector_backend = str(meta.get("backend") or vector_backend)
                records = []
                for chunk in chunks:
                    text = str(chunk.get("text") or "")
                    records.append(
                        {
                            "chunk_id": int(chunk["id"]),
                            "document_id": document_id,
                            "library_id": library_id,
                            "model_name": self.model_name,
                            "dimension": self.dimension,
                            "backend": vector_backend,
                            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                            "indexed_at": now,
                        }
                    )
                self.db.upsert_knowledge_vector_records(records)
                self.db.mark_knowledge_chunks_vector(
                    chunk_ids,
                    status="ready",
                    model_name=self.model_name,
                    indexed_at=now,
                )
            except Exception as exc:
                vector_error = str(exc).strip() or exc.__class__.__name__
                self.db.mark_knowledge_chunks_vector(
                    chunk_ids,
                    status="error",
                    model_name=self.model_name,
                    indexed_at=None,
                )

        current_vector_count = len(self.db.knowledge_vector_records(library_id))
        library_table_count = self.db.knowledge_table_row_count(library_id=library_id)
        self.db.update_knowledge_index_metadata(
            library_id,
            embedding_model=self.model_name,
            embedding_dimension=self.dimension,
            vector_backend=vector_backend,
            vector_index_path=self.vector_index.metadata(library_id, self.model_name),
            vector_count=current_vector_count,
            table_row_count=library_table_count,
            status="partial" if vector_error else "ready",
            error=vector_error,
        )
        return {
            "document_id": document_id,
            "library_id": library_id,
            "chunks": len(chunks),
            "lexical_indexed": len(chunks),
            "table_rows": len(table_rows),
            "vector_indexed": 0 if vector_error else len(chunks),
            "vector_backend": vector_backend,
            "embedding_model": self.model_name,
            "vector_error": vector_error,
            "ready": vector_error is None,
        }

    def rebuild_library(self, library_id: int) -> dict[str, Any]:
        library = self.db.get_knowledge_library(library_id)
        if not library:
            raise KnowledgeRetrievalError("Knowledge library not found")
        chunks = self.db.knowledge_chunks_for_index(library_id=library_id)
        documents = self.db.list_knowledge_documents(library_id)
        self.db.rebuild_knowledge_lexical_index()
        table_total = 0
        for document in documents:
            doc_chunks = [c for c in chunks if int(c["document_id"]) == int(document["id"])]
            rows: list[dict[str, Any]] = []
            for chunk in doc_chunks:
                rows.extend(table_rows_from_chunk(chunk))
            self.db.replace_knowledge_table_rows(int(document["id"]), rows)
            table_total += len(rows)

        chunk_ids = [int(chunk["id"]) for chunk in chunks]
        now = utc_now()
        self.db.mark_knowledge_chunks_lexical(chunk_ids, status="ready", indexed_at=now)
        vector_error: str | None = None
        backend = self.vector_index.preferred_backend
        if chunks:
            try:
                vectors = self.embedding_provider.embed_passages(
                    [str(chunk.get("text") or "") for chunk in chunks]
                )
                meta = self.vector_index.replace(
                    library_id, self.model_name, self.dimension, chunk_ids, vectors
                )
                backend = str(meta.get("backend") or backend)
                self.db.replace_knowledge_vector_records(
                    library_id,
                    [
                        {
                            "chunk_id": int(chunk["id"]),
                            "document_id": int(chunk["document_id"]),
                            "library_id": library_id,
                            "model_name": self.model_name,
                            "dimension": self.dimension,
                            "backend": backend,
                            "text_sha256": hashlib.sha256(
                                str(chunk.get("text") or "").encode("utf-8")
                            ).hexdigest(),
                            "indexed_at": now,
                        }
                        for chunk in chunks
                    ],
                )
                self.db.mark_knowledge_chunks_vector(
                    chunk_ids,
                    status="ready",
                    model_name=self.model_name,
                    indexed_at=now,
                )
            except Exception as exc:
                vector_error = str(exc).strip() or exc.__class__.__name__
                self.db.mark_knowledge_chunks_vector(
                    chunk_ids,
                    status="error",
                    model_name=self.model_name,
                    indexed_at=None,
                )
        else:
            self.vector_index.delete_library(library_id)
            self.db.replace_knowledge_vector_records(library_id, [])

        self.db.update_knowledge_index_metadata(
            library_id,
            embedding_model=self.model_name,
            embedding_dimension=self.dimension,
            vector_backend=backend,
            vector_index_path=self.vector_index.metadata(library_id, self.model_name),
            vector_count=0 if vector_error else len(chunks),
            table_row_count=table_total,
            status="partial" if vector_error else "ready",
            error=vector_error,
        )
        return {
            "library_id": library_id,
            "chunks": len(chunks),
            "table_rows": table_total,
            "vector_indexed": 0 if vector_error else len(chunks),
            "vector_backend": backend,
            "embedding_model": self.model_name,
            "vector_error": vector_error,
            "ready": vector_error is None,
        }

    def rebuild_all(self) -> dict[str, Any]:
        started = time.perf_counter()
        results = []
        for library in self.db.list_knowledge_libraries():
            results.append(self.rebuild_library(int(library["id"])))
        return {
            "libraries": results,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
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
    ) -> dict[str, Any]:
        started = time.perf_counter()
        query = str(query or "").strip()
        if not query:
            raise KnowledgeRetrievalError("Knowledge search query cannot be blank")
        top_k = max(1, min(50, int(top_k)))
        candidate_k = max(top_k, min(200, int(candidate_k)))
        mode = mode if mode in {"hybrid", "lexical", "vector", "table"} else "hybrid"
        resolved_libraries = self._resolve_libraries(library_ids, agent_id)
        warnings: list[str] = []
        fts = _fts_query(query)

        lexical: list[dict[str, Any]] = []
        table: list[dict[str, Any]] = []
        vector: list[dict[str, Any]] = []
        if mode in {"hybrid", "lexical"} and fts and resolved_libraries:
            lexical = self.db.search_knowledge_lexical(fts, resolved_libraries, candidate_k)
        if mode in {"hybrid", "table"} and fts and resolved_libraries:
            table = self.db.search_knowledge_table_rows(fts, resolved_libraries, candidate_k)
        if mode in {"hybrid", "vector"} and resolved_libraries:
            try:
                query_vector = self.embedding_provider.embed_query(query)
                raw_matches: list[tuple[int, VectorMatch]] = []
                per_library = max(candidate_k, top_k * 2)
                for library_id in resolved_libraries:
                    for match in self.vector_index.search(
                        library_id,
                        self.model_name,
                        self.dimension,
                        query_vector,
                        per_library,
                    ):
                        raw_matches.append((library_id, match))
                raw_matches.sort(key=lambda item: item[1].distance)
                ids = [item[1].chunk_id for item in raw_matches[: candidate_k * max(1, len(resolved_libraries))]]
                chunk_map = {
                    int(item["id"]): item
                    for item in self.db.knowledge_chunks_by_ids(ids)
                    if int(item.get("library_id") or 0) in set(resolved_libraries)
                }
                for _library_id, match in raw_matches:
                    chunk = chunk_map.get(match.chunk_id)
                    if not chunk:
                        continue
                    vector.append({**chunk, "vector_distance": match.distance, "vector_similarity": match.similarity})
                    if len(vector) >= candidate_k:
                        break
                if not vector:
                    warnings.append("No dense vector index is available for the selected libraries yet.")
            except Exception as exc:
                warnings.append(f"Dense retrieval unavailable: {str(exc).strip() or exc.__class__.__name__}")

        if mode == "lexical":
            ranked = self._single_channel(lexical, "lexical")
        elif mode == "vector":
            ranked = self._single_channel(vector, "vector")
        elif mode == "table":
            ranked = self._single_channel(table, "table")
        else:
            ranked = self._rrf(lexical, vector, table)

        results = ranked[:top_k]
        return {
            "query": query,
            "mode": mode,
            "library_ids": resolved_libraries,
            "agent_id": agent_id,
            "top_k": top_k,
            "candidate_k": candidate_k,
            "embedding_model": self.model_name,
            "embedding_dimension": self.dimension,
            "vector_backend": self.vector_index.preferred_backend,
            "channels": {
                "lexical_candidates": len(lexical),
                "vector_candidates": len(vector),
                "table_candidates": len(table),
            },
            "warnings": warnings,
            "results": results,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    def _resolve_libraries(
        self, library_ids: list[int] | None, agent_id: int | None
    ) -> list[int]:
        enabled = set(self.db.knowledge_enabled_library_ids())
        requested = set(int(value) for value in (library_ids or []) if int(value) > 0)
        if agent_id is not None:
            assigned = set(self.db.knowledge_library_ids_for_agent(int(agent_id)))
            allowed = enabled & assigned
        else:
            allowed = enabled
        if requested:
            allowed &= requested
        return sorted(allowed)

    @staticmethod
    def _single_channel(items: list[dict[str, Any]], channel: str) -> list[dict[str, Any]]:
        results = []
        for rank, item in enumerate(items, start=1):
            result = dict(item)
            result["rrf_score"] = 1.0 / (RRF_K + rank)
            result["ranks"] = {channel: rank}
            results.append(result)
        return results

    @staticmethod
    def _rrf(
        lexical: list[dict[str, Any]],
        vector: list[dict[str, Any]],
        table: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        merged: dict[int, dict[str, Any]] = {}
        weights = {"lexical": 1.0, "vector": 1.0, "table": 1.1}
        for channel, items in (("lexical", lexical), ("vector", vector), ("table", table)):
            for rank, item in enumerate(items, start=1):
                chunk_id = int(item.get("chunk_id") or item.get("id") or 0)
                if not chunk_id:
                    continue
                target = merged.setdefault(
                    chunk_id,
                    {
                        **item,
                        "id": chunk_id,
                        "chunk_id": chunk_id,
                        "rrf_score": 0.0,
                        "ranks": {},
                    },
                )
                # Prefer channel-specific diagnostic fields without replacing
                # the canonical chunk/document payload from the first channel.
                for key in (
                    "lexical_score",
                    "vector_distance",
                    "vector_similarity",
                    "table_score",
                    "matched_row",
                    "matched_row_number",
                ):
                    if key in item:
                        target[key] = item[key]
                target["ranks"][channel] = rank
                target["rrf_score"] += weights[channel] / (RRF_K + rank)
        return sorted(
            merged.values(),
            key=lambda item: (-float(item.get("rrf_score") or 0.0), int(item.get("chunk_id") or 0)),
        )


__all__ = [
    "DEFAULT_EMBEDDING_DIMENSION",
    "DEFAULT_EMBEDDING_MODEL",
    "EmbeddingProvider",
    "EmbeddingUnavailable",
    "FastEmbedMultilingualE5Small",
    "HybridRetriever",
    "KnowledgeRetrievalError",
    "LocalVectorIndex",
    "VectorIndexUnavailable",
    "VectorMatch",
    "table_rows_from_chunk",
]
