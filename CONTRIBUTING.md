# Contributing

1. Create a branch from `main`.
2. Keep runtime data, models, certificates, `.env`, and caches out of commits.
3. Run `python -m pytest -q` before opening a pull request.
4. Describe Windows/audio hardware used for changes involving microphones, speakers, Bluetooth, or browser permissions.
5. Keep migrations backward-compatible with existing SQLite databases whenever possible.
