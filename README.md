# VerbaNode

VerbaNode is a Windows-hosted, CPU-capable voice assistant with a responsive browser dashboard. AI processing and host audio run on the Windows PC. A desktop browser or phone can control the system over the local network, and the browser-device push-to-talk option can use the phone microphone over HTTPS.

## Main features

- Multiple editable agents with independent prompts, Ollama models, TTS voices, information, tools, memory, and chat history.
- Continuous conversation, host push-to-talk, browser-device push-to-talk, typed chat, and Stop Current TTS.
- Silero VAD, SenseVoice/FunASR STT, estimated STT confidence filtering, Ollama, Edge TTS, and local Sherpa-ONNX Kokoro.
- Sentence-buffered LLM-to-TTS streaming while chat remains one assistant message.
- Global script buttons with queue controls and persistent audio caching.
- Cached agent greetings.
- Global information library with per-agent enable/disable selection.
- SQLite storage, backups, restore, and per-agent memory.
- One active controller. A second device enters the PIN, confirms takeover locally, and immediately replaces the previous controller without requiring its approval.
- Selectable host input/output devices and persistent audio streams.

## Requirements

- Windows 10 or Windows 11, 64-bit.
- Miniconda or Anaconda.
- Ollama for Windows.
- 8 GB RAM minimum; CPU-only operation is supported.
- Devices on the same local network for remote dashboard access.

## First-time setup

Open Command Prompt or PowerShell in the project folder.

```bat
setup_windows.bat
```

The setup script creates the `verbanode` Conda environment, installs dependencies, creates `.env`, and generates a random six-digit controller PIN.

Pull the default LLM:

```bat
ollama pull qwen3.5:0.8b
```

Create or migrate the SQLite database:

```bat
setup_database.bat
```

Download speech and TTS models:

```bat
download_funasr.bat
download_kokoro.bat
```

Start VerbaNode with HTTPS:

```bat
run.bat
```

The terminal prints the desktop and local-network URLs. HTTPS is required for phone/browser microphone permission. Use `run_http.bat` only when browser-device microphone capture is not needed.

To allow another device through Windows Firewall, run `allow_firewall.bat` as Administrator.

## Database setup

The repository contains only `data/.gitkeep`; it does not commit a user database.

```bat
setup_database.bat
```

creates `data/verbanode.db`, initializes the schema, and seeds Agent Ropi with:

- model `qwen3.5:0.8b`;
- temperature `0.2`;
- top-p `0.8`;
- maximum response tokens `224`;
- STT confidence threshold `88%`.

To intentionally erase and recreate the database:

```bat
setup_database.bat --reset
```

The script requires typing `RESET` before deletion.

## Audio behavior

Host mode uses the selected Windows microphone and speaker. Conversation mode can keep both selected streams active to avoid Bluetooth endpoint churn. Browser-device PTT records in the browser, uploads WAV/PCM to the Windows host, then uses the same STT → agent → TTS pipeline. Assistant audio still plays through the host speaker.

## Project structure

```text
app/                 FastAPI application, services, database, and web UI
scripts/             Model, certificate, audio-test, and database utilities
tests/               Automated regression tests
data/.gitkeep         Empty runtime data directory placeholder
models/kokoro/        Kokoro model location and instructions
setup_windows.bat     Conda environment and dependency setup
setup_database.bat    Create, migrate, or reset SQLite data
run.bat               HTTPS launcher
run_http.bat          Optional HTTP launcher
download_funasr.bat   SenseVoice model downloader
download_kokoro.bat   Kokoro model downloader
```

## Configuration

`setup_windows.bat` copies `.env.example` to `.env`. Important values:

| Variable | Purpose |
| --- | --- |
| `VERBANODE_PIN` | Controller PIN |
| `VERBANODE_PORT` | Dashboard/API port |
| `VERBANODE_DB_PATH` | SQLite database path |
| `VERBANODE_OLLAMA_URL` | Ollama API URL |
| `VERBANODE_DEFAULT_MODEL` | New-agent default model |
| `VERBANODE_DEFAULT_LOCATION` | Weather/location default |
| `VERBANODE_FUNASR_MODEL` | STT model identifier |
| `VERBANODE_KOKORO_DIR` | Local Kokoro model folder |
| `VERBANODE_TTS_CACHE_PATH` | Persistent script/greeting cache |

Do not commit `.env`, databases, models, certificates, backups, or TTS cache files.

## Testing

```bat
conda run -n verbanode python -m pytest -q
```

Hardware-dependent microphone, Bluetooth, browser permission, and speaker behavior must also be tested on the target Windows PC.

## Reference architecture

The project was architecturally informed by the MIT-licensed `xiaozhi-esp32-server` project. VerbaNode uses a Windows-hosted topology rather than its remote ESP32 audio-device topology. See `THIRD_PARTY_NOTICES.md` and `docs/PIPELINE_COMPARISON.md`.
