# Changelog

## v0.7.4 - Stable bilingual assistant foundation

- Promoted the v0.7 bilingual assistant line to stable after final regression validation.
- Consolidated English SenseVoiceSmall and Indonesian Whisper Base/Small agent profiles with persistent active-agent selection.
- Includes selective short-term context, empty-Ollama-response recovery, per-script TTS, Edge voice management, Indonesian deterministic routing, ASR status/benchmark tooling, and plugin hardening.
- Fixed Windows Whisper Base/Small cache detection so existing OpenAI Whisper checkpoints are reported correctly.
- Updated stable release documentation and version metadata.
- 121 automated tests pass.

## v0.7.3 - Bilingual stabilization and UX cleanup

- Added Whisper Base/Small cache visibility so the dashboard shows whether Indonesian ASR models are already downloaded before switching.
- Added a one-click active language profile test that warms the selected ASR model and plays a matching Edge TTS sample without writing to chat history.
- Disabled ASR reload/benchmark controls while model operations are already loading or reloading.
- Improved English/Indonesian agent voice normalization and script language/TTS compatibility checks.
- Added clearer Indonesian script guidance and disabled incompatible Kokoro controls for Indonesian scripts.
- Added regression tests for model-cache detection, language profile validation, and the bilingual UI controls.

## 0.7.2

- Hardened the bilingual ASR path with automatic Indonesian Whisper Small to Whisper Base fallback when the accuracy-first model fails or times out.
- Expanded deterministic Indonesian time, date, weather, location, and stop-conversation routing for more natural phrases and common STT variations.
- Added an ASR status card showing the active agent model, actually loaded model, load latency, last transcription latency, completed jobs, fallback state, and last error.
- Added a real-audio Indonesian ASR benchmark that compares Whisper Base and Whisper Small on the target machine and reports load time, transcription latency, RTF, confidence, and transcript before restoring the active model.
- Preserved active-agent ASR selection after benchmarking and exposed active-agent data in the runtime status API.
- Added bilingual hardening regression tests; 115 automated tests pass.

## 0.7.1

- Persisted the active agent across VerbaNode restarts instead of resetting to the default English agent.
- Improved Indonesian location routing and common Whisper transcription variants.
- Added Whisper Small as an optional higher-accuracy Indonesian ASR model alongside Whisper Base.
- Improved Whisper model preparation for Base, Small, or both models.
- Normalized accidental Markdown emphasis before chat display and TTS playback.
- 112 automated tests pass.

## 0.7.0

- Added per-agent English and Bahasa Indonesia language profiles.
- Kept SenseVoiceSmall as the English low-latency ASR model.
- Added Whisper Base through FunASR for Indonesian-only decoding.
- Added a default Ropi Indonesia agent with Indonesian character instructions, greeting, Edge TTS, and Gadis voice.
- Added hidden active-language prompt enforcement and localized deterministic tool responses.
- Added per-script language, provider, Edge voice, Kokoro voice, speech rate, volume, and provider-aware preview.
- Added automatic SQLite migrations for agent language and Script TTS fields.
- Added `openai-whisper`, `download_whisper.bat`, setup documentation, and regression tests.
- 107 automated tests pass.

## 0.6.7

- Fixed a typed-chat interruption deadlock that could occur when a new text message was submitted while streamed TTS was still playing.
- Streaming TTS cancellation now always restores terminal queue markers after draining pending work, so generator and player workers cannot remain blocked indefinitely.
- Added bounded cancellation cleanup that force-cancels unresponsive TTS workers after 2.5 seconds while preserving idempotent stop events.
- Added regression tests for the exact removed-sentinel race and repeated cancellation; 100 automated tests pass.

## 0.6.6

- Changed conversation memory to selective short-term context: complete history remains stored, but prior messages and summaries are only injected for explicit recall requests and clear follow-up references.
- Added bounded memory selection with at most eight recent messages plus a compact summary under a conservative context budget.
- Added reduced-context Ollama recovery: an empty HTTP 200 response retries once without memory, knowledge, or tool schemas, then returns a controlled visible fallback instead of saving a blank assistant message.
- Expanded deterministic location matching for natural phrases such as `Where are we currently at?` and `Where are we right now?`.
- Added a real Edge voice dropdown, locale filter, online voice-catalogue refresh, bundled offline fallback voices, and voice preview playback.
- Updated the Agent Memory panel to explain selective context behavior.
- Added selective-memory, empty-response recovery, location-routing, Edge voice, and frontend regression tests; 98 automated tests pass.

## 0.6.3

- Added strict external plugin package validation for manifest size, entry size, semantic versions, supported permission labels, safe folder names, symbolic links, and reserved IDs.
- Added recursive LLM tool-schema validation before registration.
- Added bounded plugin execution with per-call timeout, active execution tracking, and cancellation when a conversation stops.
- Added consecutive-failure tracking and automatic `unhealthy` isolation after a configurable threshold.
- Added recovery controls for unhealthy built-in plugins and repair/reload controls for external plugins.
- Changed external reload to validate replacement code before stopping the working version; failed updates now keep the previous version available and report a reload error.
- Added shutdown-hook timeouts, reload/error counters, timeout/cancellation metrics, registry generation, and hardening settings to diagnostics and Plugin Manager payloads.
- Added Windows `tzdata` dependency plus a fixed UTC+7 fallback for `Asia/Jakarta`.
- Added plugin manifest/security documentation and an ignored `plugins/_template/` starter package.
- Added plugin hardening regression tests; 90 automated tests pass.

## 0.6.2

- Added startup and on-demand discovery of trusted local Python plugins from the top-level `plugins/` folder.
- Added strict JSON manifest validation, SDK-major compatibility checks, safe entry-path validation, duplicate-ID protection, and tool-schema verification.
- Unified built-in and external capabilities in the existing Plugin Registry without changing the conversation or LLM tool interfaces.
- Added per-plugin and reload-all lifecycle controls, safe unload when a plugin folder is removed, and optional async shutdown hooks.
- Added failed-load isolation and dashboard reporting for missing manifests, invalid JSON, unsupported SDK versions, import errors, factory errors, and duplicate IDs.
- Added built-in/external source labels, external plugin paths, SDK versions, reload controls, and failed-load cards to the responsive Plugins page.
- Added the `example_echo` reference plugin and external-plugin developer documentation.
- Preserved Phase 2 global enable/disable state and migrated it to the generalized `disabled_plugins` setting while maintaining downgrade compatibility.
- Added regression tests for discovery, execution, reload, folder removal, load-error recovery, duplicate IDs, APIs, and UI integration.

## v0.6.1 - Built-in Plugin Manager Phase 2

- Added a responsive Plugins page with global enable/disable controls for built-in capabilities.
- Persisted disabled plugin IDs in SQLite settings and restored them at startup.
- Added plugin metadata, health state, permissions, agent assignment counts, execution/error totals, and latency metrics.
- Added per-plugin and global metric reset actions.
- Added authenticated Plugin Manager APIs and live `plugins_changed` dashboard events.
- Added Plugin Manager information to bootstrap, runtime status, diagnostics snapshots, exports, and the non-destructive self-test.
- Marked globally disabled tools inside the agent editor without deleting agent assignments.
- Kept external plugin discovery, installation, manifests, removal, and hot reload out of scope for Phase 2.

## v0.6.0 - Internal plugin architecture Phase 1

- Split current time, location, weather, and stop-conversation capabilities into independent built-in plugin modules.
- Added an ordered plugin registry and manager with execution health and latency metrics.
- Kept the existing ToolService API, agent tool IDs, prompts, database settings, and conversation behavior backwards compatible.
- Added internal plugin architecture documentation and automated tests.

## 0.5.3

- Added frontend/backend version capability checks for Diagnostics.
- Replaced repeated 404 `Not Found` toasts with a clear update/restart notice when static files and the running backend do not match.
- Added an explicit Diagnostics capability declaration to `/api/bootstrap`.
- Aligned Diagnostics health, self-test, soak, latency, log, and export cards to a consistent grid.
- Added four loading placeholders so the health row remains straight before the first runtime snapshot.

## 0.5.2

- Added a dedicated Diagnostics Settings submenu with Core, Audio Engine, AI Engine, system-resource, heartbeat, queue, and restart health cards.
- Added non-destructive system self-tests for SQLite, writable runtime directories, Audio Engine responsiveness, Windows audio endpoints, AI Engine responsiveness, Ollama, and pipeline state.
- Added rolling redacted runtime logs with level filtering, dashboard clearing, and safe diagnostics ZIP export.
- Added per-turn latency history for STT, LLM, tools, TTS, and total response time without storing conversation content.
- Added configurable 5-minute to 2-hour soak monitoring for CPU, RAM, process RSS, thread counts, engine heartbeat age, queue use, restart deltas, and pipeline errors.
- Added process-level resource metrics for Core, Audio Engine, and AI Engine.
- Added an SVG favicon so normal dashboard startup no longer produces a favicon 404.
- Added diagnostics privacy protections: session tokens are redacted and exports exclude `.env`, PIN, database, conversations, certificates, caches, and model files.
- Added Phase 3 diagnostics regression tests; 70 automated tests pass.

## 0.5.1

- Reorganized the Settings page into Conversation, Host audio, AI models, Runtime, and Data submenus.
- Added responsive desktop side navigation and mobile horizontal category navigation for Settings.
- Added the persistent `show_rejected_stt_transcripts` runtime setting.
- Added a dashboard toggle to show or hide low-confidence STT transcripts that were not sent to the agent.
- Restyled rejected transcripts as muted gray diagnostic messages with a Filtered STT label.
- Prevented hidden rejected transcripts from removing the empty conversation state or cluttering the visible chat.
- Added database, schema, static UI, and version regression tests.

## 0.5.0

- Added a supervised AI Engine child process that owns SenseVoice/FunASR and local Kokoro native model objects.
- Added asynchronous model preload, persistent model reuse, model reload controls, heartbeat monitoring, and automatic AI process restart.
- Added bounded ASR and Kokoro queues with one active inference per provider.
- Routed immutable PCM utterances to the AI Engine and returned structured transcription results with confidence metadata.
- Routed Kokoro generation to the AI Engine while keeping Edge TTS and Ollama outside it.
- Added AI Engine and model health, load time, inference latency, queue depth, PID, heartbeat, and restart information to the API and dashboard.
- Added authenticated Restart AI Engine, Reload SenseVoice, and Reload Kokoro actions.
- Added an in-process compatibility mode through `VERBANODE_AI_ENGINE_PROCESS=false`.
- Added Phase 3 process, proxy, queue-boundary, and shared-audio-path tests.

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
