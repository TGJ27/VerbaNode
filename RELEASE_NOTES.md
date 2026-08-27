# VerbaNode v0.10.0 — Knowledge Engine Foundation

v0.10.0 begins the planned replacement of VerbaNode's current always-injected Information/Knowledge path with a local-first hierarchical Hybrid RAG Knowledge Engine. This release is **Phase 1 only**: it establishes durable storage, APIs, permissions, and service boundaries without changing Chat or Voice prompt behavior yet.

## What is included

- Database schema v11 adds `knowledge_libraries`, `knowledge_documents`, `knowledge_ingestion_jobs`, `knowledge_parent_blocks`, `knowledge_chunks`, and `agent_knowledge_libraries`.
- Knowledge libraries can be created, renamed, enabled/disabled, listed, and deleted when empty. Library names are case-insensitively unique.
- Agents can be explicitly assigned one or more Knowledge libraries through a dedicated permission mapping. Existing Agent payloads remain compatible.
- Document metadata supports source type/name, MIME type, relative storage key, size, SHA-256, status/error, indexing timestamp, and JSON metadata.
- Ingestion-job metadata supports queue/running/completion state, stage, progress, attempts, timestamps, and errors.
- Parent blocks and child chunks preserve hierarchy, page ranges, heading paths, content type, token counts, and future lexical/vector indexing state.
- Runtime Knowledge storage is isolated under the normal VerbaNode user-data root with `sources`, `indexes`, and `cache` directories. `VERBANODE_KNOWLEDGE_PATH` can override the location.
- Authenticated Knowledge APIs are available under `/api/knowledge`. `/api/client-info` advertises the foundation and reports retrieval as disabled.

## Intentionally not enabled in Phase 1

- PDF/DOCX/XLSX/PPTX parsers
- OCR
- BM25/FTS indexing
- embeddings or HNSW vector search
- table retrieval
- RRF/reranking
- Chat/Voice RAG context injection
- migration of the existing Information entries
- Knowledge management UI in Web/Android

This separation is deliberate: Phase 1 gives later ingestion and retrieval work a stable schema and API contract without risking the existing conversation pipeline. The old Information entries continue to behave exactly as before until the planned cutover/migration phase; they are not the final architecture.

## Upgrade

Fully stop VerbaNode Core, replace the release files, and start Core again. Schema migration v11 runs automatically and a pre-migration backup is created by the existing recovery mechanism. Android v0.3.6 remains compatible and requires no update for Phase 1.
