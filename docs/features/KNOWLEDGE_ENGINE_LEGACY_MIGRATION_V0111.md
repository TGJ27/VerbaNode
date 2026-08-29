# Knowledge Engine legacy migration — v0.11.1

VerbaNode v0.11.1 completes Hybrid RAG Phase 6 by removing the pre-RAG Information storage model.

## Migration model

Schema v14 reads the legacy Information rows and their `agent_information` links before either table is removed. Rows are partitioned by `(enabled, exact assigned-agent set)`. Each partition becomes one Knowledge Library, each legacy row becomes one `legacy_information` Knowledge document, and the old assignment set becomes the new library permission set.

This grouping is intentionally conservative: two records are never placed in the same library if doing so could give an agent access to a record it did not previously own. Disabled content becomes a disabled library. Content with no legacy agent link remains in an unassigned library.

The original legacy ID, enabled state, agent IDs, and migration timestamp are retained in document/chunk metadata.

## Retrieval availability

Migration creates parent blocks and child chunks directly because numbered SQLite migrations must not depend on optional parser/model packages. Schema-v13 FTS triggers index those chunks immediately, so migrated data is BM25-searchable as soon as the migration commits.

After Core initializes, the Knowledge Engine attempts to rebuild dense indexes for migrated/default Knowledge through the existing multilingual E5/HNSW subsystem. Dense failure only marks the migration index as partial; lexical retrieval remains available.

## Fresh installations

The canonical base schema no longer creates `information` or `agent_information`. Packaged company knowledge is seeded directly into a Knowledge Library and assigned to the default agents.

## Compatibility boundary

The old `/api/information` routes remain temporarily so older clients do not fail bootstrap/read operations. Reads return an empty array and all mutations return HTTP 410. Core contains no legacy Information CRUD/storage path after schema v14.

When a pre-Phase-6 client updates an agent without the `knowledge_library_ids` field, Core preserves that agent's existing Knowledge permissions. Explicit modern-client library lists still replace assignments normally.

## UI

The Web dashboard now exposes a Knowledge overview rather than a Legacy Information page. Agent configuration uses Knowledge Library permissions. Lists are bounded/paginated to preserve VerbaNode's fixed single-viewport, no-inner-scroll layout.

Full Web/Android document upload, indexing controls, retrieval diagnostics, and library management remain Phase 7 work.
