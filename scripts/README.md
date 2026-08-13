# VerbaNode utility scripts

Developer/runtime helpers are grouped by purpose so the repository root only contains the primary run/build entry points.

## Setup

- `scripts/setup/setup_windows.bat` — create/reuse the `verbanode` Conda environment and install dependencies.
- `scripts/setup/setup_database.bat` — create/migrate the development SQLite database; add `--reset` for an explicit destructive reset.

## Models

- `scripts/models/download_funasr.bat` — pre-download SenseVoiceSmall.
- `scripts/models/download_whisper.bat [base|small|both]` — pre-download Indonesian Whisper checkpoints.
- `scripts/models/download_kokoro.bat` — download the local Kokoro TTS model.

Python helpers live beside the corresponding BAT wrappers.

## Windows

- `scripts/windows/allow_firewall.bat` — add the private-network development firewall rule (run as Administrator).
- `scripts/windows/test_audio.bat` — run the host audio diagnostic.
- `scripts/windows/generate_local_cert.py` — standalone HTTPS certificate helper; source startup normally lets `launcher.py` manage certificates automatically.

Primary entry points intentionally remain in the repository root: `run.bat`, `build_windows.bat`, and `build_installer.bat`. `run.bat` is the only source-development launcher.
