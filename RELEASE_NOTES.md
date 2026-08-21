# VerbaNode v0.9.2 — Direct Speech & Workflow UX


- Fixed the Conversation right rail so controls start at the top instead of leaving a large blank area.
- Reworked Type to Talk into a chat-style direct-speech transcript with Enter-to-send, queued messages, persistent speech history, and per-message TTS language/engine/voice/rate/volume configuration.
- Script creation keeps speech controls inside the Create/Edit dialog again; a new script is prefilled from the last script configuration you saved, and falls back to standard defaults when no previous configuration exists.
v0.9.2 is the coordinated Core/Web release for VerbaNode Android v0.3.3. It focuses on direct speech, repeatable script authoring, broader audio playback, and consistent client configuration. RAG and large-knowledge retrieval are intentionally deferred.

## Type to Talk

- Added a persistent Core-hosted Type-to-Talk queue shared by Web and Android.
- Typed text is sent directly to TTS; it does not pass through the LLM.
- Multiple entries can be added while speech is already playing.
- Clients can play, stop, clear, remove, and reorder queued entries.
- Queue state survives client disconnects and is reconciled on Core restart.

## Script defaults

- Added persistent defaults for language, TTS mode, Edge voice, Kokoro voice, speech rate, and volume.
- New scripts inherit the last saved defaults instead of reverting after each add.
- Existing scripts keep their saved speech configuration when edited.
- Web and Android expose the defaults outside the per-script add flow.

## Audio Library

- Expanded accepted formats to WAV, MP3, FLAC, OGG/OGA, Opus, M4A, AAC, WMA, AIFF/AIF, WebM audio, MKA, and AMR.
- Formats supported by the normal decoder play directly. Other supported uploads can use an `ffmpeg` executable on PATH as a decode fallback.
- Uploaded files are validated by VerbaNode and remain in persistent user data.

## Client configuration

- Android model selection merges shared `/api/configuration-options` choices with the live installed-model catalog from Core.
- Client capability metadata advertises Type-to-Talk, script defaults, and broad audio support.

## Compatibility

- REST API remains v1.
- WebSocket protocol remains v1.
- Database schema advances to v7 and migrates automatically.
- Trusted-device pairing remains LAN-only and single-active-controller.
- No RAG/vector database/document-ingestion system is included in this release.

- Expanded Audio Library MPEG-family compatibility for `.mpeg`, `.mpg`, `.mpga`, and `.mp2` files (decoded through the existing FFmpeg fallback when required).
