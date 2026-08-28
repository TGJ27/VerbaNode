# VerbaNode v0.10.3 — Intelligent Knowledge Retrieval

v0.10.3 completes **Hybrid RAG Phase 4**. The Phase-3 BM25, multilingual dense-vector, and structured-table indexes now feed an adaptive CPU-first retrieval pipeline that can decide how to search, rerank the evidence, detect weak retrieval, remove repeated chunks, and assemble bounded hierarchical context. Chat and Voice are deliberately still disconnected from RAG until Phase 5 so retrieval can be benchmarked independently before prompt cutover.

## What is included

- Deterministic query normalization preserves technical identifiers while cleaning whitespace/Unicode punctuation.
- A cheap query router classifies each question as `exact`, `semantic`, `table`, or `table_exact` and exposes its routing rationale in search diagnostics.
- Hybrid RRF is now query-aware: exact/code questions favor BM25, semantic questions favor the dense E5 channel, and tabular/numeric questions favor structured table rows.
- A lightweight deterministic **CPU feature reranker** reorders the top candidate set using term coverage, heading/title coverage, exact identifiers, dense similarity, channel agreement, RRF strength, phrase matches, and table intent. It does not require another neural model download and adds negligible memory compared with a cross-encoder.
- Low-confidence hybrid searches automatically perform one bounded wider candidate pass. This does not call the LLM, generate alternate queries, or use HyDE, keeping CPU latency predictable.
- Same-document exact/near-duplicate chunks are removed after reranking so overlapping chunks do not consume the final context budget.
- Top evidence is expanded hierarchically: compact parent sections are preferred; large sections use the matched chunk plus nearby sibling chunks. The matched chunk is always kept first when truncation is required.
- The context builder enforces a configurable token budget, emits stable `K1`, `K2`, ... evidence blocks, preserves source/title/heading/page metadata, and reports `safe_to_inject` based on retrieval confidence.
- `/api/knowledge/search` remains the standalone benchmark/debug surface and now accepts `adaptive`, `build_context`, `context_top_k`, `context_token_budget`, and `neighbor_window` options.
- Knowledge retrieval API negotiation advances to version 2. Database schema remains **v13**, so Phase 4 requires no schema migration.

## CI fix included

The clean Windows GitHub Actions runner previously failed while collecting `tests/test_v0101_knowledge_ingestion.py` with:

`ModuleNotFoundError: No module named 'docx'`

The test job installed the lightweight Core requirements but not the Phase-2 document fixture libraries. `requirements-dev.txt` now explicitly includes the Knowledge ingestion test dependencies (`python-docx`, `openpyxl`, `python-pptx`, `pdfplumber`, `beautifulsoup4`, Pillow, ReportLab, and NumPy), and the workflow installs that dev set directly. This also prevents the next clean-runner failures that would otherwise have appeared after `python-docx` (for example ReportLab used by the PDF fixture).

## CPU behavior

Phase 4 deliberately does **not** add a second neural reranker model. The existing multilingual E5 query embedding remains the only neural retrieval inference in the normal hybrid path. RRF, routing, feature reranking, confidence calculation, deduplication, and context construction are all small deterministic CPU operations. A future optional neural cross-encoder can be benchmarked behind the reranking boundary without changing the search API or Phase-5 prompt integration.

## Intentionally not enabled yet

- Chat/Voice RAG context injection (Phase 5)
- migration/removal of the existing Information prompt path (later cutover)
- VLM/image-semantic reasoning
- LLM multi-query expansion or HyDE as a default retrieval step

The existing Information path therefore remains temporarily active and unchanged. Android v0.3.6 remains compatible and does not require an update for Phase 4.

## Upgrade

Fully stop VerbaNode Core, replace the release files, and start Core again. No database migration is required because the Knowledge schema remains v13. Existing Phase-3 indexes continue to work; Phase 4 operates on top of those indexes immediately.
