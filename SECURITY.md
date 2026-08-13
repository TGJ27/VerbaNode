# Security

## Reporting

Report security issues privately to the repository maintainer rather than opening a public issue containing credentials, tokens, private certificates, or personal data.

## Deployment notes

- Change the generated controller PIN if it has been shared.
- Keep VerbaNode on a trusted private network.
- Do not expose port 8002 directly to the public internet.
- Protect `.env`, `data/`, backups, certificates, logs, and model directories.
- Browser-device microphone access uses locally generated HTTPS certificates; verify and trust only certificates generated on your own host.
- Repeated failed PIN attempts are throttled, but the PIN is still intended as a private-LAN controller credential rather than an internet-facing authentication system.
- Controller WebSockets use short-lived one-time tickets. The primary controller session token should remain in authenticated HTTPS headers and browser session storage, not URLs.
- External plugins are trusted local Python code. Manifest permissions and the capability gateway establish the supported permission-checked API path, but they do not create a Python security sandbox.
- Review external plugin source before enabling capabilities such as `robot`, `shell`, `filesystem_write`, `camera`, `microphone`, `serial`, or `mqtt`.
- Capability action audit logs can contain tool arguments and operational metadata; treat them as potentially sensitive local logs.

## v0.8 action and restore safety

- Capability `action_id` values are persisted in SQLite and bound to the plugin plus canonical argument payload. Do not reuse an action ID for a different physical command.
- The action ledger can contain capability arguments, results, errors, and operational timestamps. Protect the VerbaNode database as sensitive local state.
- An action left unfinished by a crashed process is treated conservatively and is not automatically re-executed. Use a new action ID only after the operator/backend has determined the real hardware state.
- Backup restore accepts only bounded ZIP/database sizes, validates the manifest/schema and SQLite integrity, creates a pre-restore safety backup, and uses an atomic replacement path. Keep backup files private because they contain agents, conversations, settings, and other local state.
