# VerbaNode v0.9.1 — Media Library & Queue UX

v0.9.1 is a coordinated Core/Web release for VerbaNode Android v0.3.2. It keeps the v0.9 LAN-only trusted-device model while adding host audio-file playback, richer script-queue controls, mobile configuration selectors, and stable installation identity across source/application updates.

## Audio Library

- Added an **Audio** page to the web dashboard.
- Upload `.mp3` and `.wav` files to the VerbaNode host.
- Play/stop uploaded audio through the Windows host output device.
- Rename and delete uploaded files.
- Added authenticated `/api/audio-library` endpoints for web and Android clients.
- Audio files live in the persistent VerbaNode user-data root so source-folder updates do not remove them.

## Script Queue

- Added persistent **Loop queue** control.
- Added per-item **pause after playback** from 0 to 3600 seconds.
- Added drag reordering in the web dashboard and Android client.
- Queue state now reports its loop setting to all clients.
- Database schema advances to **v6** with `script_queue.pause_after_seconds`.

## Client configuration contract

- Added `/api/configuration-options` for languages, installed/default Ollama models, STT model choices, and TTS modes.
- The Android client uses these options as selectors instead of free-text model/language fields.

## Stable device identity across updates

Source-mode Core runtime identity is now stored under the same persistent LocalAppData-style user-data root used by packaged builds, unless explicit portable mode is enabled. On first v0.9.1 source start, legacy repo-local `.env`, database, certificates, backups, diagnostics, runtime audio, audio library, and logs are copied into the stable user-data root when no stable copy exists.

This preserves the Core `instance_id`, trusted-device database records, controller PIN, and HTTPS private key across clean source-folder replacements. An Android app or Core version change is not treated as a new device.

Set `VERBANODE_PORTABLE_MODE=true` only when intentionally using repo-local source runtime state.

## Chat UX

- Increased usable chat area in the web dashboard.
- Moved the auto-scroll control below the composer.
- Narrowed/lowered the side controls to prioritize conversation space.

## Compatibility

- REST API version remains v1.
- WebSocket protocol remains v1.
- Trusted-device pairing remains LAN-only and single-active-controller.
- Existing v0.9.0 databases migrate automatically to schema v6.
