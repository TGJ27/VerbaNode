# VerbaNode v0.7.2 Beta — Bilingual ASR Hardening

This release stabilizes the English and Bahasa Indonesia pipeline introduced in v0.7.0 and refined in v0.7.1.

## Indonesian ASR reliability

- Indonesian agents can use **Whisper Base** or **Whisper Small** through FunASR.
- Whisper Small remains the accuracy-first option. If it fails or times out during a real transcription, VerbaNode retries once with Whisper Base instead of losing the turn.
- English agents remain pinned to SenseVoiceSmall and never silently change ASR models.
- The active-agent ASR choice continues to persist across restarts.

## Indonesian deterministic routing

Expanded direct routing for natural Indonesian requests including:

- `hari apa sekarang?`
- `tanggal berapa sekarang?`
- `jam sekarang berapa?`
- `cuaca di Bandung hari ini`
- `bagaimana cuaca di Jakarta sekarang?`
- `kita dimana?`
- `berhenti bicara`
- `diam dulu`

These requests bypass the LLM when the corresponding capability is enabled.

## ASR model status

Settings → AI Models now shows:

- model selected by the active agent
- model actually loaded in the AI Engine
- model load latency
- latest transcription latency
- completed ASR jobs
- fallback state
- latest ASR error

## Base vs Small benchmark

A new Indonesian benchmark accepts a real PCM WAV recording and runs the same sample through both Whisper Base and Whisper Small on the target machine. It reports:

- model load time
- transcription time
- real-time factor (RTF)
- estimated/provider confidence
- transcript result

After the benchmark, VerbaNode restores the active agent's configured ASR model automatically. The first benchmark can take substantially longer if Whisper weights still need to be downloaded.

## Compatibility

- No database migration is required beyond the existing v0.7.x migrations.
- Existing English and Indonesian agents remain compatible.
- Existing per-script TTS configuration remains unchanged.
- 115 automated tests pass.

## Upgrade

Keep `.git`, `.env`, `data/`, `models/`, and `certs/`, then replace the updated files and run:

```bat
setup_database.bat
run.bat
```

Use `download_whisper.bat base`, `download_whisper.bat small`, or `download_whisper.bat both` if the desired models are not already cached.
