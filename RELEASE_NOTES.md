# VerbaNode v0.10.2 — Hybrid Knowledge Retrieval

v0.10.2 completes **Hybrid RAG Phase 3**. The normalized Knowledge content created by Phase 2 is now independently searchable through a CPU/local hybrid retrieval engine. Chat and Voice are deliberately not connected to RAG yet; this release gives us a stable surface for retrieval benchmarking before reranking and prompt cutover.

## What is included

- Database schema v13 adds external-content SQLite FTS5 indexes for Knowledge chunks and structured table rows, persistent vector-record metadata, and per-library index status metadata.
- BM25/FTS5 handles exact terminology, IDs, model numbers, error codes, filenames, numbers, and ordinary lexical matches.
- Dense retrieval uses CPU-only `intfloat/multilingual-e5-small` through FastEmbed. The model produces 384-dimensional multilingual vectors and uses explicit `query:` / `passage:` prefixes.
- Each Knowledge library receives its own local cosine ANN index. USearch HNSW is the preferred backend with float16 vector storage; a portable NumPy exact-search fallback keeps dense retrieval functional if the native ANN runtime cannot load.
- Structured tables are indexed as rows while preserving headers/cells and their source chunk/document metadata. Table matches are returned with the matched header, cells, and row representation.
- Hybrid mode merges lexical, dense-vector, and structured-table candidates with Reciprocal Rank Fusion (RRF). Raw BM25 and cosine scales are therefore never incorrectly averaged together.
- Enabled-library filters and agent-to-library permissions are resolved **before** retrieval so disallowed libraries never enter the candidate set.
- `/api/knowledge/search` exposes `hybrid`, `lexical`, `vector`, and `table` modes for Phase-3 testing. `/api/knowledge/index/status` exposes model/backend/count state.
- Background index maintenance includes per-document reindex plus per-library/all-library rebuild. Existing Phase-2 libraries are fully rebuilt when their first dense index is created so older documents are not omitted.
- Dense indexing/search errors are isolated. BM25 and structured-table search continue to work and the API reports a warning/partial index state rather than making Knowledge unavailable.
- `VERBANODE_KNOWLEDGE_EMBEDDING_THREADS` controls local embedding CPU threads (default 2).
- Windows packaging collects the FastEmbed and USearch runtime modules required by the dynamically loaded retrieval backend.

## Local CPU behavior

The embedding model is loaded lazily. Starting Core does not download or load it. The first dense indexing or vector search can download the model into the local Knowledge cache when it is not already present. Subsequent operations reuse that local model. BM25/FTS5 and table retrieval do not require the embedding model.

The full `requirements.txt` enables dense retrieval. Minimal/core-only development installs that omit FastEmbed/USearch can still run lexical/table retrieval and will report dense retrieval as unavailable.

## Intentionally not enabled yet

- cross-encoder reranking (Phase 4)
- query routing/normalization and confidence fallback (Phase 4)
- parent/neighbor expansion and final context packing (Phase 4)
- Chat/Voice RAG context injection (Phase 5)
- migration/removal of the existing Information prompt path (later cutover)
- VLM/image-semantic reasoning

The existing Information path therefore remains temporarily active and unchanged. Android v0.3.6 remains compatible and does not require an update for Phase 3.

## Upgrade

Fully stop VerbaNode Core, replace the release files, and start Core again. Schema migration v13 runs automatically and the existing recovery system creates the normal pre-migration database snapshot. Existing Phase-2 chunks are backfilled into FTS5 by migration; use the Knowledge index rebuild endpoint when you want to generate dense vectors for already-ingested libraries.
