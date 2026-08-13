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

> **Project status:** active development. v0.8.1 is the architecture-hardening release: the remaining runtime-heavy API domains are split out of the FastAPI entry point, controller takeover behavior is reduced to one deterministic valid-PIN policy, REST requests gain correlation IDs and structured error envelopes, duplicate action execution is tightened, and the dashboard begins splitting into independent JavaScript modules. Pairing/LAN discovery and the mobile application remain intentionally deferred.

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

- **Information / knowledge entries**
  - Reusable information can be enabled globally or assigned to selected agents

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

The v0.8.x line is focused on **architecture before feature expansion**. v0.8.1 continues the v0.8.0 foundation and keeps one client-neutral API surface that the existing website and a future mobile application can both use.

Current v0.8.1 priorities:

- keep the existing web dashboard fully supported
- keep `app/main.py` limited to application composition and lifecycle while product domains live in API routers
- keep capability action identity/result state persistent in SQLite instead of relying on process memory
- keep duplicate/replayed capability requests single-execution across concurrent callers and restarts
- version the WebSocket wire format so future clients do not depend on dashboard-specific behavior
- make database restore bounded, validated, safety-backed-up, and atomic
- keep schema upgrades ordered through numbered migrations

**Intentionally deferred:** mobile application implementation, mDNS/Bonjour discovery, QR pairing, trusted-device credentials, cloud relay, and remote access. Those should be designed together with the mobile client rather than guessed into the backend early.

After the v0.8 architecture line stabilizes, VerbaNode can build the robot capability layer on top of the persistent action contract and capability gateway.

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
