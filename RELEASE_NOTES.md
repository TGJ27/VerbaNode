# VerbaNode v0.7.6 Windows Online Installer

v0.7.6 turns the v0.7.5 frozen Windows application into a normal one-file online installer while preserving the existing source-development workflow.

## Installer

- Installs the frozen application under `C:\Program Files\VerbaNode`.
- Preserves runtime/user state under `%LOCALAPPDATA%\VerbaNode`.
- Preserves Whisper, ModelScope/SenseVoice, and Ollama model caches across upgrades.
- Creates Start Menu shortcuts, optional Desktop shortcut, optional Start-with-Windows shortcut, and a Private-network firewall rule.
- Uses a stable Inno Setup `AppId` so future setup EXEs upgrade the same installation.

## Online component wizard

- English: optionally prepares SenseVoiceSmall.
- Bahasa Indonesia: choose Whisper Base, Whisper Small, or both.
- Edge TTS remains bundled/online and needs no model download.
- Kokoro local TTS can be downloaded optionally.
- Ollama can be detected/installed and the selected local LLM is pulled automatically; default is `qwen3.5:0.8b`.

## Setup safety

- Database is backed up before installer-triggered migration.
- HTTPS certificate is checked/generated before first launch.
- Existing agents, scripts, Information, settings, plugins, certificates, databases, and downloaded models are not intentionally removed by upgrades.
- The normal uninstaller removes app binaries/shortcuts/firewall rule but leaves persistent user data and external model caches intact.

## Branding

- The supplied final VerbaNode icon is used for both `VerbaNode.exe` and `VerbaNode-Setup-0.7.6.exe`.

## Validation

- 145 automated tests pass in source mode.
- Windows/Inno Setup compilation still needs to be run on the target Windows development PC after applying this patch.
