# VerbaNode v0.12.0 — Hybrid RAG Knowledge Management & Hardening

v0.12.0 completes **Hybrid RAG Phase 7**. The single Knowledge Engine introduced across Phases 1–6 now has full day-to-day management surfaces, and dense-index work no longer blocks Core startup.

## Core startup fix

- Phase-6 E5/HNSW finalization is no longer awaited inside FastAPI startup.
- Core/launcher health becomes available after the normal Core/Audio/AI startup path instead of waiting for Knowledge embeddings/index rebuilds.
- BM25/FTS knowledge is immediately available while dense indexing continues as a background task.
- Knowledge status reports total/completed/current-library progress and broadcasts completion/failure.

## Knowledge management

- Full Web library and document management with fixed-view pagination (no new nested/page scrolling).
- Create/edit manual text knowledge, including migrated legacy text entries.
- Upload mixed document files to a selected library for the existing Phase-2 ingestion pipeline.
- Inspect normalized parent/chunk content and source metadata.
- Download an original stored source when one exists.
- Delete/reindex individual documents or rebuild a selected/all Knowledge index.
- Run retrieval tests and inspect confidence/top sources before relying on the result in Chat/Voice.
- Agent editors continue to assign explicit Knowledge Libraries.

## Indexing behavior

- Manual text is normalized and made BM25-searchable immediately.
- Dense E5/HNSW indexing is queued in the background so saving text does not synchronously load/download the embedding model.
- Dense failures remain isolated; lexical/table retrieval continues to work.

## Mobile/API

- `/api/client-info` now advertises Knowledge management, text-document editing, and background-indexing capabilities for Android v0.4.0.
- Added authenticated text-document create/update and original-source endpoints on the existing `/api/knowledge/*` surface.
- No VLM is introduced.

## Compatibility

- Database schema remains **v14**; no new migration is required from v0.11.1.
- Hybrid RAG Chat/Voice behavior from v0.11.0 and legacy migration/retirement from v0.11.1 remain intact.
- Android v0.4.0 is the matching full Knowledge-management client; older Android builds can still use non-Knowledge functions but do not satisfy the new v0.4.0 capability check.
