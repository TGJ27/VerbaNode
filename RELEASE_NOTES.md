# VerbaNode v0.6.2 Phase 3 — Trusted Local External Plugins

This alpha release completes the three-phase plugin-separation roadmap by adding external folder discovery and reload support on top of the built-in Plugin Registry and Plugin Manager.

## Changes

- Added startup and on-demand scanning of the top-level `plugins/` folder.
- Added validated `plugin.json` manifests and SDK-major compatibility checks.
- Added dynamic loading through a required `create_plugin()` factory.
- Added safe isolation and dashboard reporting for invalid manifests, missing entry files, unsupported SDK versions, import failures, factory failures, duplicate IDs, and runtime errors.
- Added **Reload external** and per-plugin **Reload** controls.
- Added automatic unload when an external plugin folder is removed and the external registry is reloaded.
- Added built-in/external labels, SDK versions, paths, failed-load status, permissions, health, metrics, and agent-assignment visibility.
- Added `plugins/example_echo/` and `docs/EXTERNAL_PLUGINS.md` as a working reference.
- Preserved existing database compatibility, agent tool IDs, deterministic routing, LLM function calling, diagnostics, Audio Engine, and AI Engine behavior.
- Includes 85 passing automated tests.

## Security scope

External plugins are trusted local Python code executed inside the VerbaNode Core process. Error isolation prevents many plugin failures from stopping VerbaNode, but this is not a security sandbox. Only install code you trust. Automatic dependency installation, a marketplace, shell permissions, and untrusted-code isolation are not included.

## Upgrade

Keep `.git`, `.env`, `data/`, `models/`, and `certs/` when applying the replacement files. Keep the new top-level `plugins/` folder. Existing databases remain compatible. The generalized `disabled_plugins` setting is created automatically while the older Phase 2 setting is retained for downgrade compatibility.
