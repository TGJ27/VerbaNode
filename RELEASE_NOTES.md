# VerbaNode v0.7.7 — Pre-Major Hardening & Conversation UX

v0.7.7 is the final hardening/polish release before the next major capability-development phase. It keeps the existing Windows application, online installer, bilingual voice pipeline, plugin architecture, and development workflow while tightening chat UX, authentication, build reproducibility, database migration structure, and the future capability execution contract.

### Web branding polish

- Replaced the legacy `VN` badge on the login screen and dashboard header with the VerbaNode application logo.
- Aligned the dashboard favicon, static asset cache-busters, and HTML fallback version with v0.7.7.

## Conversation UX

- Added a persistent **Auto-scroll ON/OFF** control to the Conversation header.
- **Auto-scroll ON** strictly locks the message history to the newest content; user scrolling is disabled while the lock is active.
- **Auto-scroll OFF** unlocks normal mouse/trackpad/touch scrolling and new messages do not move the current viewport.
- Added a floating **New messages** button while Auto-scroll is off; clicking it jumps to the newest content without re-enabling Auto-scroll.
- The Auto-scroll preference is persisted in browser local storage.
- Conversation header now exposes active agent language, STT model, TTS mode, and LLM context in compact chips.
- Existing Listening / Transcribing / Thinking / Speaking status reporting remains visible above the message history.

## Controller authentication hardening

- Added per-client failed-PIN throttling with bounded exponential lockout.
- Added configurable login attempt/window/lockout settings.
- Removed the long-lived controller session token from the WebSocket URL.
- Added short-lived, single-use WebSocket tickets created through an authenticated HTTPS endpoint.
- WebSocket tickets are consumed once and cannot be replayed.

## Plugin/capability execution foundation

- Expanded `PluginResult` with verified action semantics while preserving the existing dictionary tool contract.
- Every successful plugin execution now carries `_action` metadata with action ID, success state, status, and verification state.
- Added explicit `action_id` support for idempotent retries; repeated execution with the same explicit action ID returns the cached verified result instead of performing the action again.
- Added a permission-aware `CapabilityGateway` to `PluginContext` as the supported boundary for future robot/display/camera/device services.
- Added persistent JSONL capability action audit logging plus an authenticated `/api/plugins/actions` endpoint.
- Built-in weather now exercises the permission gateway for its declared `internet` capability.

> External plugins are still trusted local Python code and are not a security sandbox. The capability gateway establishes the supported permission-checked path for future physical capabilities.

## Database migration foundation

- Added numbered schema migration infrastructure under `app/migrations/`.
- Existing databases receive a `schema_version` marker without losing current data.
- Existing legacy compatibility migrations remain in place; future schema changes can now be added as ordered numbered migrations.

## Codebase hardening

- Removed accidental duplicate SenseVoice cache helpers, duplicate Ollama checks, duplicate health-report keys, and a duplicate plugin-manager loop introduced during earlier patching.
- Moved controller authentication and WebSocket endpoints from `app/main.py` into `app/api/auth.py` with shared auth dependencies under `app/api/deps.py`.
- Added high-signal Ruff correctness checks to GitHub Actions.
- Added dashboard JavaScript syntax validation to CI.
- Full Python compile and regression tests remain part of CI.

## Reproducible Windows builds

- `build_windows.bat` now uses a separate `verbanode-build` Conda environment by default, leaving the normal development environment untouched.
- Windows packaging dependencies are pinned to the validated build versions.
- `app/version.py` is the single application version source used by build scripts.
- `build_installer.bat` reads `APP_VERSION` and passes it to Inno Setup, so the generated installer filename and metadata follow the application version automatically.

## Compatibility

- Normal source development remains available through `run.bat` / `run_https.bat`.
- Installed user data and model caches remain upgrade-safe.
- Existing plugin result data fields and tool call behavior remain backwards compatible.
- No user database reset is required.

## Validation

- 160 automated tests passing.
- Python compilation passes.
- Dashboard JavaScript syntax check passes.
- Application import/startup surface validates with FastAPI v0.7.7 metadata.

## Next

The next major release can build on the new verified action/capability contract for robot-specific functions such as status, display control, navigation, photobooth, and other physical integrations.
