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
