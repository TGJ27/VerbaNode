# Changelog

## 0.4.2

- Added a real Windows/PortAudio hot-plug refresh operation inside the isolated Audio Engine.
- Changed the dashboard Refresh Devices action from passive enumeration to safe audio shutdown, PortAudio reinitialization, fingerprint remapping, and updated device enumeration.
- Added automatic recovery and retry for microphone locking, speaker locking, host PTT, microphone tests, utterance capture, and speaker playback.
- Added an 8–10 second staged retry window for Bluetooth/USB endpoint registration after connection.
- Added a final Audio Engine process restart fallback when a PortAudio refresh cannot reopen the requested endpoints.
- Improved default-device inspection so the active Windows profile sample rate is used even when the default numeric ID is temporarily unavailable.
- Added fallback sample-rate, channel, and latency negotiation for Windows input/output streams.
- Added device refresh count, hot-plug recovery count, and last recovery reason to runtime health.
- Added regression tests for PortAudio reinitialization, default-device profile inspection, and proxy-level hot-plug retries.

## 0.4.1

- Added a hidden no-emoji output policy and backend Unicode sanitization for streamed chat, stored assistant messages, generated roles/greetings, summaries, and TTS input.
- Discarded emoji-only TTS chunks so reaction icons cannot create empty or delayed speech requests.
- Changed Stop Conversation to stop current playback and clear pending sentence/audio queues immediately by default.
- Kept Stop Current TTS effective for both streamed assistant speech and non-streamed scripts/greetings through the isolated Audio Engine.
- Cached the Silero VAD model once per Audio Engine process instead of initializing it for every conversation turn.
- Added Phase 2 regression tests for output sanitization, multilingual text preservation, emoji-free TTS, and default stop behavior.

## 0.4.0

- Moved native host microphone and speaker ownership into one supervised Audio Engine child process.
- Added spawn-safe command/response IPC proxies for device enumeration, persistent locks, host PTT, utterance capture, playback, cancellation, tests, and health.
- Kept VAD, PortAudio callbacks, input frame queues, and speaker buffers inside the child process so per-frame audio does not cross IPC.
- Added an Audio Engine watchdog, automatic process restart, in-flight call failure handling, and restoration of requested device/lock state.
- Added Audio Engine PID, coordinator state, heartbeat age, and restart count to API and dashboard runtime status.
- Added an authenticated dashboard action to stop active audio work and manually restart the Audio Engine.
- Added `VERBANODE_AUDIO_ENGINE_PROCESS=false` compatibility mode for troubleshooting.
- Added process lifecycle, proxy-health, restart, and error-translation tests.
- Preserved the v0.3.3 database, UI, layered prompt architecture, natural tool routing, Edge/Kokoro fallback, and browser-device PTT behavior.

## 0.3.3

- Expanded deterministic core-tool routing to ignore natural greetings, wake words, and polite wrappers such as “hello Ropi” and “please”.
- Added conservative fuzzy matching for minor ASR and typing errors in current time/date requests, including “what day its its?”.
- Applied the same greeting handling to location, weather, and stop-conversation requests.
- Preserved exclusions for unrelated phrases such as time complexity and meeting-time questions.
- Added regression tests proving natural current-time requests bypass the LLM and use the configured `Asia/Jakarta` time tool directly.
- Removed device-brand-specific audio guidance from the dashboard while preserving device selection and persistent stream locking.
- Consolidated repository release documentation into `CHANGELOG.md` plus a single current `RELEASE_NOTES.md`.

## 0.3.2

- Refactored prompt construction into hidden core, voice-output, tool, runtime, knowledge, memory, and agent-character layers.
- Reduced the editable Ropi prompt to identity, domain, personality, and speaking style only.
- Kept deterministic core-tool routing and all operational tool rules outside the agent role.
- Added internal memory and retrieved-knowledge policies that treat injected content as data rather than instructions.
- Updated the agent editor and AI role generator so new character prompts do not contain tools, memory, safety, or runtime instructions.
- Added a one-time migration that replaces the known v0.3.1 operational Ropi prompt while preserving genuinely customized Ropi prompts.
- Added layered-prompt and migration regression tests.

## 0.3.1

- Strengthened the default Ropi role with mandatory live-data and physical-action rules.
- Added deterministic routing for unambiguous time/date, location, weather, and conversation-stop requests.
- Added configurable default timezone support and changed the time tool to use it.
- Restored Ropi's four core tools during the one-time v0.3.1 database migration while preserving extra tools and the user's STT threshold.
- Removed redundant HTTPS heartbeats whenever the WebSocket heartbeat is active.
- Filtered only the harmless Windows Proactor `WinError 10054` disconnect-cleanup callback without hiding other asyncio errors.
- Added regression tests for tool routing, LLM bypass, prompt migration, and Windows reset filtering.

## 0.3.0

- Added authoritative pipeline states and turn, capture, generation, and sentence identifiers.
- Added bounded TTS queues, ASR retry/timeout, direct PCM recognition, and provider health metrics.
- Changed the legacy 88% heuristic STT gate to 70% while preserving deliberate custom thresholds.
- Added Ollama timeouts, tool timeouts, up to three tool rounds, and interrupted tool-history repair.
- Added Edge/Kokoro retry, circuit breaking, and faster first-clause TTS.
- Added resilient audio-device fingerprints and device recovery counters.
- Rebuilt the dashboard with a responsive XiaozhiConsole-inspired desktop and phone layout.
- Preserved the GitHub deployment structure, CI workflow, generated controller PIN, and `data/verbanode.db` migration path.

## 0.2.6

- Added browser-device push-to-talk over HTTPS.
- Added persistent host microphone and speaker handling with selectable devices.
- Added requester-confirmed immediate controller takeover.
- Added expired-session and WebSocket recovery.
- Added script and greeting TTS caching.
- Added streamed sentence-level LLM-to-TTS playback.
- Added STT confidence threshold controls.
- Set Ropi defaults to `qwen3.5:0.8b`, 88% STT threshold, and 224 maximum response tokens.
- Added explicit database setup tooling for repository deployments.
