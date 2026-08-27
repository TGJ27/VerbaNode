# Knowledge Engine Foundation — v0.10.0

## Scope

v0.10.0 is Phase 1 of VerbaNode's planned replacement of unconditional Information injection with hierarchical Hybrid RAG. It is additive: Chat/Voice still use the legacy Information path until the later cutover phase.

## Runtime boundary

All application callers use `KnowledgeEngine`; they do not depend directly on future FTS, vector, parser, OCR, or reranker implementations. The initial backend is local. A future remote/LAN Knowledge service can be introduced behind the same Core-facing boundary.

Runtime layout:

```text
<VerbaNode user data>/knowledge/
├── sources/
├── indexes/
└── cache/
```

## Schema v11

- `knowledge_libraries`: user/agent-facing collections.
- `knowledge_documents`: canonical source metadata and indexing lifecycle.
- `knowledge_ingestion_jobs`: durable background-work lifecycle.
- `knowledge_parent_blocks`: document hierarchy/sections and future parent expansion.
- `knowledge_chunks`: child retrieval units and future lexical/vector index state.
- `agent_knowledge_libraries`: explicit agent access to libraries.

The hierarchy and metadata fields are deliberately parser-neutral so PDF, Office, spreadsheet, HTML/text, scanned-document, table, OCR-image, and later VLM-derived content can share one model.

## API

Authenticated endpoints under `/api/knowledge` expose engine status, library CRUD, document/job inspection, and agent-library assignment. Upload/ingestion endpoints are deferred to Phase 2.

## Safety of the phased rollout

Phase 1 does not alter `PromptComposer`, Chat, PTT, Conversation, Scripts, or TTS behavior. Existing Information entries are not migrated or deleted yet. This allows the new storage/API contract to be validated before retrieval becomes part of the conversation path.
