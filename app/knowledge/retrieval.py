from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

import numpy as np

from app.db import Database, utc_now


DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
DEFAULT_EMBEDDING_DIMENSION = 384
RRF_K = 60
DEFAULT_CONTEXT_TOKEN_BUDGET = 3500
DEFAULT_CONTEXT_TOP_K = 6
DEFAULT_RERANK_CANDIDATES = 20


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


_STOPWORDS = {
    # English
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "is",
    "it", "of", "on", "or", "that", "the", "this", "to", "what", "when", "where", "which",
    "who", "why", "with",
    # Indonesian
    "ada", "adalah", "atau", "bagaimana", "dalam", "dan", "dari", "di", "ini", "itu", "ke",
    "mana", "pada", "sebagai", "untuk", "yang",
}

_TABLE_STRONG_HINTS = {
    "average", "avg", "bandingkan", "baris", "biaya", "cell", "column", "compare", "cost",
    "harga", "highest", "jumlah", "kolom", "lowest", "maksimum", "maximum", "minimum",
    "paling", "price", "row", "rata", "table", "tabel", "tegangan", "terendah", "tertinggi",
    "total",
}

_TABLE_ATTRIBUTE_HINTS = {"current", "voltage", "arus", "tegangan", "amp", "amps", "watt", "watts"}

_EXACT_HINTS = {
    "api", "code", "error", "file", "firmware", "id", "model", "route", "sku", "version",
    "kode", "versi", "galat",
}

_IDENTIFIER_RE = re.compile(
    r"(?<![\w])(?=[A-Za-z0-9._/:-]*[A-Za-z])(?=[A-Za-z0-9._/:-]*\d)"
    r"[A-Za-z0-9][A-Za-z0-9._/:-]{1,}(?![\w])"
)


def normalize_query_text(text: str) -> str:
    """Cheap deterministic query cleanup that preserves technical identifiers."""
    value = unicodedata.normalize("NFKC", str(text or ""))
    value = value.replace("“", '"').replace("”", '"').replace("’", "'")
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _query_tokens(text: str, *, keep_stopwords: bool = False) -> list[str]:
    tokens = re.findall(r"[^\W_]+(?:[-./:][^\W_]+)*", text.casefold(), flags=re.UNICODE)
    if keep_stopwords:
        return tokens
    return [token for token in tokens if token not in _STOPWORDS and len(token) > 1]


def _identifiers(text: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for match in _IDENTIFIER_RE.findall(text):
        key = match.casefold()
        if key not in seen:
            seen.add(key)
            result.append(match)
    return result


@dataclass(slots=True)
class QueryPlan:
    query: str
    normalized_query: str
    intent: str
    channel_weights: dict[str, float]
    identifiers: list[str]
    reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "normalized_query": self.normalized_query,
            "channel_weights": dict(self.channel_weights),
            "identifiers": list(self.identifiers),
            "reasons": list(self.reasons),
        }


def plan_query(query: str) -> QueryPlan:
    normalized = normalize_query_text(query)
    tokens = set(_query_tokens(normalized, keep_stopwords=True))
    identifiers = _identifiers(normalized)
    quoted = bool(re.search(r'"[^"\n]{2,}"', normalized))
    table_hits = sorted(tokens & _TABLE_STRONG_HINTS)
    table_attributes = sorted(tokens & _TABLE_ATTRIBUTE_HINTS)
    exact_hits = sorted(tokens & _EXACT_HINTS)
    has_number = bool(re.search(r"\b\d+(?:[.,]\d+)?\b", normalized))
    reasons: list[str] = []

    table_signal = (
        bool(table_hits)
        or (bool(table_attributes) and bool(tokens & {"which", "what", "berapa", "mana"}))
        or (has_number and bool(tokens & {"lebih", "kurang", "above", "below", "over", "under"}))
    )
    exact_signal = bool(identifiers or quoted or exact_hits)

    if table_signal and exact_signal:
        intent = "table_exact"
        weights = {"lexical": 1.35, "vector": 0.75, "table": 1.55}
    elif table_signal:
        intent = "table"
        weights = {"lexical": 1.05, "vector": 0.90, "table": 1.55}
    elif exact_signal:
        intent = "exact"
        weights = {"lexical": 1.50, "vector": 0.80, "table": 0.95}
    else:
        intent = "semantic"
        weights = {"lexical": 0.95, "vector": 1.30, "table": 0.85}

    if identifiers:
        reasons.append("technical identifier detected")
    if quoted:
        reasons.append("quoted phrase detected")
    if exact_hits:
        reasons.append("exact-match terminology detected")
    if table_hits or (table_signal and table_attributes):
        reasons.append("tabular/numeric terminology detected")
    if not reasons:
        reasons.append("semantic/general question")

    return QueryPlan(
        query=query,
        normalized_query=normalized,
        intent=intent,
        channel_weights=weights,
        identifiers=identifiers,
        reasons=reasons,
    )


def _estimate_tokens(text: str) -> int:
    # No tokenizer dependency is required in Core. This deliberately errs a bit
    # high for Latin-script English/Indonesian so the eventual LLM prompt stays
    # under budget when Phase 5 consumes the same context builder.
    words = re.findall(r"\S+", str(text or ""))
    return max(1, int(math.ceil(len(words) * 1.35))) if words else 0


def _truncate_to_tokens(text: str, token_budget: int) -> str:
    text = str(text or "").strip()
    if not text or token_budget <= 0:
        return ""
    if _estimate_tokens(text) <= token_budget:
        return text
    # Approximate four characters/token, then back up to a word boundary.
    cap = max(64, int(token_budget) * 4)
    value = text[:cap]
    if len(value) < len(text):
        value = value.rsplit(" ", 1)[0].rstrip() + " …"
    return value


def _token_set(text: str) -> set[str]:
    return set(_query_tokens(text))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union) if union else 0.0


class CpuFeatureReranker:
    """Very light deterministic reranker for CPU-only VerbaNode installs.

    It deliberately avoids another neural model download. Dense semantic score,
    hybrid channel agreement, exact identifiers, query-term coverage, headings,
    and content type are recombined after RRF. A neural cross-encoder can be
    added behind the same Phase-4 boundary later without changing Chat/Voice.
    """

    name = "verbanode-cpu-feature-reranker-v1"

    def rerank(self, plan: QueryPlan, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not items:
            return []
        query_tokens = set(_query_tokens(plan.normalized_query))
        identifiers = [value.casefold() for value in plan.identifiers]
        max_rrf = max(float(item.get("rrf_score") or 0.0) for item in items) or 1.0
        reranked: list[dict[str, Any]] = []

        for item in items:
            text = str(item.get("text") or "")
            matched_row = str(item.get("matched_row") or "")
            heading = str(item.get("heading_path") or "")
            title = str(item.get("document_title") or "")
            haystack = "\n".join(part for part in (title, heading, text, matched_row) if part)
            haystack_fold = haystack.casefold()
            candidate_tokens = _token_set(haystack)
            coverage = (
                len(query_tokens & candidate_tokens) / len(query_tokens) if query_tokens else 0.0
            )
            heading_tokens = _token_set(f"{title} {heading}")
            heading_coverage = (
                len(query_tokens & heading_tokens) / len(query_tokens) if query_tokens else 0.0
            )
            if identifiers:
                identifier_score = sum(1 for value in identifiers if value in haystack_fold) / len(identifiers)
            else:
                identifier_score = 0.0
            ranks = item.get("ranks") or {}
            agreement = min(1.0, len(ranks) / 3.0)
            vector_similarity = float(item.get("vector_similarity") or 0.0)
            vector_score = max(0.0, min(1.0, vector_similarity))
            rrf_norm = max(0.0, min(1.0, float(item.get("rrf_score") or 0.0) / max_rrf))
            table_match = 1.0 if str(item.get("content_type") or "") == "table" or matched_row else 0.0
            phrase = 0.0
            phrase_query = plan.normalized_query.casefold()
            if 3 <= len(phrase_query) <= 180 and phrase_query in haystack_fold:
                phrase = 1.0

            if plan.intent == "semantic":
                score = (
                    coverage * 0.20
                    + heading_coverage * 0.08
                    + agreement * 0.10
                    + vector_score * 0.30
                    + rrf_norm * 0.25
                    + phrase * 0.07
                )
            elif plan.intent in {"table", "table_exact"}:
                score = (
                    coverage * 0.20
                    + heading_coverage * 0.07
                    + identifier_score * 0.13
                    + agreement * 0.08
                    + vector_score * 0.10
                    + rrf_norm * 0.17
                    + table_match * 0.20
                    + phrase * 0.05
                )
            else:  # exact
                score = (
                    coverage * 0.25
                    + heading_coverage * 0.08
                    + identifier_score * 0.25
                    + agreement * 0.08
                    + vector_score * 0.07
                    + rrf_norm * 0.20
                    + phrase * 0.07
                )

            result = dict(item)
            result["rerank_score"] = round(max(0.0, min(1.0, score)), 6)
            result["rerank_components"] = {
                "coverage": round(coverage, 4),
                "heading_coverage": round(heading_coverage, 4),
                "identifier": round(identifier_score, 4),
                "channel_agreement": round(agreement, 4),
                "vector": round(vector_score, 4),
                "rrf": round(rrf_norm, 4),
                "table": round(table_match, 4),
                "phrase": round(phrase, 4),
            }
            reranked.append(result)

        return sorted(
            reranked,
            key=lambda item: (
                -float(item.get("rerank_score") or 0.0),
                -float(item.get("rrf_score") or 0.0),
                int(item.get("chunk_id") or item.get("id") or 0),
            ),
        )


class HybridRetriever:
    """Phase-4 intelligent retrieval over the Phase-3 hybrid indexes.

    Search remains standalone from Chat/Voice, but now includes cheap query
    routing, weighted RRF, deterministic CPU reranking, confidence-based
    widening, duplicate suppression, and bounded hierarchical context assembly.
    """

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
        self.reranker = CpuFeatureReranker()
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
            "phase": "intelligent_retrieval",
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
            "query_routing": True,
            "reranking": True,
            "reranker": self.reranker.name,
            "confidence_fallback": True,
            "deduplication": True,
            "hierarchical_context": True,
            "context_token_budget_default": DEFAULT_CONTEXT_TOKEN_BUDGET,
            "context_top_k_default": DEFAULT_CONTEXT_TOP_K,
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
        adaptive: bool = True,
        build_context: bool = True,
        context_top_k: int = DEFAULT_CONTEXT_TOP_K,
        context_token_budget: int = DEFAULT_CONTEXT_TOKEN_BUDGET,
        neighbor_window: int = 1,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        query = str(query or "").strip()
        if not query:
            raise KnowledgeRetrievalError("Knowledge search query cannot be blank")
        top_k = max(1, min(50, int(top_k)))
        candidate_k = max(top_k, min(200, int(candidate_k)))
        context_top_k = max(1, min(12, int(context_top_k)))
        context_token_budget = max(256, min(12000, int(context_token_budget)))
        neighbor_window = max(0, min(2, int(neighbor_window)))
        mode = mode if mode in {"hybrid", "lexical", "vector", "table"} else "hybrid"
        resolved_libraries = self._resolve_libraries(library_ids, agent_id)
        warnings: list[str] = []
        plan = plan_query(query)
        fts = _fts_query(plan.normalized_query)

        lexical, vector, table = self._retrieve_channels(
            plan,
            fts,
            resolved_libraries,
            mode=mode,
            candidate_k=candidate_k,
            top_k=top_k,
            warnings=warnings,
        )
        ranked = self._rank_channels(plan, lexical, vector, table, mode)
        reranked = self._rerank_and_deduplicate(plan, ranked, top_k=top_k)
        dedup_removed = max(0, len(ranked) - len(reranked))
        confidence = self._confidence(reranked)
        initial_confidence = dict(confidence)
        fallback_used = False
        effective_candidate_k = candidate_k

        # Low-confidence questions get one bounded wider retrieval pass. This is
        # intentionally retrieval-only: no LLM query rewriting or HyDE call is
        # introduced on CPU-only systems.
        if (
            adaptive
            and mode == "hybrid"
            and resolved_libraries
            and confidence["label"] in {"none", "low"}
            and candidate_k < 120
        ):
            widened_k = min(120, max(candidate_k * 2, top_k * 8, 48))
            if widened_k > candidate_k:
                fallback_used = True
                effective_candidate_k = widened_k
                lexical, vector, table = self._retrieve_channels(
                    plan,
                    fts,
                    resolved_libraries,
                    mode=mode,
                    candidate_k=widened_k,
                    top_k=top_k,
                    warnings=warnings,
                )
                ranked = self._rank_channels(plan, lexical, vector, table, mode)
                reranked = self._rerank_and_deduplicate(plan, ranked, top_k=top_k)
                dedup_removed = max(0, len(ranked) - len(reranked))
                confidence = self._confidence(reranked)

        results = reranked[:top_k]
        context = (
            self._build_context(
                results,
                max_evidence=context_top_k,
                token_budget=context_token_budget,
                neighbor_window=neighbor_window,
            )
            if build_context
            else {
                "enabled": False,
                "token_budget": context_token_budget,
                "estimated_tokens": 0,
                "evidence_count": 0,
                "evidence": [],
                "text": "",
            }
        )
        context["safe_to_inject"] = bool(results) and confidence["label"] in {"medium", "high"}
        return {
            "query": query,
            "normalized_query": plan.normalized_query,
            "mode": mode,
            "strategy": "adaptive" if adaptive else "fixed",
            "routing": plan.as_dict(),
            "library_ids": resolved_libraries,
            "agent_id": agent_id,
            "top_k": top_k,
            "candidate_k": candidate_k,
            "effective_candidate_k": effective_candidate_k,
            "embedding_model": self.model_name,
            "embedding_dimension": self.dimension,
            "vector_backend": self.vector_index.preferred_backend,
            "reranker": self.reranker.name,
            "postprocessing": {
                "ranked_candidates": len(ranked),
                "deduplicated_candidates": len(reranked),
                "duplicates_removed": dedup_removed,
            },
            "channels": {
                "lexical_candidates": len(lexical),
                "vector_candidates": len(vector),
                "table_candidates": len(table),
            },
            "confidence": {
                **confidence,
                "initial_score": initial_confidence["score"],
                "initial_label": initial_confidence["label"],
                "fallback_used": fallback_used,
            },
            "context": context,
            "warnings": warnings,
            "results": results,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    def _retrieve_channels(
        self,
        plan: QueryPlan,
        fts: str,
        resolved_libraries: list[int],
        *,
        mode: str,
        candidate_k: int,
        top_k: int,
        warnings: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        lexical: list[dict[str, Any]] = []
        table: list[dict[str, Any]] = []
        vector: list[dict[str, Any]] = []
        if mode in {"hybrid", "lexical"} and fts and resolved_libraries:
            lexical = self.db.search_knowledge_lexical(fts, resolved_libraries, candidate_k)
        if mode in {"hybrid", "table"} and fts and resolved_libraries:
            table = self.db.search_knowledge_table_rows(fts, resolved_libraries, candidate_k)
        if mode in {"hybrid", "vector"} and resolved_libraries:
            try:
                query_vector = self.embedding_provider.embed_query(plan.normalized_query)
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
                ids = [
                    item[1].chunk_id
                    for item in raw_matches[: candidate_k * max(1, len(resolved_libraries))]
                ]
                allowed = set(resolved_libraries)
                chunk_map = {
                    int(item["id"]): item
                    for item in self.db.knowledge_chunks_by_ids(ids)
                    if int(item.get("library_id") or 0) in allowed
                }
                for _library_id, match in raw_matches:
                    chunk = chunk_map.get(match.chunk_id)
                    if not chunk:
                        continue
                    vector.append(
                        {
                            **chunk,
                            "vector_distance": match.distance,
                            "vector_similarity": match.similarity,
                        }
                    )
                    if len(vector) >= candidate_k:
                        break
                if not vector:
                    warning = "No dense vector index is available for the selected libraries yet."
                    if warning not in warnings:
                        warnings.append(warning)
            except Exception as exc:
                warning = (
                    f"Dense retrieval unavailable: {str(exc).strip() or exc.__class__.__name__}"
                )
                if warning not in warnings:
                    warnings.append(warning)
        return lexical, vector, table

    def _rank_channels(
        self,
        plan: QueryPlan,
        lexical: list[dict[str, Any]],
        vector: list[dict[str, Any]],
        table: list[dict[str, Any]],
        mode: str,
    ) -> list[dict[str, Any]]:
        if mode == "lexical":
            return self._single_channel(lexical, "lexical")
        if mode == "vector":
            return self._single_channel(vector, "vector")
        if mode == "table":
            return self._single_channel(table, "table")
        return self._rrf(lexical, vector, table, weights=plan.channel_weights)

    def _rerank_and_deduplicate(
        self, plan: QueryPlan, ranked: list[dict[str, Any]], *, top_k: int
    ) -> list[dict[str, Any]]:
        rerank_k = min(len(ranked), max(DEFAULT_RERANK_CANDIDATES, int(top_k) * 4))
        reranked = self.reranker.rerank(plan, ranked[:rerank_k])
        if rerank_k < len(ranked):
            # Unreranked tail remains available only after all scored candidates.
            tail = [dict(item, rerank_score=0.0, rerank_components={}) for item in ranked[rerank_k:]]
            reranked.extend(tail)

        deduped: list[dict[str, Any]] = []
        fingerprints: list[tuple[int, set[str], str]] = []
        for item in reranked:
            document_id = int(item.get("document_id") or 0)
            text = str(item.get("matched_row") or item.get("text") or "").strip()
            normalized = re.sub(r"\s+", " ", text.casefold())
            tokens = _token_set(normalized)
            duplicate = False
            for kept_document_id, kept_tokens, kept_normalized in fingerprints:
                if document_id != kept_document_id:
                    continue
                if normalized and normalized == kept_normalized:
                    duplicate = True
                    break
                if len(tokens) >= 6 and len(kept_tokens) >= 6 and _jaccard(tokens, kept_tokens) >= 0.90:
                    duplicate = True
                    break
            if duplicate:
                continue
            result = dict(item)
            result["deduplicated"] = False
            deduped.append(result)
            fingerprints.append((document_id, tokens, normalized))
        return deduped

    @staticmethod
    def _confidence(items: list[dict[str, Any]]) -> dict[str, Any]:
        if not items:
            return {"score": 0.0, "label": "none", "margin": 0.0}
        top = items[0]
        top_score = float(top.get("rerank_score") or 0.0)
        second_score = float(items[1].get("rerank_score") or 0.0) if len(items) > 1 else 0.0
        margin = max(0.0, top_score - second_score)
        components = top.get("rerank_components") or {}
        agreement = float(components.get("channel_agreement") or 0.0)
        coverage = float(components.get("coverage") or 0.0)
        score = max(
            0.0,
            min(1.0, top_score * 0.72 + agreement * 0.12 + coverage * 0.10 + min(1.0, margin * 4) * 0.06),
        )
        if score >= 0.68:
            label = "high"
        elif score >= 0.48:
            label = "medium"
        else:
            label = "low"
        return {"score": round(score, 6), "label": label, "margin": round(margin, 6)}

    def _build_context(
        self,
        results: list[dict[str, Any]],
        *,
        max_evidence: int,
        token_budget: int,
        neighbor_window: int,
    ) -> dict[str, Any]:
        if not results:
            return {
                "enabled": True,
                "token_budget": token_budget,
                "estimated_tokens": 0,
                "evidence_count": 0,
                "evidence": [],
                "text": "",
            }

        document_cache: dict[int, tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]] = {}
        used_context_keys: set[tuple[str, int]] = set()
        evidence: list[dict[str, Any]] = []
        rendered: list[str] = []
        consumed = 0

        for result in results:
            if len(evidence) >= max_evidence or consumed >= token_budget:
                break
            document_id = int(result.get("document_id") or 0)
            chunk_id = int(result.get("chunk_id") or result.get("id") or 0)
            parent_id = int(result.get("parent_block_id") or 0)
            if not document_id or not chunk_id:
                continue
            if document_id not in document_cache:
                chunks = self.db.list_knowledge_chunks(document_id)
                parents = {
                    int(item["id"]): item
                    for item in self.db.list_knowledge_parent_blocks(document_id)
                }
                document_cache[document_id] = (chunks, parents)
            chunks, parents = document_cache[document_id]
            parent = parents.get(parent_id)
            remaining = token_budget - consumed
            if remaining < 64:
                break

            expansion = "matched_chunk"
            context_key = ("chunk", chunk_id)
            text = str(result.get("matched_row") or result.get("text") or "").strip()
            heading = str(result.get("heading_path") or "").strip()

            # Prefer a coherent parent block when it is compact enough. Large
            # parents use local neighbor expansion so one section cannot consume
            # the entire prompt budget.
            if parent:
                parent_text = str(parent.get("text") or "").strip()
                parent_tokens = _estimate_tokens(parent_text)
                parent_limit = min(900, max(220, token_budget // 2))
                parent_key = ("parent", parent_id)
                if parent_text and parent_tokens <= parent_limit and parent_key not in used_context_keys:
                    text = parent_text
                    expansion = "parent"
                    context_key = parent_key
                else:
                    current = next((item for item in chunks if int(item.get("id") or 0) == chunk_id), None)
                    if current:
                        ordinal = int(current.get("ordinal") or 0)
                        local = [
                            item
                            for item in chunks
                            if abs(int(item.get("ordinal") or 0) - ordinal) <= neighbor_window
                            and (
                                not parent_id
                                or int(item.get("parent_block_id") or 0) == parent_id
                            )
                        ]
                        local.sort(key=lambda item: (int(item.get("ordinal") or 0), int(item.get("id") or 0)))
                        if local:
                            # Put the matched chunk first so token truncation can
                            # never discard the actual hit in favor of a long
                            # preceding neighbor. Nearby chunks follow as context.
                            ordered = [current] + [
                                item for item in local if int(item.get("id") or 0) != chunk_id
                            ]
                            text = "\n\n".join(
                                str(item.get("text") or "").strip()
                                for item in ordered
                                if str(item.get("text") or "").strip()
                            )
                            expansion = "neighbors" if len(local) > 1 else "matched_chunk"

            if context_key in used_context_keys:
                continue
            # Keep room for additional evidence rather than allowing the first
            # hit to consume the entire budget.
            per_item_cap = min(900, remaining)
            text = _truncate_to_tokens(text, per_item_cap)
            if not text:
                continue
            estimated = _estimate_tokens(text)
            if estimated > remaining:
                text = _truncate_to_tokens(text, remaining)
                estimated = _estimate_tokens(text)
            if not text or estimated <= 0:
                continue

            page_start = result.get("page_start")
            page_end = result.get("page_end")
            source = str(result.get("source_name") or result.get("document_title") or "Knowledge")
            label_bits = [source]
            if heading:
                label_bits.append(heading)
            if page_start:
                page_label = f"page {page_start}" if not page_end or page_end == page_start else f"pages {page_start}-{page_end}"
                label_bits.append(page_label)
            evidence_id = f"K{len(evidence) + 1}"
            label = " — ".join(label_bits)
            item = {
                "evidence_id": evidence_id,
                "chunk_id": chunk_id,
                "document_id": document_id,
                "library_id": int(result.get("library_id") or 0),
                "document_title": result.get("document_title"),
                "source_name": result.get("source_name"),
                "heading_path": heading,
                "page_start": page_start,
                "page_end": page_end,
                "content_type": result.get("content_type") or "text",
                "expansion": expansion,
                "rerank_score": float(result.get("rerank_score") or 0.0),
                "estimated_tokens": estimated,
                "text": text,
            }
            evidence.append(item)
            rendered.append(f"[{evidence_id}] {label}\n{text}")
            used_context_keys.add(context_key)
            consumed += estimated

        return {
            "enabled": True,
            "token_budget": token_budget,
            "estimated_tokens": consumed,
            "evidence_count": len(evidence),
            "evidence": evidence,
            "text": "\n\n".join(rendered),
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
        *,
        weights: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        merged: dict[int, dict[str, Any]] = {}
        weights = weights or {"lexical": 1.0, "vector": 1.0, "table": 1.1}
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
    "DEFAULT_CONTEXT_TOKEN_BUDGET",
    "DEFAULT_CONTEXT_TOP_K",
    "CpuFeatureReranker",
    "QueryPlan",
    "EmbeddingProvider",
    "EmbeddingUnavailable",
    "FastEmbedMultilingualE5Small",
    "HybridRetriever",
    "KnowledgeRetrievalError",
    "LocalVectorIndex",
    "VectorIndexUnavailable",
    "VectorMatch",
    "normalize_query_text",
    "plan_query",
    "table_rows_from_chunk",
]
