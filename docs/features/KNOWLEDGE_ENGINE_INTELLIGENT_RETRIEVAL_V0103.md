# Knowledge Engine Intelligent Retrieval — v0.10.3

VerbaNode v0.10.3 is Hybrid RAG Phase 4. It converts Phase-3 candidate retrieval into a final evidence-selection/context-construction pipeline while keeping Chat/Voice integration disabled for independent benchmarking.

## Query flow

```text
question
  -> normalize
  -> route (exact / semantic / table / table_exact)
  -> pre-filter allowed libraries
  -> BM25 + dense HNSW + structured table search
  -> query-aware weighted RRF
  -> CPU feature reranker
  -> confidence check
       -> low: one bounded wider retrieval pass
  -> same-document duplicate suppression
  -> parent/neighbor expansion
  -> token-budgeted evidence context
```

No LLM call is used before retrieval, and no VLM is used.

## CPU reranker

The Phase-4 reranker is deliberately deterministic rather than a second neural model. It combines signals already available from the hybrid search plus cheap text features. This avoids another model download, keeps RAM/CPU use low, and gives VerbaNode a stable reranking boundary where an optional cross-encoder can be benchmarked later.

## Confidence and context safety

Search results include a confidence score/label and whether adaptive widening was used. Context previews include `safe_to_inject`; Phase 5 can use that gate to avoid injecting low-confidence/irrelevant evidence into the LLM prompt.

## Context construction

Compact parent sections are used as coherent evidence when they fit. Large parents use the matched child chunk plus bounded neighbor chunks. Evidence is deduplicated and packed under a configurable token budget with source/title/heading/page metadata and stable `K1`, `K2`, ... labels.

## Still deferred

- Chat/Voice RAG injection
- migration/removal of legacy Information injection
- VLM/image reasoning
- default multi-query/HyDE
