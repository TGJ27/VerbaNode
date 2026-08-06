# VerbaNode External Plugins

Each non-hidden subfolder is one trusted local Python plugin. VerbaNode scans this folder at startup and when **Reload external** is pressed.

Use `plugins/_template/` as the starting point. The template folder is ignored until copied and renamed.

External plugins execute inside VerbaNode Core. Validation, timeouts, failure thresholds, cancellation, and safe reload protect application reliability, but this is not a security sandbox. Only install code you trust.

See:

- `docs/EXTERNAL_PLUGINS.md`
- `docs/PLUGIN_MANIFEST.md`
- `docs/PLUGIN_SECURITY.md`
