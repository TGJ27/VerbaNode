# Phase 3 diagnostics and soak monitoring

VerbaNode v0.5.2 adds observability around the existing three runtime boundaries without adding another process.

```text
Core process
├── Diagnostics Manager
│   ├── redacted in-memory logs
│   ├── system/process resource sampling
│   ├── self-test coordinator
│   ├── recent-turn latency history
│   ├── soak-test sampler
│   └── safe ZIP report export
├── Audio Engine supervisor
└── AI Engine supervisor
```

## Privacy boundary

Diagnostics exports include health, dependency versions, counters, process metrics, recent redacted logs, recent latency records, and soak summaries. They do not include the `.env` file, controller PIN, SQLite database, conversation content, certificates, TTS cache, recordings, or model binaries. WebSocket session tokens are redacted before entering the log ring.

## Self-test

The dashboard self-test is non-destructive. It checks database access, writable runtime directories, engine responsiveness and heartbeat freshness, available Windows input/output endpoints, Ollama connectivity, and pipeline state. Existing microphone and speaker test buttons remain in Host Audio because those tests intentionally capture or play audio.

## Soak test

The soak monitor samples during normal operation. It does not generate synthetic conversations. It records system CPU/RAM, Core/Audio/AI process RSS and threads, engine heartbeat age, inference queue use, engine restart deltas, and pipeline error deltas. Completed soak reports are written under the ignored `diagnostics/` runtime directory.
