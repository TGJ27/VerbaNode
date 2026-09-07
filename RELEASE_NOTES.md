# VerbaNode v0.12.3 — Knowledge Mobile Contract Expansion

v0.12.3 extends the existing Core ↔ Android mobile contract for Knowledge Management Phase 2 without changing REST API v1, WebSocket protocol v1, database schema v14, or Hybrid RAG behavior.

## Knowledge mobile operations

- Advertises document re-ingestion through `POST /api/knowledge/documents/{document_id}/reingest`.
- Advertises ingestion-job monitoring through `GET /api/knowledge/jobs`.
- Advertises dedicated per-agent Knowledge Library read/update routes.
- Declares the `library_ids` request field contract from the authoritative `AgentKnowledgeLibrariesUpdate` schema.

## Compatibility

- Mobile contract format remains version 1; this is an additive operation-set expansion.
- Existing Core clients remain compatible.
- VerbaNode Android v0.5.0+ requires these advertised Knowledge Phase 2 operations.
- No database migration is required.
