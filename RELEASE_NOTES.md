# VerbaNode v0.12.1 — Windows Audio Playback Recovery

v0.12.1 is a focused Core hotfix for a shared Windows speaker failure that can silence TTS, Scripts, Type-to-Talk, and Audio Library at the same time.

## Shared playback recovery

- Normal playback still prefers the isolated Audio Engine and its existing device refresh/restart recovery.
- If that path remains unavailable, Core can use a dormant in-process `HostAudioPlayer` as a last-resort playback path.
- If the saved Windows speaker ID still exists but cannot actually be opened, ordinary shared playback may retry through the Windows system-default output for the current session.
- Once the system-default fallback succeeds, subsequent shared playback stays on that safe session fallback until the user explicitly selects or refreshes an output device.
- The fallback is session-only and does not silently overwrite the user's saved speaker preference.

## Diagnostics integrity

- Explicit **Test Output** requests remain strict: a test for device N never succeeds by secretly playing through another device.
- Player health reports whether local/system-default fallback is active and why it was entered.
- TTS `last_error` now includes speaker/playback failures that occur after synthesis succeeds.

## Compatibility

- Database schema remains **v14**; no migration is required from v0.12.0.
- Hybrid RAG Phase 7 behavior remains unchanged.
- No Android API change is required.
- No VLM is introduced.
