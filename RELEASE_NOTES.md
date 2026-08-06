# VerbaNode v0.6.7 Beta — Typed Chat Interruption Fix

This maintenance release fixes a deadlock in streamed TTS cancellation.

## Fixed

- Sending a typed chat message while the assistant is speaking now stops the current TTS stream and allows the new turn to continue.
- Cancelling TTS can no longer remove the player queue's only end marker and leave the previous generation lock held forever.
- Repeated Stop TTS or overlapping cancellation requests are idempotent.
- If a TTS worker does not terminate within 2.5 seconds, VerbaNode cancels the worker task and releases the conversation turn instead of requiring an application restart.
- 100 automated tests pass, including regression coverage for the original queue-sentinel race.

## Upgrade

Keep `.git`, `.env`, `data/`, `models/`, and `certs/`. Replace the updated files and restart VerbaNode. No database migration is required.
