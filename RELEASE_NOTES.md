# VerbaNode v0.11.0 — Hybrid RAG Chat/Voice Cutover

v0.11.0 completes **Hybrid RAG Phase 5**. The Knowledge Engine is no longer only a standalone search/debug subsystem: normal LLM turns from Web Chat, typed input, browser PTT, and continuous Voice now retrieve bounded evidence from the active agent's assigned Knowledge Libraries before the prompt is built.

## Prompt behavior changed

The old Information system is no longer concatenated into every prompt. Legacy Information rows and agent links remain in the database only so Phase 6 can migrate them safely; they are not used as factual LLM context in v0.11.0.

For an ordinary turn, Core now:

1. checks whether the request is a deterministic live-tool command; those commands skip RAG;
2. resolves the active agent's enabled Knowledge Libraries;
3. runs the Phase-4 hybrid retrieval pipeline (BM25 + multilingual dense vectors + structured tables + weighted RRF + CPU reranking);
4. applies confidence fallback/deduplication and builds parent/neighbor context;
5. injects evidence only when `safe_to_inject` is true;
6. continues with no knowledge context if retrieval is weak or unavailable; and
7. returns compact source/confidence metadata with the completed turn.

The knowledge context budget is derived from the active agent's model context size and capped so system/agent policy, selective conversation memory, tools, the current user message, and model output retain room. The full knowledge library is never appended to the prompt.

## Shared Chat and Voice path

All normal conversational entry points already converge on `ConversationManager.process_user_text()`. Phase 5 integrates RAG at that shared boundary, so Web Chat, typed input, browser PTT, host PTT/voice, and continuous conversation receive the same retrieval behavior without duplicating retrieval logic in clients.

## Failure behavior

Knowledge retrieval is intentionally non-fatal. Missing dense-model/runtime support can still fall back to lexical/table retrieval inside the Knowledge Engine, and an unexpected retrieval/index failure causes the turn to continue without RAG rather than returning an error to the user. Low-confidence evidence is likewise omitted instead of being forced into the prompt.

## CI regression fixed

A historical test still asserted `version == CURRENT_SCHEMA_VERSION == 10`, even though the Knowledge phases advanced the canonical schema to v13. That test now validates against the migration registry/current schema value rather than an obsolete literal, preventing future numbered migrations from breaking the same assertion again.

## Compatibility

- Database schema: **v13** (unchanged; no migration)
- Knowledge retrieval API: v2 (unchanged)
- Knowledge prompt integration capability: v1
- VLM: not used
- Android v0.3.6 remains compatible; Android does not perform retrieval locally
- Phase 6 will migrate legacy Information records into Knowledge Libraries and retire the old management model

## Upgrade

Fully stop VerbaNode Core, replace the release files, and start Core again. Existing Phase-3/4 Knowledge indexes remain usable immediately. Because schema v13 is unchanged, no database migration runs for this release.
