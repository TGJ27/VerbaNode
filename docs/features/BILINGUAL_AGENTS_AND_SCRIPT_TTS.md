# Bilingual agents and per-script TTS

VerbaNode v0.7.0 supports one active language profile at a time. The active agent determines the speech-recognition model, response language, deterministic tool formatting, and default Edge voice.

## Language profiles

| Agent language | ASR model | ASR decoding | Recommended TTS | Default voice |
|---|---|---|---|---|
| English | `iic/SenseVoiceSmall` | English | Edge or Kokoro | `en-US-AriaNeural` |
| Bahasa Indonesia | `Whisper-base` through FunASR | Forced Indonesian (`id`) | Edge | `id-ID-GadisNeural` |

Only the model required by the active agent is used for transcription. The isolated AI Engine unloads the previous ASR model when another model is selected. The first Indonesian turn may therefore take longer while Whisper Base is loaded.

## Windows installation

Run the normal dependency installer:

```bat
scripts/setup/setup_windows.bat
```

The main requirements now include `openai-whisper`. Prepare both ASR models before a demonstration:

```bat
scripts/models/download_funasr.bat
scripts/models/download_whisper.bat
```

The model files are stored in the provider cache outside the Git repository. Do not commit downloaded model files.

## Agent configuration

Open **Agents → Edit → Models & Voice** and select:

- **English**: VerbaNode selects SenseVoiceSmall and filters Edge voices to English locales.
- **Bahasa Indonesia**: VerbaNode selects Whisper Base, forces Indonesian transcription, selects Edge-only TTS, and filters Edge voices to Indonesian locales.

The STT model field is read-only because the language profile controls it.

The default database migration preserves the existing English Ropi and adds **Ropi Indonesia** once. Deleting the Indonesian agent later does not recreate it on every startup.

## Script TTS

Scripts no longer inherit the active agent TTS. Each script stores:

- Language
- TTS mode
- Edge voice
- Kokoro voice
- Speech rate
- Volume

For Indonesian scripts, VerbaNode enforces Edge TTS and an `id-ID` voice. English scripts can use Edge, Kokoro, or either fallback order.

## Verification

1. Activate **Ropi** and say an English sentence. The AI Engine should report `iic/SenseVoiceSmall`.
2. Activate **Ropi Indonesia** and say an Indonesian sentence. The AI Engine should load `Whisper-base`, and the STT log should include `language=id`.
3. Ask the time, weather, or location while Ropi Indonesia is active. The deterministic reply should be in Bahasa Indonesia.
4. Create one English Script and one Indonesian Script with different Edge voices. Run both while either agent is active. Each Script should retain its own voice.
5. Restart VerbaNode and confirm agent language and Script voice settings remain saved.

## Troubleshooting

### Whisper support is not installed

Run:

```bat
scripts/setup/setup_windows.bat
```

Then prepare the model:

```bat
scripts/models/download_whisper.bat
```

### The first Indonesian transcription is slow

This is expected when switching from SenseVoice to Whisper Base for the first time. Pre-download the model and allow the AI Engine to finish loading before speaking.

### Indonesian text uses an English voice

Edit the Indonesian agent or Script and select an `id-ID` Edge voice. VerbaNode also corrects incompatible voice selections when saving.

### Switching agents causes a model reload

This is intentional. Only one ASR model is kept active at a time to control CPU and memory use.
