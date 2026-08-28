<div align="center">

<img src="packaging/assets/VerbaNode.png" alt="VerbaNode" width="140">

# VerbaNode

### Local, modular voice-assistant platform for Windows

**Speech-to-Text · Local LLM · Text-to-Speech · Agents · Memory · Plugins · HTTPS Dashboard**

</div>

---

## Overview

VerbaNode is a Windows-first local voice-assistant platform designed for interactive robots, kiosks, desktop assistants, demonstrations, and other systems that need a configurable conversational interface.

The project combines speech recognition, local LLM inference, text-to-speech, agent profiles, selective short-term memory, script playback, information/knowledge entries, and a modular plugin system behind one responsive web dashboard.

VerbaNode can run directly from source for development or as a packaged Windows application. The Windows application uses a small native launcher to start and monitor the backend and expose the HTTPS dashboard on the local computer and available LAN interfaces.

> **Project status:** active development. v0.10.3 completes Hybrid RAG Phase 4: the Phase-3 BM25/vector/table indexes now feed adaptive query routing, weighted RRF, a lightweight deterministic CPU reranker, confidence-based widening, near-duplicate suppression, and bounded parent/neighbor context construction. Retrieval remains independently testable and is still **not** injected into Chat/Voice until Phase 5. The existing Information path remains active only until migration/cutover. No VLM is used. Android v0.3.6 remains compatible.

---

## Highlights

- **Local-first conversational pipeline**
  - Local LLMs through Ollama
  - Local speech recognition
  - Optional local TTS
  - Edge TTS support

- **Bilingual agent support**
  - English pipeline using SenseVoiceSmall
  - Bahasa Indonesia pipeline using Whisper Base or Whisper Small
  - Language-specific STT and TTS configuration per agent

- **Multiple interaction modes**
  - Conversation mode
  - Push-to-Talk
  - Click-and-Hold
  - Talk by Text
  - Script playback

- **Agent system**
  - Multiple configurable agents
  - Per-agent language, STT, TTS, role prompt, greeting, and UI identity
  - Active-agent persistence

- **Selective short-term memory**
  - Conversation history is stored
  - Relevant context can be supplied when needed instead of resending the entire conversation every turn

- **Intelligent Hybrid Knowledge retrieval (v0.10.3 / Hybrid RAG Phase 4)**
  - Local-first Knowledge libraries with explicit per-agent access and pre-retrieval filtering
  - Universal mixed-document ingestion for PDF, Office files, spreadsheets, text/web formats, images, and scans
  - Structure-preserving parent/child normalization for headings, pages, tables, slides, sheets, OCR, and metadata
  - SQLite FTS5/BM25 lexical search for exact names, codes, identifiers, and technical terminology
  - CPU-only `intfloat/multilingual-e5-small` dense embeddings (384 dimensions) with per-library local HNSW indexes
  - Structured table-row search with query-aware weighted Reciprocal Rank Fusion (RRF) across lexical, vector, and table channels
  - Cheap query normalization/routing distinguishes exact identifiers, semantic questions, and table/numeric questions
  - Lightweight deterministic CPU reranking combines dense similarity, exact identifiers, term/heading coverage, channel agreement, and content type without downloading a second model
  - Low-confidence hybrid searches widen candidate retrieval once without an extra LLM query-rewrite/HyDE call
  - Near-duplicate chunks are suppressed and top evidence expands to coherent parent/neighbor context under a configurable token budget
  - Context previews expose source/page metadata plus a `safe_to_inject` confidence gate for the later Phase-5 Chat/Voice cutover
  - Dense retrieval degrades safely: BM25/table search stays available if the embedding runtime/model is unavailable
  - No VLM or image-semantic reasoning; Chat/Voice RAG injection remains Phase 5
  - Existing Information entries remain temporarily active until the planned RAG cutover/migration phase

- **Plugin architecture**
  - Built-in plugins
  - External plugins
  - Plugin manifests, validation, metrics, hardening, and reload support
  - Permission-aware capability gateway foundation
  - Verified action results, action IDs/idempotency, and capability audit logging
  - Template and example plugin included

- **Windows application**
  - Standalone packaged `VerbaNode.exe`
  - Native launcher
  - Core / Audio Engine / AI Engine / Ollama health status
  - Dashboard PIN controls
  - HTTPS localhost and LAN address discovery
  - Graceful process-tree shutdown

- **Windows installer**
  - Standard Program Files installation
  - Upgrade-aware application identity
  - Persistent user data outside Program Files
  - Optional component/model setup with existing-model detection
  - Start Menu / Desktop shortcuts
  - Uninstall support

- **v0.10.3 Intelligent Knowledge retrieval**
  - Adds exact/semantic/table query routing and query-aware RRF channel weights.
  - Adds a bounded CPU feature reranker with no second neural-model download.
  - Adds confidence scoring and one-pass candidate widening for weak hybrid matches.
  - Adds same-document near-duplicate suppression plus parent/neighbor evidence expansion and token-budgeted context previews.
  - Adds a `safe_to_inject` context gate while intentionally leaving Chat/Voice integration disabled until Phase 5.
  - Fixes clean GitHub Actions test collection by installing the Phase-2 document fixture dependencies (`python-docx`, `openpyxl`, `python-pptx`, `pdfplumber`, `reportlab`, etc.) through `requirements-dev.txt`.
  - Keeps database schema v13; no migration is required for Phase 4.

- **v0.10.2 Hybrid Knowledge retrieval**
  - Adds schema v13 for FTS5 lexical indexes, structured table-row indexes, vector-record metadata, and per-library index metadata.
  - Adds CPU multilingual E5 embeddings and local USearch HNSW indexes, with a portable NumPy exact-search fallback when the native ANN backend is unavailable.
  - Adds `/api/knowledge/search`, `/api/knowledge/index/status`, document reindex, and library/all-library rebuild APIs.
  - Fuses BM25, dense-vector, and table-row candidates with RRF while enforcing enabled-library and agent-library filters before retrieval.
  - Keeps reranking and Chat/Voice context injection disabled for Phase 4/5 validation; no VLM is introduced.

- **v0.10.1 Universal Knowledge ingestion**
  - Adds schema v12 asset metadata and local `assets/` storage alongside sources/indexes/cache.
  - Parses PDF, DOCX, XLSX/XLSM, CSV/TSV, PPTX, HTML, Markdown, TXT, JSON, XML, code/text files, and raster images.
  - Preserves document structure and tables; scanned/image-only content can use local CPU OCR without a VLM.
  - Adds streamed bounded uploads, background ingestion jobs, re-ingestion, document deletion, and normalized-content inspection.
  - Keeps retrieval disabled until Phase 3 and keeps Android v0.3.6 compatible.
  - Restores a fixed dashboard viewport and removes the Conversation control-rail scrollbar regression.

- **v0.10.0 Knowledge Engine foundation**
  - Added schema v11 for Knowledge libraries, documents, ingestion jobs, hierarchical blocks/chunks, and agent-library permissions.
  - Added the local-first Knowledge service/API boundary used by Phase 2 and later retrieval phases.

- **v0.9.6 Type-to-Talk self-healing queue**
  - Adds schema migration v10, which force-rebuilds the direct-speech queue for databases already stamped v9.
  - Validates/repairs the queue on every Core startup rather than trusting schema metadata alone.
  - If Send hits a queue-schema SQLite error, Core repairs the queue immediately and retries the insert once.
  - Removes any persistent SQLite trigger whose SQL references `type_to_talk_queue`, including cross-table legacy triggers.
- **v0.9.5 Type-to-Talk database repair**
  - Removes unsupported legacy SQLite triggers that can reference the obsolete `error` queue column.
  - Rebuilds malformed Type-to-Talk queue tables while preserving valid queued text where possible.
  - Validates the production queue INSERT during startup migration before the dashboard/mobile client can submit speech.

- **v0.9.4 Type-to-Talk hotfix**
  - Prevents idle Type-to-Talk requests from unnecessarily tearing down the microphone/audio engine.
  - Makes conversation-stop audio cleanup best-effort so an engine restart cannot surface as a raw HTTP 500.
  - Applies to both the built-in web dashboard and native Android clients because they share the same Core API.

- **v0.9.2 direct speech & workflow UX**
  - Persistent Type-to-Talk queue shared by Web and Android; text goes directly to TTS without LLM processing
  - Remembered script language/TTS/voice/rate/volume defaults for faster multi-entry authoring
  - Common-format Audio Library with optional FFmpeg fallback decoding
  - Android model choices merged with the live installed Ollama model catalog
  - Coordinated with VerbaNode Android v0.3.3

- **v0.9.1 media library & queue UX**
  - Upload/play/rename/delete MP3 and WAV files through the host Audio Library
  - Persistent script-queue loop, per-item pause-after-playback, and drag reorder
  - Shared configuration options for web and Android model/language selectors
  - Stable Core identity/state across clean source-folder updates
  - Coordinated with VerbaNode Android v0.3.2
- **v0.9.0 local mobile & trusted devices**
  - DNS-SD/mDNS advertisement for automatic same-Wi-Fi discovery
  - QR and short-code pairing from Settings → Devices
  - Persistent trusted-device registry with hashed credentials and revocation
  - Stable HTTPS SPKI identity across certificate SAN refreshes
  - Trusted-device login reuses the existing single-active-controller policy
  - Manual IP/hostname connection remains available as a fallback
  - LAN-only by design; no cloud relay or Internet remote control
  - 222 automated Core tests pass in the clean v0.9.0 source tree

- **v0.8.5 stabilization**
  - WebSocket heartbeat/watchdog, bounded reconnect backoff, session revalidation, and same-origin browser WebSocket guard
  - Stale controller cleanup invalidates outstanding one-time WebSocket tickets
  - Startup reconciles orphaned persistent actions to `expired` or `interrupted` instead of leaving false `running` state
  - Baseline browser security headers/CSP plus configurable JSON-body limits and bounded speech uploads
  - Clean source first run seeds `.env` and generates a random PIN when the configured value is blank/placeholder
  - Dashboard split further into chat, agents, plugins, settings, data-recovery, transport/runtime, browser-PTT, and diagnostics modules; `app.js` is below 1,000 lines
  - Release verifier is shared by local development, CI, and Windows packaging
  - 215 automated tests pass in the clean v0.8.5 source tree

- **v0.8.4 client readiness**
  - Public `/api/client-info` exposes non-secret server/API/WebSocket/auth compatibility metadata before login
  - Login accepts optional client type/version/API metadata while preserving legacy browser/CLI compatibility
  - Controller sessions have non-secret `session_id` values and authenticated `/api/session` metadata
  - `/api/*` responses advertise VerbaNode/API/WebSocket versions and request correlation IDs
  - Explicit unsupported REST API versions receive a structured compatibility error; explicit unsupported WebSocket protocols receive `protocol_error` + close code `4406`
  - Dashboard transport/runtime/browser-microphone code is split into `runtime.js`, `client.js`, and `browser-ptt.js` without adding a frontend framework
  - Current controller ownership remains single-active-controller; v0.9.0 adds trusted Android handoff without concurrent ownership
  - 203 automated tests pass in the clean v0.8.4 source tree

- **v0.8.3 recovery hardening**
  - Numbered migration schema v4 is now the sole home for legacy schema upgrades
  - SQLite `application_id`, `user_version`, and `schema_migrations` history make database identity/versioning explicit
  - Existing older databases receive an automatic pre-migration recovery snapshot before upgrade
  - Backup format v3 records database size and SHA-256 and verifies both on restore
  - Restore rejects unsafe ZIP members, invalid/foreign/newer databases, and inconsistent schema metadata
  - SQLite online backup is used for consistent WAL-safe snapshots and restore, with automatic pre-restore rollback
  - Authenticated `/api/backup/status` exposes schema/backup format and automatic recovery snapshot inventory

- **v0.8.2 capability foundation**
  - New `app/capabilities` provider contract and registry for future robot/device/service integrations
  - Capability names map deterministically to plugin manifest permissions before provider execution
  - Provider execution is bounded globally and per provider, with configurable timeouts and argument limits
  - Capability requests have TTL/expiry and best-effort provider cancellation hooks
  - Parent plugin actions can be cancelled through the authenticated action API, propagating cancellation into active provider work
  - Persistent action ledger schema v3 stores `expires_at` and treats expired actions as terminal/non-retryable
  - Authenticated `/api/capabilities` metadata exposes providers, limits, and currently active provider operations
  - No robot-specific hardware provider or cloud/Internet relay is included; local mobile pairing/discovery is available in v0.9.0

- **v0.8.1 architecture hardening**
  - `app/main.py` reduced to application composition/lifecycle; system, diagnostics, audio, AI, and TTS endpoints now live in dedicated routers
  - REST correlation IDs (`X-Request-ID`) and structured API error envelopes while preserving the legacy `detail` field
  - Same-event-loop duplicate action IDs reserve one leader before touching SQLite, with the persistent ledger remaining the cross-process authority
  - Legacy takeover approval/polling routes and dashboard modal removed; a valid PIN deterministically transfers the single controller session
  - Diagnostics dashboard code moved into `static/js/diagnostics.js` as the first browser modularization step
  - v0.8.0 persistent action ledger, WebSocket protocol v1, migration v2, and hardened backup/restore remain the platform foundation

- **v0.7.7 pre-major hardening**
  - Strict chat Auto-scroll lock with persistent preference and new-message jump control
  - Active language/STT/TTS/model context in the Conversation header
  - PIN login throttling and one-time WebSocket tickets
  - Numbered database migration foundation
  - Auth API router split to keep `app/main.py` from continuing to grow monolithically
  - Isolated `verbanode-build` Conda environment with pinned Windows packaging dependencies
  - Ruff correctness checks and dashboard JavaScript syntax checks in CI

---

## Core Pipeline

```text
Microphone / Browser PTT / Typed Text
                |
                v
        +----------------+
        | Audio / Input  |
        +----------------+
                |
                v
        +----------------+
        |      STT       |
        | SenseVoice /   |
        | Whisper        |
        +----------------+
                |
                v
        +----------------+
        | Conversation   |
        | Controller     |
        +----------------+
          |      |      |
          |      |      +--------------------+
          |      |                           |
          v      v                           v
      Plugins  Memory / Info              Ollama
          |      |                           |
          +------+-------------+-------------+
                               |
                               v
                        +-------------+
                        | LLM Response|
                        +-------------+
                               |
                               v
                        +-------------+
                        |     TTS     |
                        | Edge/Kokoro |
                        +-------------+
                               |
                               v
                            Speaker
```

The packaged Windows application separates major runtime responsibilities into the VerbaNode Core, Audio Engine, and AI Engine so long-running audio and inference work are isolated from the dashboard/controller process.

---

## Speech and Voice Stack

| Function | English | Bahasa Indonesia |
|---|---|---|
| Speech recognition | SenseVoiceSmall | Whisper Base / Whisper Small |
| Local fallback | Agent/config dependent | Whisper Small can fall back to Base |
| Online TTS | Edge TTS | Edge TTS |
| Local TTS | Kokoro | Currently intended primarily for supported configured voices |
| LLM | Ollama models | Ollama models |

VerbaNode also exposes ASR status information such as the configured model, loaded model, load/transcription latency, fallback state, and errors.

---

## Windows Installation

### Option A — Installer

For normal users, use the Windows installer from the project's **GitHub Releases** page:

```text
VerbaNode-Setup-<version>.exe
```

The installer is intended to:

- install VerbaNode under `C:\Program Files\VerbaNode`
- create Windows shortcuts
- configure the application firewall rule
- initialize or migrate the VerbaNode database
- prepare HTTPS
- preserve existing user data during upgrades
- optionally prepare selected AI components/models

### Persistent data

Installed application binaries and user data are deliberately separated.

```text
C:\Program Files\VerbaNode\
    VerbaNode.exe
    _internal\
    ...
```

Persistent user state is stored under:

```text
%LOCALAPPDATA%\VerbaNode\
```

This includes application-managed data such as configuration, database state, certificates, plugins, diagnostics, backups, and other writable runtime files.

Model caches may also live in their normal user locations, for example:

```text
%USERPROFILE%\.cache\whisper\
%USERPROFILE%\.cache\modelscope\
%USERPROFILE%\.ollama\
```

**Upgrading VerbaNode should replace application binaries without deleting agents, scripts, information entries, settings, plugins, databases, certificates, or downloaded model caches.**

---

## Development Setup

### Requirements

Primary development target:

- Windows 10/11 x64
- Git
- Miniconda or Anaconda
- Python 3.11 environment
- Ollama for local LLM inference
- A working microphone and audio output device

### 1. Clone the repository

```powershell
git clone https://github.com/TGJ27/VerbaNode.git
cd VerbaNode
```

### 2. Run the Windows setup

```powershell
scripts\setup\setup_windows.bat
```

The setup script prepares the `verbanode` Conda environment and installs the required Python dependencies.

### 3. Initialize the database

```powershell
scripts\setup\setup_database.bat
```

### 4. Download optional/local models

Model helpers are grouped under:

```text
scripts\models\
```

Available helpers include:

```powershell
scripts\models\download_funasr.bat
scripts\models\download_whisper.bat
scripts\models\download_kokoro.bat
```

Only download the models required by the agents and TTS providers you plan to use.

### 5. Configure environment settings

Copy:

```text
.env.example
```

to:

```text
.env
```

and adjust the required values for your machine.

Do **not** commit `.env`, generated certificates, databases, model files, or runtime audio.

### 6. Start VerbaNode

Recommended development startup:

```powershell
run.bat
```

`run.bat` is the single source-development entry point. It activates the `verbanode` Conda environment, makes the repository root importable, and starts `launcher.py`. The launcher creates or refreshes the local HTTPS certificate automatically so browser microphone access and LAN dashboard access behave consistently with the packaged application.

---

## Dashboard Access

When VerbaNode is running, the dashboard is exposed through HTTPS.

Typical local address:

```text
https://127.0.0.1:8002
```

Available LAN/Wi-Fi addresses are shown by the packaged Windows launcher.

The launcher also exposes:

- service health
- Ollama connection status
- dashboard PIN Show / Hide / Copy
- Open Dashboard
- Restart Services
- Minimize
- Exit

HTTPS certificates are generated and maintained by VerbaNode for local operation.

---

## Building the Windows Application

The repository includes a PyInstaller-based Windows application build.

Run:

```powershell
build_windows.bat
```

The build script:

1. locates Conda
2. uses a separate `verbanode-build` Conda environment by default
3. creates that build environment when missing
4. installs the application requirements plus pinned packaging requirements
5. performs a clean PyInstaller build without modifying the normal development environment

Output:

```text
dist\
└── VerbaNode\
    ├── VerbaNode.exe
    └── _internal\
```

The application is intentionally packaged as **onedir** rather than a single-file PyInstaller executable because VerbaNode contains multiprocessing, native audio/ML libraries, model runtimes, and other resources that benefit from an explicit application directory.

---

## Building the Windows Installer

Install Inno Setup on the development machine, then run:

```powershell
build_installer.bat
```

Output:

```text
dist-installer\
└── VerbaNode-Setup-<version>.exe
```

Installer-related files live under:

```text
packaging\
├── VerbaNode.spec
├── VerbaNode.iss
├── requirements-packaging.txt
├── README.md
└── assets\
    ├── VerbaNode.ico
    └── VerbaNode.png
```

See:

- `docs/packaging/WINDOWS_APP.md`
- `docs/packaging/INSTALLER.md`
- `packaging/README.md`

for packaging-specific documentation.

---

## Plugins

VerbaNode separates built-in application plugins from external user plugins.

### Built-in plugins

Built-ins live under:

```text
app\plugins\builtin\
```

Current built-in capabilities include conversation control, location, current time, and weather-related tooling.

### External plugins

External plugin examples and templates live under:

```text
plugins\
├── example_echo\
└── _template\
```

A plugin normally contains:

```text
my_plugin\
├── plugin.json
├── plugin.py
└── README.md
```

Use `_template` as the starting point for new plugins.

Plugin documentation:

```text
docs\plugins\
```

includes architecture, manifest, security, manager, and external-plugin guides.

---

## Repository Structure

```text
VerbaNode/
├── app/                  # Core application
│   ├── plugins/          # Internal plugin framework + built-ins
│   ├── services/         # STT, TTS, audio, AI engine, memory, pipeline, etc.
│   └── static/           # Responsive web dashboard
│
├── plugins/              # External plugin template/examples
├── packaging/            # PyInstaller + Inno Setup + branding assets
├── scripts/              # Setup, model, and Windows helper scripts
├── docs/                 # Architecture, features, plugins, packaging docs
├── tests/                # Automated regression tests
│
├── launcher.py           # Source/frozen launcher entry point
├── run.bat               # Single development startup entry point
├── build_windows.bat     # Build Windows application
├── build_installer.bat   # Build Windows installer
│
├── requirements.txt
├── requirements-core.txt
├── requirements-dev.txt
├── README.md
├── CHANGELOG.md
└── RELEASE_NOTES.md
```

Generated build output, databases, caches, models, certificates, diagnostics, and runtime audio should remain outside Git tracking.

---

## Testing

Run the full test suite with:

```powershell
python -m pytest -q
```

The test suite covers areas including:

- audio lifecycle and device selection
- Audio Engine and AI Engine isolation
- STT confidence handling
- bilingual agents
- Whisper hardening and fallback
- TTS caching and interruption
- selective memory
- typed-chat interruption
- plugin architecture and security
- diagnostics
- Windows launcher lifecycle and styling
- Windows packaging
- installer/setup CLI behavior
- repository layout

Before a release, also test the packaged application and installer on Windows outside the source repository.

---

## Documentation

Documentation is grouped by topic:

```text
docs/
├── architecture/
├── features/
├── packaging/
├── plugins/
└── ui-preview/
```

Useful starting points:

- `docs/architecture/PIPELINE_COMPARISON.md`
- `docs/features/BILINGUAL_AGENTS_AND_SCRIPT_TTS.md`
- `docs/features/SELECTIVE_MEMORY.md`
- `docs/plugins/EXTERNAL_PLUGINS.md`
- `docs/plugins/PLUGIN_SECURITY.md`
- `docs/packaging/WINDOWS_APP.md`
- `docs/packaging/INSTALLER.md`

---

## Security and Privacy

VerbaNode is designed primarily for local deployment, but it still exposes a browser-accessible dashboard and can use online services depending on configuration.

Keep these rules in mind:

- never commit `.env`
- never commit generated private certificate keys
- keep dashboard PINs private
- repeated failed PIN logins are throttled, but the dashboard should still only be exposed to trusted networks
- controller WebSockets use short-lived one-time tickets instead of placing the main session token in the WebSocket URL
- only expose the dashboard to trusted networks
- review external plugins before enabling them
- remember that Edge TTS is an online service
- Ollama/local STT/local TTS data remains local unless another configured plugin/service sends data externally

See `SECURITY.md` for project security guidance.

---

## Current Direction

The v0.8.x line was the **architecture-before-feature-expansion** sequence. v0.9.0 is the first feature line built on that foundation, adding local Android discovery/pairing/trusted-device support without adding cloud connectivity.

Current v0.9.0 guarantees/priorities:

- keep the existing web dashboard fully supported as one client of the shared REST/WebSocket backend
- keep `app/main.py` limited to application composition and lifecycle while product domains live in API routers
- preserve explicit REST API v1 and WebSocket Protocol v1 compatibility metadata for future clients
- preserve one active-controller ownership policy while making expiry/ticket cleanup deterministic
- keep action identity/result state persistent in SQLite and reconcile process-local active work after crashes/restarts
- route future physical/service operations through registered capability providers with permission, TTL, timeout, cancellation, and concurrency controls
- keep database upgrades ordered, recoverable, and downgrade-safe
- keep backup/restore bounded, checksum-verified, safety-backed-up, and SQLite-consistent
- keep browser inputs bounded and browser/WebSocket origin behavior explicit
- keep frontend responsibilities modular without a framework rewrite
- run one release verifier locally, in CI, and before Windows packaging to catch version/route/source-tree regressions

**Intentionally excluded from Core v0.9.0:** cloud relay/Internet remote control, multi-controller ownership, and robot-specific physical providers. The native Android application is a separate project that consumes the local discovery/pairing/client contracts in this release.

The next development line can build new client/device functionality on top of this stabilized backend rather than continuing architectural churn inside v0.8.

---

## Contributing

Contributions, testing, bug reports, and plugin improvements are welcome.

Before submitting changes:

```powershell
python -m pytest -q
```

Please keep changes modular, preserve the source-development workflow, and avoid committing generated/runtime data.

See `CONTRIBUTING.md` for additional guidance.

---

## License

See `LICENSE` for licensing terms.

---

<div align="center">

**VerbaNode**

Local voice-assistant infrastructure for interactive systems and robotics.

</div>
