# VerbaNode v0.7.4 Stable

VerbaNode v0.7.4 is the stable release of the v0.7 bilingual assistant line. It consolidates the English/Indonesian voice pipeline, plugin hardening, selective conversation context, Edge voice management, per-script TTS, diagnostics, and the reliability fixes developed through v0.7.0-v0.7.3.

## Stable bilingual agents

- English agents use SenseVoiceSmall through FunASR.
- Indonesian agents can select Whisper Base or Whisper Small through FunASR with decoding fixed to Indonesian.
- Only one agent language profile is active at a time.
- The last active agent is persisted and restored after VerbaNode restarts.
- Ships with default Ropi and Ropi Indonesia profiles.
- Indonesian deterministic time, date, weather, location, and stop requests are handled without unnecessary LLM calls.
- Common Indonesian STT variations are normalized for deterministic routing.

## ASR model management and diagnostics

- Shows the agent-selected ASR model and the model actually loaded by the AI Engine.
- Shows model load time, last transcription latency, completed jobs, fallback status, and last ASR error.
- Detects downloaded Whisper Base and Small checkpoints across supported Windows/OpenAI Whisper cache locations.
- Includes a non-destructive active-language profile test.
- Includes a real WAV benchmark for Whisper Base versus Whisper Small with load time, transcription latency, RTF, confidence, and transcript output.
- Indonesian Whisper Small can fall back to Whisper Base if model loading or inference fails; the English SenseVoice path remains unchanged.

## TTS and scripts

- Edge voice catalogue with locale filtering, refresh, offline fallback list, and preview.
- Indonesian agents are normalized to Indonesian Edge voices.
- English agents retain Edge/Kokoro provider choices.
- Scripts now store their own language, TTS mode, Edge voice, Kokoro voice, speaking rate, and volume.
- Indonesian scripts are validated as Edge-only and cannot silently use an incompatible Kokoro voice.

## Conversation reliability

- Full conversation history remains stored, but prior messages and summaries are injected only for explicit recall or clear context-dependent follow-ups.
- Selected short-term context is bounded instead of replaying the entire conversation to Ollama.
- Empty Ollama HTTP 200 responses retry with reduced context and never create a silent blank assistant turn.
- Typed chat can interrupt active streamed TTS without leaving the generation lock stuck.
- Active-agent selection remains persistent across restarts.

## Plugin architecture

- Built-in capabilities are separated behind the Plugin Registry and Plugin Manager.
- Trusted local external plugins can be discovered from the top-level `plugins/` directory.
- Plugin manifests, paths, permissions, versions, IDs, and LLM tool schemas are validated before registration.
- Plugin execution uses timeouts, bounded concurrency, active-call cancellation, failure thresholds, unhealthy-plugin isolation, and safe reload/recovery controls.
- Plugin health and metrics are exposed in the Plugins page and Diagnostics.

## Dashboard and usability

- Responsive desktop/mobile dashboard.
- File Explorer-style Cards, List, and Details views for Information and Plugins.
- Small, Medium, and Large interface text-size preferences.
- Improved card spacing, outlines, status badges, and readability.
- Rejected low-confidence STT can be shown as muted diagnostics or hidden completely.

## Windows reliability

- Isolated Audio Engine and AI Engine with heartbeat monitoring and supervised recovery.
- Persistent microphone/speaker ownership and Windows audio hot-plug recovery.
- Windows `tzdata` support for IANA timezones.
- Whisper Base/Small cache detection recognizes the standard Windows OpenAI Whisper cache.

## Validation

- 121 automated tests pass.
- Python compilation passes.
- Frontend JavaScript syntax validation passes.
- No user `.env`, databases, certificates, model checkpoints, diagnostics, runtime audio, or TTS cache are included in the release archive.

## Upgrade

Keep your existing local data:

```text
.git
.env
data/
models/
certs/
```

Replace the application files with v0.7.4, then run:

```powershell
setup_windows.bat
setup_database.bat
run.bat
```

Hard-refresh the dashboard with `Ctrl+Shift+R` after the first start.

Whisper checkpoints already present under the OpenAI Whisper cache do not need to be downloaded again.

## Known limitations

- External plugins are trusted local Python code; VerbaNode validates packages but does not provide a true Python security sandbox.
- Whisper Base/Small CPU latency varies significantly by processor; use the built-in benchmark on the target deployment PC.
- Edge TTS requires network access.
- Interface text-size and Explorer-view preferences are stored per browser.
