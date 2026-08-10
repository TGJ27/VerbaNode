# VerbaNode v0.7.6 Online Windows Installer

`VerbaNode-Setup-0.7.6.exe` wraps the already-frozen VerbaNode application and prepares optional AI components online.

## Developer build order

1. Apply the v0.7.6 installer patch.
2. Run `python -m pytest -q`.
3. Run `build_windows.bat` once. This rebuild is required because v0.7.6 adds setup CLI commands and the final application icon.
4. Fully exit VerbaNode.
5. Run `build_installer.bat`.

Output:

`dist-installer\VerbaNode-Setup-0.7.6.exe`

## Installer choices

- English: prepares SenseVoiceSmall if selected.
- Bahasa Indonesia: choose Whisper Base, Whisper Small, or both.
- Edge TTS: already included in the application runtime.
- Kokoro: optional local model download.
- Ollama: optional detection/install plus model pull. The default model is `qwen3.5:0.8b`.

The installer uses VerbaNode's own frozen setup commands for database migration, HTTPS initialization, model cache handling, and Ollama model pulls. This keeps installer logic aligned with the application.

## Upgrade preservation

Application binaries are replaced under `C:\Program Files\VerbaNode`.

Persistent content is intentionally outside the install directory and is not deleted on upgrades:

- `%LOCALAPPDATA%\VerbaNode` — database, agents, scripts, Information, settings, external plugins, certificates, diagnostics, backups, and VerbaNode-managed models.
- `%USERPROFILE%\.cache\whisper` — Whisper checkpoints.
- `%USERPROFILE%\.cache\modelscope` — SenseVoice/ModelScope cache.
- `%USERPROFILE%\.ollama` — Ollama model storage.

The database is backed up before each installer-triggered migration.

## Uninstall behavior

The normal uninstaller removes VerbaNode application binaries, shortcuts, and its firewall rule. It does not intentionally delete persistent VerbaNode user data or external model caches.

## Final icon

`packaging\assets\VerbaNode.ico` is generated from the approved VerbaNode icon and is used by both `VerbaNode.exe` and the Setup executable.
