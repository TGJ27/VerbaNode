# Phase 1 implementation

VerbaNode v0.3.0 hardens the existing single-process application before audio is moved into a supervised child process in Phase 2.

## Pipeline state and identity

`app/services/pipeline.py` provides one authoritative pipeline state and shared identifiers:

- `turn_id` for one user/assistant exchange;
- `capture_id` for one microphone recording;
- `generation_id` for one LLM/TTS generation;
- sentence indexes for ordered TTS generation and playback.

The dashboard receives pipeline-state events and exposes the latest stage, latency measurements, errors, and counters.

## STT and ASR

- SenseVoice receives an immutable PCM copy.
- Direct PCM recognition is attempted first; temporary WAV input remains as a compatibility fallback.
- Transcription has a finite timeout and one transient retry.
- The old 88% heuristic hard gate is migrated to 70%. Provider confidence is still preferred when available.
- Saved custom thresholds are not overwritten.

## LLM and tools

- Ollama uses finite connection and read timeouts.
- Tool calls have an execution timeout.
- Up to three tool rounds are supported.
- Interrupted tool-call history is repaired before the next request.
- The wrapper no longer overrides an agent prompt by forcing English output.

## TTS

- The first natural clause may be synthesized before the first full sentence completes.
- Text-generation and generated-audio queues are bounded.
- Edge and Kokoro each receive one retry.
- Failed providers enter a temporary circuit-open state so fallback is immediate instead of repeatedly waiting on a known failure.
- Edge/Kokoro remain independent fallback providers.

## Audio handling

The persistent microphone and speaker streams remain coordinated inside the main process for Phase 1. This avoids changing native audio ownership and pipeline behavior at the same time.

Device selections now include a fingerprint containing device name, host API, direction, and channel capability. If Windows or PortAudio changes numeric IDs, VerbaNode resolves the saved fingerprint to the new ID. A temporary enumeration failure preserves the last saved ID.

Health data includes input drops, input reopen count, output reopen count, playback recovery count, queue depth, and lock state.

## UI

The console uses a XiaozhiConsole-inspired light visual system while keeping the existing VerbaNode workflow.

- Desktop conversation view fits within one viewport and uses internal scrolling.
- Main pages use centered pill navigation and compact cards.
- Phone layout provides a drawer, bottom navigation, and fixed voice controls for conversation mode, host PTT, and dashboard-device PTT.
- Settings exposes pipeline, provider, latency, and audio health.

## Phase 2 boundary

Phase 2 should move the existing microphone worker, speaker worker, VAD, device recovery, and audio state coordinator into one supervised Audio Engine process. Microphone and speaker should remain coordinated by that one process rather than becoming independent processes.

## v0.3.2 layered prompt architecture

The editable agent configuration now owns only identity and character. `app/services/prompts.py` composes the hidden operating prompt from distinct layers:

```text
Core operating policy
Voice-output policy
Enabled-tool policy
Runtime context
Agent identity and character
Retrieved knowledge context
Remembered context
```

Deterministic routing remains outside the model for unambiguous core requests. The prompt composer includes only schemas for tools enabled on the active agent. Knowledge and memory are explicitly delimited as data rather than instruction sources. The database keeps the `system_prompt` column for backward compatibility, but the UI presents it as **Character instructions**.
## v0.3.3 natural core-tool routing

The deterministic built-in router now normalizes greetings, wake words, and politeness wrappers before matching. It also uses a restricted token whitelist to tolerate small ASR/typing errors for current time/date requests without hijacking unrelated phrases such as time complexity or scheduled event times. Clear current time/date, location, weather, and stop requests continue to execute before the LLM.

