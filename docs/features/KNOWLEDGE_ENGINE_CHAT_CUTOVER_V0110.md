# Knowledge Engine Chat/Voice Cutover — v0.11.0

VerbaNode v0.11.0 is Hybrid RAG Phase 5. It connects the Phase-4 intelligent retrieval/context builder to the single conversation path shared by typed Chat, browser/host PTT, and continuous Voice.

## Turn flow

`user text -> deterministic tool check -> agent library filter -> hybrid retrieval -> confidence gate -> bounded evidence -> prompt -> LLM`

Legacy `information` records are no longer loaded by `ConversationManager` for prompt construction. They remain persisted only for Phase-6 conversion.

## Safety and availability

Only evidence whose context reports `safe_to_inject=true` is converted into prompt knowledge entries. Retrieval exceptions are logged and reported as compact turn metadata, but the LLM turn continues without knowledge. Deterministic core-tool routes skip RAG.

## Client metadata

Completed turn payloads include compact knowledge metadata (confidence/routing/source IDs and page/heading metadata) but do not broadcast full library content.
