# VerbaNode v0.7.5 Windows Application Preview

v0.7.5 is the first Windows desktop packaging preview built on the v0.7.4 stable assistant foundation. It does not change the STT/LLM/TTS/plugin behavior; it adds a production-style Windows launcher and frozen runtime layout.

## Native launcher

When packaged as `VerbaNode.exe`, the application opens a small native Windows window that:

- starts VerbaNode using HTTPS;
- shows VerbaNode Core, Audio Engine, AI Engine, and Ollama status;
- discovers usable IPv4 network interfaces;
- lists `https://127.0.0.1:8002` and LAN dashboard addresses;
- provides Open and Copy actions for every address;
- can open the dashboard automatically once the backend is healthy;
- can restart the backend services without closing the launcher.

## Upgrade-safe data layout

Source development remains repository-local. Frozen/installed builds instead store mutable data under `%LOCALAPPDATA%\VerbaNode`, including the database, configuration, certificates, plugins, diagnostics, runtime audio, backups, logs, and VerbaNode-managed models. Whisper and ModelScope continue using their normal per-user caches. Replacing the application binaries therefore does not overwrite agents, scripts, settings, plugins, or downloaded model caches.

## HTTPS

Development still uses `run.bat` -> `run_https.bat`. The packaged application performs the equivalent HTTPS certificate preparation internally and can generate the local certificate without relying on a Conda OpenSSL installation.

## Build

On Windows, activate the normal VerbaNode environment and run:

```bat
build_windows.bat
```

The preview uses PyInstaller `onedir` and produces `dist\VerbaNode\VerbaNode.exe`. PyInstaller builds are platform-specific, so the Windows executable must be built on Windows.

## Validation

The source package passes 125 automated tests plus Python and JavaScript syntax checks. The actual frozen executable still needs first-run validation on the target Windows PC before this packaging layer is promoted beyond preview.
