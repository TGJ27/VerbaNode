# VerbaNode Online Windows Installer

`VerbaNode-Setup-<version>.exe` wraps the already-frozen VerbaNode application and prepares optional AI components online.

The installer version is derived from `app/version.py` by `build_installer.bat`; do not maintain a second release version manually in the build script.

## Developer build order

1. Run `python -m pytest -q`.
2. Run `build_windows.bat`.
3. Fully exit VerbaNode.
4. Run `build_installer.bat`.

Output:

`dist-installer\VerbaNode-Setup-<version>.exe`

## Build isolation

`build_windows.bat` uses the `verbanode-build` Conda environment by default. This keeps PyInstaller and packaging dependency changes out of the normal `verbanode` development environment. Override it only when necessary with `VERBANODE_CONDA_ENV`.

Validated build-only dependency versions are pinned in `packaging\requirements-packaging.txt`.

## Installer choices

- English: prepares SenseVoiceSmall if selected and missing.
- Bahasa Indonesia: choose Whisper Base, Whisper Small, or both; existing checkpoints are reused.
- Edge TTS: already included in the application runtime.
- Kokoro: optional local model download, skipped when already present.
- Ollama: optional detection/install plus model pull; an existing Ollama installation/model is reused.

The installer uses VerbaNode's own frozen setup commands for database migration, HTTPS initialization, model cache handling, and Ollama model pulls. This keeps installer logic aligned with the application.

## Upgrade preservation

Application binaries are replaced under `C:\Program Files\VerbaNode`.

Persistent content is intentionally outside the install directory and is not deleted on upgrades:

- `%LOCALAPPDATA%\VerbaNode` — database, agents, scripts, Information, settings, external plugins, certificates, diagnostics, backups, logs, and VerbaNode-managed models.
- `%USERPROFILE%\.cache\whisper` — Whisper checkpoints.
- `%USERPROFILE%\.cache\modelscope` — SenseVoice/ModelScope cache.
- `%USERPROFILE%\.ollama` — Ollama model storage.

The database is backed up before each installer-triggered migration. Numbered database migrations are tracked through the `schema_version` setting beginning with v0.7.7.

## Uninstall behavior

The normal uninstaller removes VerbaNode application binaries, shortcuts, and its firewall rule. It does not intentionally delete persistent VerbaNode user data or external model caches.

## Branding

`packaging\assets\VerbaNode.ico` is used by the application, Setup executable, shortcuts, and Windows uninstall entry.
