# Phase 3 implementation: isolated AI Engine

VerbaNode v0.5.0 separates native local model inference from both the FastAPI core and the Phase 2 Audio Engine.

```text
VerbaNode Core
├── FastAPI and dashboard
├── conversation orchestration
├── prompts, tools, memory, and SQLite
├── Ollama HTTP client
├── Edge TTS provider
├── Audio Engine supervisor
└── AI Engine supervisor
    └── VerbaNodeAIEngine process
        ├── SenseVoice/FunASR model
        ├── Kokoro/Sherpa-ONNX model
        ├── ASR queue and inference lock
        ├── Kokoro queue and inference lock
        └── health, preload, reload, and watchdog responses
```

## IPC boundary

The Audio Engine keeps frame-level capture, VAD, and playback. After an utterance is complete, the core sends one immutable NumPy PCM snapshot to the AI Engine. The AI Engine returns text, confidence metadata, and latency. Kokoro writes a temporary WAV file in the shared runtime folder and returns only its path.

## Lifecycle

The AI process reports ready immediately, then preloads SenseVoice in a background thread. Kokoro is preloaded only when its model files exist. A watchdog checks the process without blocking active inference because inference jobs run in worker threads while ping/status commands remain responsive.

A timed-out ASR or Kokoro request restarts only the AI Engine. FastAPI, the dashboard, database, Audio Engine, tools, memory, Edge TTS, and Ollama remain available.

## Queue limits

- ASR: two in-flight jobs, one active inference.
- Kokoro: four in-flight jobs, one active inference.

The limits are configurable through `.env`. Existing turn and speech generation IDs still reject stale results after cancellation.

## Compatibility mode

Set `VERBANODE_AI_ENGINE_PROCESS=false` to use the earlier in-process SenseVoice and Kokoro providers for troubleshooting.

## Manual validation

Test model preload, first-turn latency, Edge-to-Kokoro fallback, model reload, AI process restart, conversation continuity after restart, and a 30–60 minute CPU/RAM soak test before a stable release.

## v0.5.1 dashboard addendum

The Phase 3 runtime architecture is unchanged. Settings is now category-based, and rejected STT visibility is a persisted presentation preference. Confidence filtering remains a backend pipeline decision; the new visibility toggle affects only whether rejected transcript diagnostics are rendered in chat.
