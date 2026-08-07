# VerbaNode v0.7.0 Beta — English and Indonesian Agents

This release adds first-class Bahasa Indonesia support while preserving the existing low-latency English pipeline.

## Bilingual agent profiles

- Adds an explicit **English / Bahasa Indonesia** language setting to every agent.
- English agents use `iic/SenseVoiceSmall` through FunASR.
- Indonesian agents use multilingual `Whisper-base` through FunASR with decoding forced to Indonesian.
- Only one language/ASR profile is active at a time, based on the active agent.
- Adds a default **Ropi Indonesia** agent with Indonesian identity instructions, greeting, Whisper Base STT, Edge-only TTS, and `id-ID-GadisNeural`.
- Existing English Ropi configurations remain available.

## Indonesian output

- Adds a hidden language policy so the active agent responds consistently in its configured language.
- Localizes deterministic time, date, location, weather, and stop-conversation responses.
- Filters the Edge voice catalogue to the active agent language.

## Per-script TTS

- Scripts no longer depend on the active agent voice.
- Every Script now stores its own language, TTS mode, Edge voice, Kokoro voice, rate, and volume.
- Adds a Script voice preview that uses the selected provider configuration.
- Existing scripts migrate to English Edge TTS with Aria by default.

## Setup and compatibility

- Adds the `openai-whisper` dependency.
- Adds `download_whisper.bat` and `scripts/download_whisper.py`.
- Existing SQLite databases migrate automatically and receive Ropi Indonesia once.
- The isolated AI Engine switches ASR models when the active agent language changes.
- Includes 107 passing automated tests.

## Upgrade

Keep `.git`, `.env`, `data/`, `models/`, and `certs/`. Replace the updated files, then run:

```bat
setup_windows.bat
setup_database.bat
download_whisper.bat
run.bat
```

The first Indonesian transcription can be slower while Whisper Base loads.
