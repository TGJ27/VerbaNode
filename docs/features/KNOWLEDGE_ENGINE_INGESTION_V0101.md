# Knowledge Engine Phase 2 — Universal Ingestion (v0.10.1)

Phase 2 turns the Phase-1 metadata foundation into a real local document-ingestion system while intentionally stopping before retrieval/indexing.

## Supported source families

- PDF, including scanned/image-only pages through CPU OCR when available
- DOCX
- XLSX/XLSM
- CSV/TSV
- PPTX
- HTML/HTM
- Markdown and plain text
- JSON/XML
- common source/code/config files
- PNG/JPEG/WebP/BMP/TIFF images through OCR only (no VLM)

## Normalized representation

Every source is retained as the original file and parsed into document-aware parent blocks. Searchable child chunks preserve heading paths, page/slide/sheet location, content type, table identity, and source metadata. Tables remain explicit table blocks rather than being flattened into one prompt string.

Image assets retain OCR text and source/page metadata. The design deliberately keeps original images so a future optional VLM can be added without changing document storage or ingestion contracts.

## Runtime flow

1. Stream upload to a bounded staging file.
2. Move the source into local Knowledge storage and create document/job metadata.
3. Parse with the format-specific parser.
4. Use OCR only where native text is missing or the source itself is an image.
5. Normalize extracted structure into parent blocks and child chunks.
6. Persist extracted asset metadata/OCR.
7. Mark lexical/vector states `pending` for Phase 3.

Retrieval remains disabled in v0.10.1, so Chat/Voice prompt behavior is unchanged.
