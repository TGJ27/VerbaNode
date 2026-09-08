# Changelog

## v0.12.5 - Connection and LAN discovery hardening

- Added versioned active UDP discovery alongside the existing `_verbanode._tcp.local.` mDNS advertisement.
- Active discovery exposes only public identity/compatibility metadata and never credentials.
- `/api/client-info` now advertises active-discovery capability, port, and protocol version for Android v0.5.2.
- Windows development firewall setup now permits the configured VerbaNode UDP discovery port on Private networks.
- REST API v1, WebSocket protocol v1, database schema v14, and mobile contract v1 remain unchanged.

## v0.12.4 - Agent mobile contract and CI hardening

- Advertise the existing agent role-generation endpoint and critical request/response fields in mobile contract v1 for Android v0.5.1.
- Validate mobile-contract routes against FastAPI OpenAPI output rather than internal route objects, including normalized path converters.
- Update Windows CI setup actions while preserving REST API v1, WebSocket protocol v1, and database schema v14.


## v0.12.3 - Knowledge mobile contract expansion

- Added the existing Knowledge re-ingest, ingestion-job, and per-agent library-assignment routes to the machine-readable mobile contract.
- Declared `library_ids` for dedicated agent Knowledge permission updates from the authoritative Pydantic schema.
- Added contract regression coverage for Android Knowledge Management Phase 2.
- Keeps REST API v1, WebSocket protocol v1, database schema v14, and Hybrid RAG behavior unchanged.

## v0.12.2 - Mobile contract hardening

- Added a versioned `mobile_contract` manifest to `/api/client-info` for Core ↔ Android compatibility negotiation.
- Declared the full Android REST operation set, API/WebSocket versions, session header, WebSocket paths, critical request/response fields, and protocol close codes.
- Added regression tests that compare all advertised mobile operations against the actual FastAPI route table and authoritative request models.
- Keeps REST API v1, WebSocket protocol v1, database schema v14, Hybrid RAG Phase 7, and existing client compatibility unchanged.

## v0.12.1 - Windows audio playback recovery

- Added a last-resort in-process HostAudioPlayer fallback when isolated Audio Engine playback remains unavailable after the normal restart/device-recovery path.
- Added session-only fallback to the Windows system-default output when a previously saved output endpoint still enumerates but cannot be opened; explicit output-device tests remain strict and never silently switch devices.
- Added fallback state/reason fields to player health so Diagnostics can show when recovery is active.
- TTS now records playback-layer errors in `last_error` after successful synthesis, improving diagnosis when every audio-producing feature shares a speaker failure.
- Added regression coverage for stale saved-output fallback and strict explicit-device testing.
- Database schema remains v14; no migration is required.

## v0.12.0 - Knowledge management and production hardening (Hybrid RAG Phase 7)

- Moved Phase-6 dense E5/HNSW finalization out of the FastAPI startup critical path so Core can become healthy/ready immediately after normal service initialization; BM25 remains usable while dense indexing runs in the background.
- Added persistent dense-index progress reporting (`index_total`, `index_completed`, and current library) and Knowledge change broadcasts when background finalization completes or fails.
- Added full Web Knowledge management: library CRUD, migrated/manual document list, text create/edit, file upload, delete/reindex, source/chunk inspection, retrieval testing, index rebuild, and fixed-view pagination without adding dashboard scrollbars.
- Added manual-text document APIs and original-source download support while keeping parsing/OCR/indexing authoritative in Core.
- Made manual text immediately BM25-searchable and queued dense indexing in the background rather than synchronously loading the embedding model on save.
- Added Phase-7 client capability flags for Knowledge management, text documents, and background indexing.
- Added Android v0.4.0 compatibility contract and management APIs for the same Knowledge Libraries/documents used by Web.
- Kept schema v14 and Hybrid RAG retrieval semantics unchanged; no VLM is introduced.
- Added Phase-7 regression coverage for startup non-blocking behavior, manual-text lexical readiness, management APIs, fixed Web layout, and feature negotiation.

## v0.11.1 - Legacy Information migration and retirement (Hybrid RAG Phase 6)

- Added schema v14 to convert every legacy Information row into Hybrid RAG Knowledge documents and permanently retire the old `information` / `agent_information` tables.
- Preserved legacy access by grouping migrated rows only by exact agent-assignment set plus enabled state; disabled and unassigned content retain those semantics.
- Made migrated text immediately BM25-searchable inside the migration and added post-migration dense-index finalization through the existing multilingual E5/HNSW pipeline.
- Changed fresh-install company knowledge seeding to create a real Knowledge Library/document/chunk instead of legacy Information rows.
- Removed legacy Information CRUD from the database layer and removed the Legacy Information management UI from the Web dashboard.
- Added a bounded Knowledge overview and paginated per-agent Knowledge Library assignment controls without introducing dashboard/sidebar scrolling.
- Kept `/api/information` only as an old-client compatibility shim: reads return an empty list and writes return HTTP 410.
- Added old-client agent-update protection so Android v0.3.6 payloads that omit `knowledge_library_ids` preserve existing migrated RAG permissions instead of clearing them.
- Added migration regression tests covering exact agent access, disabled/unassigned entries, immediate BM25 retrieval, fresh-install retirement, and Web UI retirement.
- Advanced Knowledge Engine phase reporting to `legacy_information_migrated`; Chat/Voice Hybrid RAG from Phase 5 remains active.

## v0.11.0 - Knowledge Chat/Voice cutover (Hybrid RAG Phase 5)

- Connected the Phase-4 hybrid retrieval/context builder to the shared conversation path used by Web Chat, typed input, browser PTT, and continuous Voice.
- Removed unconditional legacy Information injection from LLM turns. Legacy rows remain persisted only for the planned Phase-6 migration.
- Added per-turn agent-library filtering, bounded context budgeting, confidence-gated evidence injection, and compact source metadata on `knowledge_retrieval` / `assistant_complete` events and API results.
- Deterministic core-tool requests bypass RAG so live tool commands do not incur embedding/retrieval work.
- Retrieval failures and low-confidence matches fail open to normal conversation with no knowledge context rather than failing or contaminating the turn.
- Updated Knowledge/client capability negotiation to advertise Chat and Voice integration while explicitly reporting legacy prompt injection as disabled.
- Fixed the stale schema-version CI regression by replacing the hardcoded `== 10` migration assertion with registry-driven `CURRENT_SCHEMA_VERSION` validation.
- Database schema remains v13; no migration is required for Phase 5.

## v0.10.3 - Intelligent Knowledge retrieval (Hybrid RAG Phase 4)

- Added deterministic query normalization and an adaptive router for exact/identifier, semantic, table, and table+exact questions.
- Added query-aware RRF weights so BM25 dominates identifier/code lookups, vector retrieval is favored for semantic paraphrases, and structured-table retrieval is favored for numeric/tabular questions.
- Added a lightweight CPU feature reranker that combines query-term coverage, heading/title coverage, exact identifier matches, dense cosine similarity, channel agreement, RRF strength, phrase matches, and table intent without introducing another neural model or model download.
- Added confidence scoring and a single bounded candidate-widening fallback for low-confidence hybrid retrieval; no LLM query rewriting or HyDE call is used.
- Added same-document near-duplicate suppression to reduce overlapping/repeated chunks before context construction.
- Added hierarchical parent/neighbor expansion and a token-budgeted context builder that emits stable `K1`, `K2`, ... evidence blocks with source/title/heading/page metadata.
- Added a `safe_to_inject` confidence gate to context previews in preparation for the Phase-5 Chat/Voice cutover; Chat/Voice still do not consume RAG in this release.
- Advanced Knowledge retrieval API negotiation to version 2 and exposed Phase-4 capabilities in `/api/client-info` and Knowledge status.
- Fixed clean Windows GitHub Actions collection of Phase-2 ingestion tests by declaring `python-docx`, `openpyxl`, `python-pptx`, `pdfplumber`, `beautifulsoup4`, Pillow, ReportLab, and NumPy in `requirements-dev.txt`; CI now installs that single dev dependency set.
- Database schema remains v13; Phase 4 requires no data migration.
- No VLM is introduced and Android v0.3.6 remains compatible.

## v0.10.2 - Hybrid Knowledge retrieval (Hybrid RAG Phase 3)

- Added database schema v13 with external-content FTS5 indexes for Knowledge chunks and structured table rows, plus vector-record and per-library index metadata.
- Added SQLite FTS5/BM25 lexical retrieval for exact technical terms, identifiers, model numbers, codes, and ordinary text.
- Added CPU-only `intfloat/multilingual-e5-small` (384-dimensional) embeddings through FastEmbed with explicit E5 query/passage prefixes.
- Added persistent per-library USearch HNSW cosine indexes using float16 storage, with a portable NumPy exact-search fallback if the native backend is unavailable.
- Added structured table-row indexing so headers/cells remain queryable without flattening away table identity.
- Added Reciprocal Rank Fusion (RRF) across lexical, dense-vector, and table channels and applied enabled-library/agent-library filters before retrieval.
- Added authenticated Knowledge search/index-status APIs plus background document reindex and library/all-library rebuild endpoints.
- Dense-index failures are isolated: lexical/table retrieval remains available and the affected document/index exposes a partial/error state instead of disabling Knowledge search.
- Added packaged FastEmbed/USearch collection and configurable local embedding CPU threads.
- Kept reranking and Chat/Voice RAG context injection disabled until Phase 4/5; the legacy Information injection remains temporarily active until cutover/migration.
- No VLM is introduced, and Android v0.3.6 remains compatible.

## v0.10.1 - Universal Knowledge ingestion (Hybrid RAG Phase 2)

- Added universal local document ingestion for PDF, DOCX, XLSX/XLSM, CSV/TSV, PPTX, HTML, Markdown, TXT, JSON, XML, source/code files, and common raster images.
- Added schema v12 `knowledge_document_assets` for OCR/image metadata without introducing a VLM.
- Added structure-preserving extraction for headings, pages/slides/sheets, tables, image OCR, metadata, parent blocks, and retrieval-ready child chunks.
- Added CPU OCR fallback for scanned/image-only content and preserved original source files for future reprocessing.
- Added streamed bounded uploads, background ingestion jobs, re-ingestion, document deletion, supported-format reporting, and normalized-content inspection APIs.
- Kept BM25, embeddings, vector search, reranking, and Chat/Voice retrieval disabled until later Hybrid RAG phases.
- Removed the Conversation control-rail scrollbar/42vh cap and restored a fixed viewport dashboard layout with compact non-scrolling audio controls.
- No Android change is required; Android v0.3.6 remains compatible.

## v0.10.0 - Knowledge Engine foundation (Hybrid RAG Phase 1)

- Added database schema v11 with canonical Knowledge Engine tables for libraries, documents, ingestion jobs, hierarchical parent blocks/chunks, and agent-to-library permissions.
- Added a local-first Knowledge Engine service boundary and stable runtime layout under the VerbaNode user-data directory (`knowledge/sources`, `knowledge/indexes`, and `knowledge/cache`).
- Added authenticated `/api/knowledge/*` foundation endpoints for engine status, library CRUD, document/job inspection, and agent-library assignments.
- Added client feature negotiation for the Knowledge Engine foundation while explicitly advertising that parsing/retrieval/chat integration are not enabled yet.
- Added document/job/block/chunk persistence primitives for Phase 2 ingestion without selecting a parser, embedding model, vector backend, or reranker prematurely.
- Kept the existing Information prompt path active during Phase 1 only; the planned later cutover will migrate existing entries and remove unconditional factual prompt injection.
- No Android client change is required for this backend foundation release.

## v0.9.6 - Type-to-Talk migration-independent self-heal

- Add schema migration v10 to force a canonical rebuild of `type_to_talk_queue` for databases already stamped schema v9.
- Validate/repair the Type-to-Talk queue on every Core startup, independent of migration metadata.
- Add request-time recovery: if Send encounters a Type-to-Talk SQLite schema error, Core force-repairs the queue and retries the insert exactly once.
- Remove all persistent SQLite triggers whose SQL references `type_to_talk_queue`, not only triggers attached directly to that table.
- Replace the prior `EXPLAIN` probe with a real rolled-back production-shaped INSERT, so trigger execution is validated too.
- Preserve valid queued text while rebuilding and reset playback state to `waiting`.

## v0.9.5 - Type-to-Talk database schema repair

- Add schema migration v9 to remove unsupported legacy Type-to-Talk SQLite triggers that can reference the obsolete `error` column.
- Rebuild malformed Type-to-Talk queue tables while preserving valid queued text.
- Normalize queue state/indexes and compile the production INSERT during startup so schema incompatibilities are caught before use.
- Keep the v0.9.4 best-effort playback/audio cleanup behavior.

## v0.9.4 - Type-to-Talk 500 reliability fix

- Isolate all competing-playback cleanup during Type-to-Talk submission so stale/restarting subsystems cannot raise HTTP 500.
- Add schema migration v8 to self-repair the Type-to-Talk queue table/index and reset stale playing rows.
- Return an explicit 503 with diagnostic detail if queue insertion itself is unavailable.

## v0.9.4 - Type-to-Talk reliability hotfix

- Fixed a Core-side HTTP 500 affecting Type-to-Talk from both the web dashboard and Android clients when the microphone/audio engine was idle, unavailable, or restarting.
- Idle Type-to-Talk requests now stop only current speech/output instead of tearing down the conversation microphone path.
- Conversation shutdown now treats capture cancellation, PTT cancellation, and microphone unlock as best-effort cleanup so transient audio-engine failures do not abort API requests.
- Added regression tests for the idle Type-to-Talk path and resilient conversation-stop cleanup.

## v0.9.2 - Direct speech and workflow UX

- Added a persistent server-side Type-to-Talk queue shared by the web and Android clients; queued text goes directly to TTS without LLM processing.
- Added persistent script speech defaults so language, TTS mode/voice, speech rate, and volume are reused across new script entries instead of resetting.
- Hardened Android model selection by combining shared configuration choices with the live installed Ollama model catalog.
- Expanded the Audio Library to common formats including WAV, MP3, FLAC, OGG/OGA, Opus, M4A, AAC, WMA, AIFF/AIF, WebM audio, MKA, and AMR, with optional FFmpeg fallback decoding.
- Added client feature negotiation for Type-to-Talk, script defaults, and broad audio formats.
- Advanced database schema to v7 for the persistent Type-to-Talk queue.
- RAG/large-knowledge retrieval remains intentionally deferred to a later release.
- Coordinated with VerbaNode Android v0.3.3.


## v0.9.1 - Media library and queue UX

- Added MP3/WAV Audio Library APIs and web Audio page.
- Added shared configuration-option API for web/mobile selectors.
- Added script queue loop, per-item post-play pause, and drag reorder support.
- Moved source-mode identity/state to stable user data with one-time v0.9.0 migration.
- Expanded chat space and moved the web auto-scroll toggle below the composer.
- Advanced database schema to v6 and added v0.9.1 regression coverage.
- Coordinated with VerbaNode Android v0.3.2.


## v0.9.0 - Local mobile and trusted devices

- Added schema v5 trusted-device registry with hashed device credentials, last-seen metadata, revocation, rename, and delete support.
- Added short-lived QR and numeric-code pairing with memory-only pairing secrets and rate-limited public claims.
- Added trusted-device controller authentication through `/api/auth/device-login` while retaining PIN login and the single-active-controller policy.
- Added authenticated device-management and pairing APIs plus `/api/discovery/status`.
- Added persistent VerbaNode instance identity and mobile/device feature negotiation to `/api/client-info`.
- Added DNS-SD/mDNS advertisement on `_verbanode._tcp.local.` with Core/API/WS/instance/TLS identity metadata.
- Added stable SHA-256 SPKI server identity and reuse of the existing HTTPS private key when certificate SANs are refreshed after LAN-address changes.
- Added Settings → Devices web UI for QR/code pairing, discovery state, trusted-device rename/revoke/delete, and active-controller visibility.
- Added `zeroconf`, `qrcode`, and explicit `cryptography` runtime dependencies and packaged collection support.
- Updated the source firewall helper for both the configured VerbaNode TCP port and mDNS UDP 5353 on Private networks.
- Added 0.9.0 local-mobile regression coverage; 222 Core tests pass.
- Remains LAN-only: no cloud relay, Internet remote control, or multi-controller ownership is introduced.

## v0.8.5 - Stabilization

- Added WebSocket heartbeat watchdogs, bounded reconnect backoff, session revalidation, and connection-generation protection in the browser client.
- Added server-side WebSocket idle timeout handling and same-origin browser WebSocket enforcement while retaining originless/native-client support.
- Added deterministic stale controller/session cleanup and one-time WebSocket ticket invalidation.
- Added startup reconciliation for inherited `pending`/`running` actions: expired deadlines become `expired`; remaining orphaned work becomes `interrupted`.
- Added security headers/CSP and configurable early limits for declared JSON request bodies.
- Replaced unbounded browser-PTT and ASR benchmark upload reads with bounded incremental reads.
- Hardened clean source first run by seeding `.env` and generating a random six-digit PIN when the configured PIN is blank or placeholder.
- Split the framework-free dashboard further into chat, agents, plugins, settings, data-recovery, runtime, client, browser-PTT, and diagnostics modules; `app.js` is now below 1,000 lines.
- Added backup/recovery status and restore-progress UX with correlated request IDs on errors.
- Added `scripts/release/verify_release.py` and wired release checks into CI and the Windows packaging flow.
- Fixed Windows short-TTL action classification so deadline-limited execution is persisted as `expired` rather than occasionally `timed_out`.
- Fixed a capability-cancellation race so provider `cancel()` hooks are invoked even when an operation task is cancelled before its first execution slice.
- Expanded stabilization coverage to 215 automated tests in the clean v0.8.5 source tree.
- Continued to defer mobile discovery/pairing, trusted-device credentials, cloud relay, and robot-specific hardware providers.

## v0.8.4 - Client readiness

- Added public non-secret `/api/client-info` compatibility metadata for the existing web dashboard and future manually configured mobile clients.
- Centralized REST API/WebSocket protocol constants and client-facing feature negotiation metadata.
- Extended controller login with optional client type/version/API metadata while preserving legacy request compatibility.
- Added random non-secret controller `session_id` values and authenticated `/api/session` metadata.
- Added explicit `409 incompatible_api_version` negotiation failures for clients that request unsupported REST API versions.
- Added VerbaNode version/API/WebSocket compatibility headers and no-store policy to `/api/*` responses.
- Added explicit WebSocket protocol mismatch handling with `protocol_error` and close code `4406`, while retaining legacy commands that omit a protocol field.
- Split dashboard runtime/client transport/browser microphone logic into `runtime.js`, `client.js`, and `browser-ptt.js`; the framework-free `app.js` is now under 1,800 lines.
- Fixed dashboard structured API-error parsing so parsed error metadata remains in scope when constructing client errors.
- 203 automated tests passing in the clean v0.8.4 source tree.
- Kept the controller policy single-active-controller and continued to defer mobile pairing, LAN discovery, trusted-device credentials, cloud relay, and robot-specific hardware providers.

## v0.8.3 - Recovery hardening

- Advanced the numbered database migration system to schema v4 and moved remaining legacy column upgrades out of `Database.initialize()`.
- Added ordered/contiguous migration registry validation, per-migration SQLite savepoints, downgrade refusal, `PRAGMA user_version`, VerbaNode `application_id`, and persistent `schema_migrations` history.
- Added automatic pre-migration database recovery snapshots with bounded retention.
- Upgraded ZIP backups to format v3 with database byte-size and SHA-256 integrity metadata while retaining validated v1/v2 restore compatibility.
- Hardened restore archive parsing against path traversal, duplicate members, symlinks, oversized payloads, foreign databases, schema inconsistencies, and checksum/size tampering.
- Replaced WAL file copying with SQLite-native online backup snapshots and SQLite-native restore with automatic pre-restore rollback.
- Added authenticated `/api/backup/status` recovery/schema visibility.
- Added v0.8.3 migration, backup-integrity, tamper, recovery-snapshot, restore, and retention regression coverage.
- 197 automated tests passing in the clean v0.8.3 source tree.
- Kept mobile discovery/pairing and robot-specific hardware providers intentionally out of scope.

## v0.8.2 - Capability foundation

- Added a provider-neutral `app/capabilities` layer with provider interface, registry, requests/results, namespace validation, and bounded execution service.
- Extended `CapabilityGateway` with async provider invocation while preserving explicit plugin manifest permission checks.
- Added deterministic capability-to-permission mapping for robot, display, camera, microphone, serial, MQTT, network, internet, shell, and filesystem namespaces.
- Added global/per-provider execution limits, provider timeouts, argument-size limits, TTL/expiry, cancellation hooks, and provider shutdown handling.
- Added authenticated capability metadata and active-operation cancellation APIs.
- Added authenticated parent action cancellation that propagates into active provider operations.
- Advanced the persistent action ledger to schema v3 with `expires_at`; expired actions are terminal and are not re-executed after a deadline or restart.
- Added v0.8.2 provider, permission, concurrency, expiry, cancellation, migration, and API regression tests.
- Kept mobile discovery/pairing and robot-specific hardware providers intentionally out of scope.
- 187 automated tests passing in the clean v0.8.2 source tree.

## v0.8.1 - Architecture hardening

- Reduced `app/main.py` from roughly 1,100 lines in early v0.8 work to about 100 lines by extracting system/bootstrap, diagnostics, audio/runtime settings, AI, and TTS APIs into dedicated routers.
- Added request correlation IDs to REST responses through `X-Request-ID`; safe caller-supplied IDs are preserved and invalid/missing IDs are generated automatically.
- Added structured HTTP/validation error envelopes with stable error codes, request IDs, and optional details while preserving the existing top-level `detail` field for compatibility.
- Added request IDs to the standard Python log format so backend log entries can be correlated with REST failures.
- Removed the unused takeover approval request/poll/respond implementation and dashboard takeover modal. Correct PIN authentication remains the single controller authorization boundary and transfers control deterministically.
- Tightened same-process action idempotency by reserving an in-flight leader future before the SQLite claim; concurrent duplicate callers now reliably join the same execution.
- Prevented terminal/interrupted ledger rows from being overwritten by late completions by restricting completion updates to active actions.
- Moved diagnostics rendering/refresh code into `app/static/js/diagnostics.js`, beginning incremental browser modularization without introducing a framework.
- Updated the dashboard API client to understand structured error metadata (`code`, `request_id`, and details).
- Kept mobile app, mDNS/Bonjour discovery, QR pairing, trusted-device credentials, cloud relay, and robot-specific hardware providers out of scope.
- 178 automated tests passing in the clean v0.8.1 source tree.

## v0.8.0 - Architecture foundation

- Consolidated source startup into one root `run.bat`; removed the redundant `run_http.bat` and `run_https.bat` wrappers.
- Fixed nested source helpers so `scripts/windows/generate_local_cert.py`, `scripts/windows/test_audio.py`, and `scripts/setup/setup_database.py` can always import `app.*` from the repository root.
- Added explicit repository `PYTHONPATH` bootstrapping and source-runner regression tests to prevent `ModuleNotFoundError: No module named 'app'` from returning.
- Added a persistent SQLite action ledger with globally bound action IDs, canonical argument hashes, terminal result replay, and crash-safe non-retry semantics.
- Prevented concurrent duplicate explicit action IDs from executing the same capability twice.
- Added authenticated action history/status APIs.
- Added migration schema version 2 for the action ledger.
- Split agents, information, scripts/queue, conversations, plugins, models, actions, and backup/restore into FastAPI routers, reducing the `app/main.py` monolith.
- Added versioned WebSocket protocol v1 with request IDs and backwards-compatible event/legacy-command support.
- Updated the web dashboard to send protocol-v1 WebSocket commands.
- Hardened restore with streaming upload, bounded sizes, backup manifest/schema validation, SQLite integrity checks, automatic safety backup, and atomic database replacement.
- Kept mobile app, LAN discovery, pairing, trusted-device credentials, cloud relay, and robot-specific providers explicitly out of scope for this release.
- 171 automated tests passing in the assembled clean v0.8.0 source tree.

## v0.7.7 - Pre-major hardening and conversation UX

- Added strict persistent chat Auto-scroll lock and new-message jump control.
- Added active agent language/STT/TTS/LLM context chips in Conversation.
- Added PIN login throttling and one-time WebSocket tickets.
- Removed controller session tokens from WebSocket URLs.
- Added verified plugin action metadata, idempotency action IDs, capability gateway, and action audit logging.
- Added numbered database migration foundation.
- Split authentication/WebSocket API routes out of `app/main.py`.
- Removed duplicate setup/plugin-manager code introduced by previous patching.
- Added Ruff correctness and JavaScript syntax checks to CI.
- Isolated Windows packaging in a `verbanode-build` Conda environment and pinned packaging tool versions.
- Centralized release version usage around `app/version.py`.
- Replaced the legacy `VN` web badge with the application logo and aligned the web favicon/cache-busters to v0.7.7.
- 160 automated tests passing.

## v0.7.6 - Windows online installer

- Add one-file Inno Setup 7 online installer around the frozen VerbaNode application.
- Add English SenseVoiceSmall and Indonesian Whisper Base/Small/Both setup choices.
- Add optional Kokoro local TTS download.
- Add Ollama detection/install and local model pull during setup.
- Add installer-triggered database backup/migration and HTTPS certificate initialization.
- Use the approved VerbaNode icon for both the application EXE and Setup EXE.
- Keep Program Files binaries separate from persistent LocalAppData/model caches so upgrades preserve user data.
- Fix the previous Inno warnings by using a common Startup shortcut and an UninstallRun RunOnceId.
- Reorganize repository utilities into `scripts/setup/`, `scripts/models/`, and `scripts/windows/`.
- Move PyInstaller files into `packaging/` and group documentation by architecture, plugins, features, and packaging.
- Keep primary run/build entry points in the root while updating all path references and regression tests; 151 automated tests pass.

## v0.7.5 - Windows application packaging preview

- Added a PyInstaller onedir build for `VerbaNode.exe`.
- Added a native Windows launcher that supervises the HTTPS backend, reports Core/Audio/AI/Ollama status, and lists usable dashboard IP addresses with Open/Copy actions.
- Added frozen-runtime path separation so installed binaries stay read-only while agents, scripts, settings, plugins, certificates, diagnostics, and VerbaNode-managed models live under `%LOCALAPPDATA%\VerbaNode`.
- Preserved the existing source development workflow through `run.bat` and `run_https.bat`.
- Added internal HTTPS certificate generation fallback for packaged systems without Conda OpenSSL.
- Added Windows packaging documentation, build dependencies, PyInstaller spec, and regression tests.


## v0.7.4 - Stable bilingual assistant foundation

- Promoted the v0.7 bilingual assistant line to stable after final regression validation.
- Consolidated English SenseVoiceSmall and Indonesian Whisper Base/Small agent profiles with persistent active-agent selection.
- Includes selective short-term context, empty-Ollama-response recovery, per-script TTS, Edge voice management, Indonesian deterministic routing, ASR status/benchmark tooling, and plugin hardening.
- Fixed Windows Whisper Base/Small cache detection so existing OpenAI Whisper checkpoints are reported correctly.
- Updated stable release documentation and version metadata.
- 121 automated tests pass.

## v0.7.3 - Bilingual stabilization and UX cleanup

- Added Whisper Base/Small cache visibility so the dashboard shows whether Indonesian ASR models are already downloaded before switching.
- Added a one-click active language profile test that warms the selected ASR model and plays a matching Edge TTS sample without writing to chat history.
- Disabled ASR reload/benchmark controls while model operations are already loading or reloading.
- Improved English/Indonesian agent voice normalization and script language/TTS compatibility checks.
- Added clearer Indonesian script guidance and disabled incompatible Kokoro controls for Indonesian scripts.
- Added regression tests for model-cache detection, language profile validation, and the bilingual UI controls.

## 0.7.2

- Hardened the bilingual ASR path with automatic Indonesian Whisper Small to Whisper Base fallback when the accuracy-first model fails or times out.
- Expanded deterministic Indonesian time, date, weather, location, and stop-conversation routing for more natural phrases and common STT variations.
- Added an ASR status card showing the active agent model, actually loaded model, load latency, last transcription latency, completed jobs, fallback state, and last error.
- Added a real-audio Indonesian ASR benchmark that compares Whisper Base and Whisper Small on the target machine and reports load time, transcription latency, RTF, confidence, and transcript before restoring the active model.
- Preserved active-agent ASR selection after benchmarking and exposed active-agent data in the runtime status API.
- Added bilingual hardening regression tests; 115 automated tests pass.

## 0.7.1

- Persisted the active agent across VerbaNode restarts instead of resetting to the default English agent.
- Improved Indonesian location routing and common Whisper transcription variants.
- Added Whisper Small as an optional higher-accuracy Indonesian ASR model alongside Whisper Base.
- Improved Whisper model preparation for Base, Small, or both models.
- Normalized accidental Markdown emphasis before chat display and TTS playback.
- 112 automated tests pass.

## 0.7.0

- Added per-agent English and Bahasa Indonesia language profiles.
- Kept SenseVoiceSmall as the English low-latency ASR model.
- Added Whisper Base through FunASR for Indonesian-only decoding.
- Added a default Ropi Indonesia agent with Indonesian character instructions, greeting, Edge TTS, and Gadis voice.
- Added hidden active-language prompt enforcement and localized deterministic tool responses.
- Added per-script language, provider, Edge voice, Kokoro voice, speech rate, volume, and provider-aware preview.
- Added automatic SQLite migrations for agent language and Script TTS fields.
- Added `openai-whisper`, `scripts/models/download_whisper.bat`, setup documentation, and regression tests.
- 107 automated tests pass.

## 0.6.7

- Fixed a typed-chat interruption deadlock that could occur when a new text message was submitted while streamed TTS was still playing.
- Streaming TTS cancellation now always restores terminal queue markers after draining pending work, so generator and player workers cannot remain blocked indefinitely.
- Added bounded cancellation cleanup that force-cancels unresponsive TTS workers after 2.5 seconds while preserving idempotent stop events.
- Added regression tests for the exact removed-sentinel race and repeated cancellation; 100 automated tests pass.

## 0.6.6

- Changed conversation memory to selective short-term context: complete history remains stored, but prior messages and summaries are only injected for explicit recall requests and clear follow-up references.
- Added bounded memory selection with at most eight recent messages plus a compact summary under a conservative context budget.
- Added reduced-context Ollama recovery: an empty HTTP 200 response retries once without memory, knowledge, or tool schemas, then returns a controlled visible fallback instead of saving a blank assistant message.
- Expanded deterministic location matching for natural phrases such as `Where are we currently at?` and `Where are we right now?`.
- Added a real Edge voice dropdown, locale filter, online voice-catalogue refresh, bundled offline fallback voices, and voice preview playback.
- Updated the Agent Memory panel to explain selective context behavior.
- Added selective-memory, empty-response recovery, location-routing, Edge voice, and frontend regression tests; 98 automated tests pass.

## 0.6.3

- Added strict external plugin package validation for manifest size, entry size, semantic versions, supported permission labels, safe folder names, symbolic links, and reserved IDs.
- Added recursive LLM tool-schema validation before registration.
- Added bounded plugin execution with per-call timeout, active execution tracking, and cancellation when a conversation stops.
- Added consecutive-failure tracking and automatic `unhealthy` isolation after a configurable threshold.
- Added recovery controls for unhealthy built-in plugins and repair/reload controls for external plugins.
- Changed external reload to validate replacement code before stopping the working version; failed updates now keep the previous version available and report a reload error.
- Added shutdown-hook timeouts, reload/error counters, timeout/cancellation metrics, registry generation, and hardening settings to diagnostics and Plugin Manager payloads.
- Added Windows `tzdata` dependency plus a fixed UTC+7 fallback for `Asia/Jakarta`.
- Added plugin manifest/security documentation and an ignored `plugins/_template/` starter package.
- Added plugin hardening regression tests; 90 automated tests pass.

## 0.6.2

- Added startup and on-demand discovery of trusted local Python plugins from the top-level `plugins/` folder.
- Added strict JSON manifest validation, SDK-major compatibility checks, safe entry-path validation, duplicate-ID protection, and tool-schema verification.
- Unified built-in and external capabilities in the existing Plugin Registry without changing the conversation or LLM tool interfaces.
- Added per-plugin and reload-all lifecycle controls, safe unload when a plugin folder is removed, and optional async shutdown hooks.
- Added failed-load isolation and dashboard reporting for missing manifests, invalid JSON, unsupported SDK versions, import errors, factory errors, and duplicate IDs.
- Added built-in/external source labels, external plugin paths, SDK versions, reload controls, and failed-load cards to the responsive Plugins page.
- Added the `example_echo` reference plugin and external-plugin developer documentation.
- Preserved Phase 2 global enable/disable state and migrated it to the generalized `disabled_plugins` setting while maintaining downgrade compatibility.
- Added regression tests for discovery, execution, reload, folder removal, load-error recovery, duplicate IDs, APIs, and UI integration.

## v0.6.1 - Built-in Plugin Manager Phase 2

- Added a responsive Plugins page with global enable/disable controls for built-in capabilities.
- Persisted disabled plugin IDs in SQLite settings and restored them at startup.
- Added plugin metadata, health state, permissions, agent assignment counts, execution/error totals, and latency metrics.
- Added per-plugin and global metric reset actions.
- Added authenticated Plugin Manager APIs and live `plugins_changed` dashboard events.
- Added Plugin Manager information to bootstrap, runtime status, diagnostics snapshots, exports, and the non-destructive self-test.
- Marked globally disabled tools inside the agent editor without deleting agent assignments.
- Kept external plugin discovery, installation, manifests, removal, and hot reload out of scope for Phase 2.

## v0.6.0 - Internal plugin architecture Phase 1

- Split current time, location, weather, and stop-conversation capabilities into independent built-in plugin modules.
- Added an ordered plugin registry and manager with execution health and latency metrics.
- Kept the existing ToolService API, agent tool IDs, prompts, database settings, and conversation behavior backwards compatible.
- Added internal plugin architecture documentation and automated tests.

## 0.5.3

- Added frontend/backend version capability checks for Diagnostics.
- Replaced repeated 404 `Not Found` toasts with a clear update/restart notice when static files and the running backend do not match.
- Added an explicit Diagnostics capability declaration to `/api/bootstrap`.
- Aligned Diagnostics health, self-test, soak, latency, log, and export cards to a consistent grid.
- Added four loading placeholders so the health row remains straight before the first runtime snapshot.

## 0.5.2

- Added a dedicated Diagnostics Settings submenu with Core, Audio Engine, AI Engine, system-resource, heartbeat, queue, and restart health cards.
- Added non-destructive system self-tests for SQLite, writable runtime directories, Audio Engine responsiveness, Windows audio endpoints, AI Engine responsiveness, Ollama, and pipeline state.
- Added rolling redacted runtime logs with level filtering, dashboard clearing, and safe diagnostics ZIP export.
- Added per-turn latency history for STT, LLM, tools, TTS, and total response time without storing conversation content.
- Added configurable 5-minute to 2-hour soak monitoring for CPU, RAM, process RSS, thread counts, engine heartbeat age, queue use, restart deltas, and pipeline errors.
- Added process-level resource metrics for Core, Audio Engine, and AI Engine.
- Added an SVG favicon so normal dashboard startup no longer produces a favicon 404.
- Added diagnostics privacy protections: session tokens are redacted and exports exclude `.env`, PIN, database, conversations, certificates, caches, and model files.
- Added Phase 3 diagnostics regression tests; 70 automated tests pass.

## 0.5.1

- Reorganized the Settings page into Conversation, Host audio, AI models, Runtime, and Data submenus.
- Added responsive desktop side navigation and mobile horizontal category navigation for Settings.
- Added the persistent `show_rejected_stt_transcripts` runtime setting.
- Added a dashboard toggle to show or hide low-confidence STT transcripts that were not sent to the agent.
- Restyled rejected transcripts as muted gray diagnostic messages with a Filtered STT label.
- Prevented hidden rejected transcripts from removing the empty conversation state or cluttering the visible chat.
- Added database, schema, static UI, and version regression tests.

## 0.5.0

- Added a supervised AI Engine child process that owns SenseVoice/FunASR and local Kokoro native model objects.
- Added asynchronous model preload, persistent model reuse, model reload controls, heartbeat monitoring, and automatic AI process restart.
- Added bounded ASR and Kokoro queues with one active inference per provider.
- Routed immutable PCM utterances to the AI Engine and returned structured transcription results with confidence metadata.
- Routed Kokoro generation to the AI Engine while keeping Edge TTS and Ollama outside it.
- Added AI Engine and model health, load time, inference latency, queue depth, PID, heartbeat, and restart information to the API and dashboard.
- Added authenticated Restart AI Engine, Reload SenseVoice, and Reload Kokoro actions.
- Added an in-process compatibility mode through `VERBANODE_AI_ENGINE_PROCESS=false`.
- Added Phase 3 process, proxy, queue-boundary, and shared-audio-path tests.

## 0.4.2

- Added a real Windows/PortAudio hot-plug refresh operation inside the isolated Audio Engine.
- Changed the dashboard Refresh Devices action from passive enumeration to safe audio shutdown, PortAudio reinitialization, fingerprint remapping, and updated device enumeration.
- Added automatic recovery and retry for microphone locking, speaker locking, host PTT, microphone tests, utterance capture, and speaker playback.
- Added an 8–10 second staged retry window for Bluetooth/USB endpoint registration after connection.
- Added a final Audio Engine process restart fallback when a PortAudio refresh cannot reopen the requested endpoints.
- Improved default-device inspection so the active Windows profile sample rate is used even when the default numeric ID is temporarily unavailable.
- Added fallback sample-rate, channel, and latency negotiation for Windows input/output streams.
- Added device refresh count, hot-plug recovery count, and last recovery reason to runtime health.
- Added regression tests for PortAudio reinitialization, default-device profile inspection, and proxy-level hot-plug retries.

## 0.4.1

- Added a hidden no-emoji output policy and backend Unicode sanitization for streamed chat, stored assistant messages, generated roles/greetings, summaries, and TTS input.
- Discarded emoji-only TTS chunks so reaction icons cannot create empty or delayed speech requests.
- Changed Stop Conversation to stop current playback and clear pending sentence/audio queues immediately by default.
- Kept Stop Current TTS effective for both streamed assistant speech and non-streamed scripts/greetings through the isolated Audio Engine.
- Cached the Silero VAD model once per Audio Engine process instead of initializing it for every conversation turn.
- Added Phase 2 regression tests for output sanitization, multilingual text preservation, emoji-free TTS, and default stop behavior.

## 0.4.0

- Moved native host microphone and speaker ownership into one supervised Audio Engine child process.
- Added spawn-safe command/response IPC proxies for device enumeration, persistent locks, host PTT, utterance capture, playback, cancellation, tests, and health.
- Kept VAD, PortAudio callbacks, input frame queues, and speaker buffers inside the child process so per-frame audio does not cross IPC.
- Added an Audio Engine watchdog, automatic process restart, in-flight call failure handling, and restoration of requested device/lock state.
- Added Audio Engine PID, coordinator state, heartbeat age, and restart count to API and dashboard runtime status.
- Added an authenticated dashboard action to stop active audio work and manually restart the Audio Engine.
- Added `VERBANODE_AUDIO_ENGINE_PROCESS=false` compatibility mode for troubleshooting.
- Added process lifecycle, proxy-health, restart, and error-translation tests.
- Preserved the v0.3.3 database, UI, layered prompt architecture, natural tool routing, Edge/Kokoro fallback, and browser-device PTT behavior.

## 0.3.3

- Expanded deterministic core-tool routing to ignore natural greetings, wake words, and polite wrappers such as “hello Ropi” and “please”.
- Added conservative fuzzy matching for minor ASR and typing errors in current time/date requests, including “what day its its?”.
- Applied the same greeting handling to location, weather, and stop-conversation requests.
- Preserved exclusions for unrelated phrases such as time complexity and meeting-time questions.
- Added regression tests proving natural current-time requests bypass the LLM and use the configured `Asia/Jakarta` time tool directly.
- Removed device-brand-specific audio guidance from the dashboard while preserving device selection and persistent stream locking.
- Consolidated repository release documentation into `CHANGELOG.md` plus a single current `RELEASE_NOTES.md`.

## 0.3.2

- Refactored prompt construction into hidden core, voice-output, tool, runtime, knowledge, memory, and agent-character layers.
- Reduced the editable Ropi prompt to identity, domain, personality, and speaking style only.
- Kept deterministic core-tool routing and all operational tool rules outside the agent role.
- Added internal memory and retrieved-knowledge policies that treat injected content as data rather than instructions.
- Updated the agent editor and AI role generator so new character prompts do not contain tools, memory, safety, or runtime instructions.
- Added a one-time migration that replaces the known v0.3.1 operational Ropi prompt while preserving genuinely customized Ropi prompts.
- Added layered-prompt and migration regression tests.

## 0.3.1

- Strengthened the default Ropi role with mandatory live-data and physical-action rules.
- Added deterministic routing for unambiguous time/date, location, weather, and conversation-stop requests.
- Added configurable default timezone support and changed the time tool to use it.
- Restored Ropi's four core tools during the one-time v0.3.1 database migration while preserving extra tools and the user's STT threshold.
- Removed redundant HTTPS heartbeats whenever the WebSocket heartbeat is active.
- Filtered only the harmless Windows Proactor `WinError 10054` disconnect-cleanup callback without hiding other asyncio errors.
- Added regression tests for tool routing, LLM bypass, prompt migration, and Windows reset filtering.

## 0.3.0

- Added authoritative pipeline states and turn, capture, generation, and sentence identifiers.
- Added bounded TTS queues, ASR retry/timeout, direct PCM recognition, and provider health metrics.
- Changed the legacy 88% heuristic STT gate to 70% while preserving deliberate custom thresholds.
- Added Ollama timeouts, tool timeouts, up to three tool rounds, and interrupted tool-history repair.
- Added Edge/Kokoro retry, circuit breaking, and faster first-clause TTS.
- Added resilient audio-device fingerprints and device recovery counters.
- Rebuilt the dashboard with a responsive XiaozhiConsole-inspired desktop and phone layout.
- Preserved the GitHub deployment structure, CI workflow, generated controller PIN, and `data/verbanode.db` migration path.

## 0.2.6

- Added browser-device push-to-talk over HTTPS.
- Added persistent host microphone and speaker handling with selectable devices.
- Added requester-confirmed immediate controller takeover.
- Added expired-session and WebSocket recovery.
- Added script and greeting TTS caching.
- Added streamed sentence-level LLM-to-TTS playback.
- Added STT confidence threshold controls.
- Set Ropi defaults to `qwen3.5:0.8b`, 88% STT threshold, and 224 maximum response tokens.
- Added explicit database setup tooling for repository deployments.
- Fixed the conversation side rail alignment so controls no longer leave a large empty area above them.
- Type to Talk now has its own remembered TTS configuration and a chat-style send/queue experience.
- Added MPEG-family audio uploads (`.mpeg`, `.mpg`, `.mpga`, `.mp2`, `.mpa`) in addition to existing formats.

