# VerbaNode Windows Application and Online Installer (v0.7.6)

This release adds the packaging layer used to build `VerbaNode.exe` without
removing or replacing the source development workflow.

## Development remains unchanged

Use `run.bat` / `run_https.bat` exactly as before. In source mode VerbaNode
keeps repository-local `data/`, `certs/`, `plugins/`, `models/`, diagnostics,
and `.env` paths.

## Frozen application behavior

`dist/VerbaNode/VerbaNode.exe` opens a small Windows launcher. The launcher:

- creates/updates the HTTPS certificate;
- starts the VerbaNode HTTPS backend as a supervised child process;
- waits for Core, Audio Engine, and AI Engine health;
- checks Ollama connectivity;
- discovers usable IPv4 interfaces;
- shows an Open and Copy action for each dashboard URL;
- optionally opens the local dashboard automatically;
- provides Restart Services and Exit controls.

The Windows application writes mutable state to `%LOCALAPPDATA%\VerbaNode`:

- `data/` database and TTS cache
- `config/.env` and launcher preferences
- `certs/`
- `plugins/`
- `models/` (for VerbaNode-managed local models)
- `diagnostics/`
- `runtime_audio/`
- `backups/`
- `logs/`

Whisper stays in `%USERPROFILE%\.cache\whisper` and ModelScope/SenseVoice keeps
using its normal user cache. Installing a newer VerbaNode build therefore does
not overwrite agents, scripts, settings, external plugins, certificates, or
model caches.

## Build on Windows

Activate the normal VerbaNode environment, then run:

```bat
build_windows.bat
```

PyInstaller is platform-specific; build the Windows executable on Windows.
The output is an onedir application at `dist\VerbaNode\`.

## Why onedir

VerbaNode uses multiprocessing, PyTorch/FunASR, native audio libraries, and
large provider stacks. A one-folder bundle has faster startup, clearer DLL
loading, and simpler diagnostics than extracting a giant one-file executable
on every launch.

## Launcher visual theme

The frozen Windows launcher uses CustomTkinter and mirrors the web dashboard's
light blue/white card design, indigo controls, rounded components, and status
pills. CustomTkinter is a build-only launcher dependency; source development
continues to use `run.bat` / `run_https.bat` without requiring the native
launcher UI.


## v0.7.6 online installer

After `build_windows.bat`, run `build_installer.bat` to create `dist-installer\VerbaNode-Setup-0.7.6.exe`. The wizard can prepare SenseVoiceSmall, Whisper Base/Small, Kokoro, Ollama, and an Ollama model. The setup uses VerbaNode's frozen `--setup-*` commands and keeps mutable data/model caches outside Program Files.
