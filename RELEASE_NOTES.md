# VerbaNode v0.10.1 — Universal Knowledge Ingestion

v0.10.1 completes **Hybrid RAG Phase 2**. The local-first Knowledge Engine can now accept and normalize large mixed document sources while retrieval remains deliberately disabled until Phase 3.

## What is included

- Database schema v12 adds persistent `knowledge_document_assets` so extracted/OCR image metadata is retained without requiring a VLM.
- Upload/ingestion APIs now accept PDF, DOCX, XLSX/XLSM, CSV/TSV, PPTX, HTML, Markdown, TXT, JSON, XML, common source/code files, and common raster image formats.
- Native structure is retained where possible: document headings, pages/slides/sheets, tables, captions/labels, source metadata, and page ranges are normalized into the Phase-1 parent-block/child-chunk model.
- PDF parsing extracts text and tables; image-only/scanned pages use CPU OCR when the OCR runtime is available.
- DOCX, PPTX, and standalone image ingestion can retain extracted image assets and OCR text. No VLM is used.
- XLSX/CSV ingestion keeps row/column structure in table blocks instead of flattening an entire workbook into prompt prose.
- Structure-aware chunking creates retrieval-ready child chunks with heading context and estimated token counts. Lexical/vector states remain `pending` for Phase 3.
- Ingestion runs as a background task after the source has been safely stored. Jobs expose queued/running/completed/failed stage and progress state and support re-ingestion.
- Original source files remain authoritative under the local Knowledge directory; generated assets are stored separately and can be rebuilt.
- Added document deletion, re-ingestion, supported-format inspection, and normalized-content inspection APIs.
- Uploads are streamed to disk and bounded by `VERBANODE_KNOWLEDGE_MAX_UPLOAD_BYTES` (1 GiB default).

## Dashboard regression fix

- The dashboard shell remains fixed to the viewport.
- The Conversation control rail no longer has its own scrollbar or a `42vh` height cap.
- Conversation controls were compacted so Global Audio Control, Now Speaking, and Quick Scripts fit the fixed rail at normal desktop heights.
- Native scrollbars are hidden throughout the dashboard so nested scrollbar chrome does not reappear; the main shell itself does not move.
- On narrow/mobile layouts, the duplicated desktop Conversation rail is not stacked below Chat; the existing mobile voice dock provides those controls inside the fixed viewport.

## Intentionally not enabled yet

- BM25/FTS indexing
- embeddings/HNSW vector indexing
- hybrid retrieval/RRF
- reranking
- Chat/Voice RAG context injection
- migration/removal of the existing Information prompt path
- VLM/image semantic reasoning

The existing Information path therefore remains active only until the later cutover phase. Android v0.3.6 remains compatible and does not require an update for Phase 2.

## Upgrade

Fully stop VerbaNode Core, replace the release files, and start Core again. Schema migration v12 runs automatically and the existing recovery system creates the normal pre-migration database snapshot.
