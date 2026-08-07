# VerbaNode v0.7.3 Beta

This stabilization release focuses on the English/Indonesian voice pipeline introduced in v0.7.x.

## Highlights

- Whisper Base and Whisper Small cache/download status is visible in Settings → AI Models.
- Added **Test active language profile** to verify the selected ASR model can load and that the language-matched Edge voice can play.
- ASR reload and benchmark controls are locked while model operations are in progress to prevent overlapping reloads.
- English agents are constrained to SenseVoiceSmall and English Edge voices. Indonesian agents are constrained to Whisper Base/Small and Indonesian Edge voices.
- Indonesian scripts use Edge TTS only; incompatible Kokoro controls are disabled and validated before save.
- Existing Audio Engine, AI Engine, plugin, selective-context, and per-script TTS behavior remains compatible.
