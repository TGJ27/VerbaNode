# Contributing

1. Create a branch from `main`.
2. Keep runtime data, models, certificates, `.env`, and caches out of commits.
3. Install the test environment with `python -m pip install -r requirements-dev.txt soundfile sounddevice`. The dev requirements include the lightweight Knowledge document fixtures used by the test suite without installing the full STT/TTS runtime.
4. Run `python -m pytest -q` before opening a pull request.
5. Describe Windows/audio hardware used for changes involving microphones, speakers, Bluetooth, or browser permissions.
6. Keep migrations backward-compatible with existing SQLite databases whenever possible.
