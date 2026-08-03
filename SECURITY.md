# Security

## Reporting

Report security issues privately to the repository maintainer rather than opening a public issue containing credentials, tokens, or personal data.

## Deployment notes

- Change the generated controller PIN if it is shared.
- Keep VerbaNode on a trusted private network.
- Do not expose port 8002 directly to the public internet.
- Protect `.env`, `data/`, backups, certificates, and model directories.
- Browser-device microphone access uses locally generated HTTPS certificates; verify and trust only certificates generated on your own host.
