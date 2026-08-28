# Knowledge Engine Hybrid Retrieval — v0.10.2

VerbaNode v0.10.2 is Hybrid RAG Phase 3. It makes Phase-2 normalized Knowledge content searchable without connecting retrieval to Chat/Voice yet.

## Retrieval channels

The local retrieval engine runs three independent channels and fuses them with Reciprocal Rank Fusion (RRF):

1. **Lexical** — SQLite FTS5/BM25 over normalized Knowledge chunks. This is the exact-match path for technical terms, identifiers, codes, names, and ordinary text.
2. **Dense** — `intfloat/multilingual-e5-small` (384 dimensions) through FastEmbed/ONNX on CPU. Vectors are stored per Knowledge library in a USearch HNSW cosine index. A NumPy exact-search file is used as a resilience fallback if the native ANN backend cannot load.
3. **Structured tables** — extracted table chunks are indexed row-by-row while preserving headers, cells, source chunk/document, page range, and heading metadata.

RRF combines ranks rather than averaging incompatible BM25 and cosine scores. Table results have a small fusion weight advantage when the same table chunk appears across channels.

## Permissions and scope

Knowledge library enablement and agent-to-library assignments are resolved before the retrieval channels execute. A request scoped to an agent therefore searches only enabled libraries assigned to that agent. Optional explicit library IDs can narrow the scope further but cannot expand agent permissions.

## Dense model lifecycle

The embedding model is lazy. Core startup does not load or download the model. The first dense indexing/search operation initializes FastEmbed and may download model files into `knowledge/cache/embeddings` if they are not already cached.

`VERBANODE_KNOWLEDGE_EMBEDDING_THREADS` controls the CPU thread count and defaults to 2.

Dense failures do not make Knowledge unusable. Phase 3 records a partial/error state for dense indexing and keeps FTS5/table retrieval available.

## Index lifecycle

New/reingested documents are observed by the FTS5 triggers and indexed for tables/dense vectors after parsing. A populated Phase-2 library with no compatible vector index is rebuilt as a whole the first time dense indexing is requested, preventing older documents from being silently omitted.

The API also exposes explicit document reindex and library/all-library rebuild operations.

## API

- `GET /api/knowledge/index/status`
- `POST /api/knowledge/search`
- `POST /api/knowledge/index/rebuild`
- `POST /api/knowledge/documents/{document_id}/reindex`

Search modes are `hybrid`, `lexical`, `vector`, and `table`. Phase 3 is a retrieval/debug surface; it is not yet an LLM-context endpoint.

## Deferred to later phases

Phase 4 adds query routing/normalization, reranking, confidence fallback, parent/neighbor expansion, deduplication, and context budgeting. Phase 5 connects the resulting evidence pipeline to Chat/Voice and removes unconditional factual Knowledge injection during cutover. VLM/image-semantic reasoning remains disabled.
