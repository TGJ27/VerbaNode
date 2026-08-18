# v0.9.1 Media Library & Queue UX

## Audio Library

Authenticated clients use `/api/audio-library` to list host audio, upload MP3/WAV files, start/stop playback, rename files, and delete files. Playback uses the existing host audio output service. Starting library audio stops conversation/script-queue playback to avoid competing output ownership.

## Configuration options

`GET /api/configuration-options` is the shared selector contract for web/native clients. It currently exposes languages, available/default LLM models, language-specific STT models, and TTS modes. Clients should prefer this endpoint instead of hardcoding editable model/language strings.

## Script queue controls

Queue responses include `loop` and each item includes `pause_after_seconds`. Loop state is persisted in settings. Pause duration is persisted with the queue item. Reorder operations must include every current queue ID exactly once.

## Update identity

Version numbers are metadata, not identity. Core identity comes from the persistent database `instance_id`; Android identity comes from its stored profile/device credential. Source mode now uses stable user data by default and migrates legacy v0.9.0 repo-local state once. This prevents a clean source update from appearing as a new VerbaNode instance.
