# VerbaNode v0.4.2 Phase 2 Hot-Plug Recovery Test Release

## Windows audio hot-plug recovery

- Added a real PortAudio refresh path for USB and Bluetooth devices connected after VerbaNode has already started.
- **Refresh Devices** now stops active audio safely, rebuilds the Windows/PortAudio device snapshot, remaps saved device fingerprints, and returns the updated input/output list.
- Microphone lock, speaker lock, host PTT, microphone tests, and speaker playback automatically trigger hot-plug recovery after an initial device-open failure.
- Recovery waits through the Windows Bluetooth profile registration period, retries device enumeration, remaps changed PortAudio IDs, and restores the requested microphone/speaker lock state.
- If PortAudio reinitialization is insufficient, VerbaNode restarts only the isolated Audio Engine process once and retries the endpoints; FastAPI, the UI, database, LLM, tools, and memory stay online.
- Default-device opening now uses the actual Windows profile sample rate when available and tries safe fallback sample rates, channel counts, and latency modes.
- Added device refresh and hot-plug recovery counters to Runtime Status.

## Preserved v0.4.1 hardening

- Emoji remains blocked by hidden prompt policy and backend sanitization before display, storage, and TTS.
- Stop Conversation immediately cancels playback and clears pending speech.
- Silero VAD remains cached once per Audio Engine process.

## Upgrade

Keep `.git`, `.env`, `data/`, `models/`, and `certs/`. Copy the new repository files over the existing checkout, then run:

```bat
setup_windows.bat
setup_database.bat
run.bat
```

## Hardware test checklist

1. Start VerbaNode with no external microphone connected.
2. Connect the microphone or Bluetooth headset while VerbaNode remains running.
3. Wait until Windows shows the endpoint, then press **Refresh Devices** or start Conversation Mode directly.
4. Confirm the terminal reports `Recovering Windows audio devices` followed by `Windows audio recovery completed`.
5. Test microphone, speaker, duplex lock, conversation mode, PTT, unplug/reconnect, and Audio Engine restart.

## Test status

55 automated tests pass. This remains a Phase 2 hardware test build until hot-plug behavior has been confirmed on the target Windows PC and audio devices.
