# Changelog

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
