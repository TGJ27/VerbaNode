# Phase 2 implementation: isolated Audio Engine

VerbaNode v0.4.2 keeps native host microphone and speaker ownership out of the FastAPI/LLM process and into one supervised child process.

## Process topology

```text
VerbaNode Core process
├── FastAPI and responsive dashboard
├── conversation orchestration
├── SenseVoice/FunASR
├── Ollama, tools, prompts, and memory
├── Edge/Kokoro synthesis
└── Audio Engine supervisor and IPC proxies
        │
        ▼
Audio Engine child process
├── persistent microphone stream
├── VAD and utterance buffering
├── persistent speaker stream
├── playback cancellation
├── device recovery
└── microphone/speaker state coordinator
```

The microphone and speaker are not independent processes. One process owns both endpoints so Windows device selection, half-duplex behavior, cancellation, and recovery remain coordinated.

## IPC boundary

The PortAudio callbacks and frame queues stay inside the child process. VerbaNode does not send each 20–32 ms frame through multiprocessing queues.

The core process sends commands such as:

- lock or release a selected device;
- start, stop, or cancel host PTT;
- capture one utterance until silence;
- play or cancel one generated audio file;
- query device and engine health.

Only complete utterance arrays, small command responses, health data, and audio-file paths cross the process boundary.

## Supervision and recovery

`AudioEngineSupervisor` provides:

- spawn-safe Windows process creation;
- startup readiness checks;
- a periodic heartbeat watchdog;
- forced termination when the process stops responding;
- automatic process restart;
- restoration of the selected input/output devices and requested lock state;
- PortAudio termination/reinitialization when Windows devices are connected after startup;
- staged hot-plug retries, saved-fingerprint remapping, and an Audio Engine-only restart fallback;
- failure of in-flight calls instead of leaving core threads blocked forever;
- restart count, PID, heartbeat age, and coordinator state in the dashboard status.
- an authenticated manual restart action in Settings for recovery testing.

If a native PortAudio operation crashes or deadlocks the child process, the web UI, database, conversation history, LLM, tools, and memory stay online.

## Compatibility mode

Set the following only for troubleshooting or regression comparison:

```env
VERBANODE_AUDIO_ENGINE_PROCESS=false
```

This restores the v0.3.3 in-process audio implementation without changing the database.

## Scope boundary

Phase 2 isolates host PortAudio. Browser-device microphone recordings still arrive through HTTPS and are passed directly to STT, because they do not own a Windows audio endpoint.

Physical microphone, Bluetooth, WASAPI/MME, driver-disconnect, and long-duration recovery behavior must be tested on the target Windows computer before publishing v0.4.2 as a stable release.

## Windows hot-plug path (v0.4.2)

When a microphone or speaker open fails after a USB/Bluetooth connection change, the proxy does not immediately return a 503. It performs this recovery sequence:

```text
Initial endpoint open fails
→ stop active capture and playback
→ close persistent input/output streams
→ Pa_Terminate / Pa_Initialize inside Audio Engine
→ staged Windows endpoint registration wait
→ enumerate until the saved fingerprint/selected ID appears
→ remap changed PortAudio IDs
→ negotiate native and fallback stream formats
→ restore requested speaker then microphone locks
→ persist remapped IDs
```

If the endpoint still cannot be reopened, only the Audio Engine child process is restarted once and the refresh/remap sequence is repeated. The FastAPI process and all non-audio state remain online.

The dashboard **Refresh Devices** button invokes this same real refresh path. The normal `GET /api/audio/devices` endpoint remains a passive status query and does not disturb active streams.
