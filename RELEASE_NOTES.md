# VerbaNode v0.9.0 — Local Mobile & Trusted Devices

v0.9.0 is the first post-v0.8 feature release. It keeps VerbaNode LAN-only while adding the server-side foundation required by the separate native Android controller: automatic local discovery, QR/code pairing, persistent trusted-device credentials, device revocation, and stable local TLS identity.

## Local discovery

- VerbaNode advertises `_verbanode._tcp.local.` with DNS-SD/mDNS when discovery is enabled.
- Discovery metadata includes product, Core version, REST API version, WebSocket protocol version, persistent instance ID, TLS requirement, and the stable HTTPS public-key identity.
- `/api/discovery/status` exposes the current advertisement state to authenticated clients.
- `scripts/windows/allow_firewall.bat` now adds Private-network rules for the VerbaNode TCP port and mDNS UDP 5353 when running from source.
- The packaged installer keeps its existing Private-network program-scoped firewall rule, which covers the VerbaNode executable.

## Trusted local devices

Database schema v5 adds a `trusted_devices` registry. A trusted Android device receives a high-entropy bearer credential during pairing; only its SHA-256 digest is stored in the VerbaNode database.

Authenticated users can:

- list trusted devices
- rename devices
- revoke credentials immediately
- delete already-revoked devices
- see which trusted device currently owns the single controller session

A revoked device cannot use its old credential again. PIN login remains available as the recovery/fallback authorization path.

## QR and short-code pairing

The web dashboard now has **Settings → Devices** with a local pairing flow:

1. Start a short-lived pairing request.
2. Scan the QR code in VerbaNode Android or enter the displayed short code.
3. The Android client proves the pairing secret locally over pinned HTTPS.
4. VerbaNode issues a unique trusted-device credential.
5. The phone can reconnect later without re-entering the dashboard PIN until the device is revoked.

Pairing secrets remain memory-only and expire automatically. The public claim endpoint is rate-limited and never exposes an existing pairing secret.

## Stable local HTTPS identity

VerbaNode still generates its HTTPS certificate locally and never distributes a private key in source or release archives.

For mobile trust, v0.9.0 introduces a SHA-256 SubjectPublicKeyInfo (SPKI) identity. When the machine's LAN IP addresses change, VerbaNode refreshes the certificate SANs while reusing the existing private key. This means:

- certificate bytes/fingerprint may change after an IP change
- the pinned public-key/SPKI identity remains stable
- a trusted phone does not need to silently disable TLS validation

`/api/client-info`, pairing payloads, and mDNS metadata expose the non-secret SPKI identity needed by local clients.

## Mobile-aware authentication

- Added `POST /api/auth/device-login` for trusted local devices.
- Controller sessions can carry a `device_id` in addition to client type/name/version metadata.
- Trusted-device login still enters the same existing single-active-controller model as the web dashboard.
- Taking control from web to Android (or back) remains deterministic; v0.9.0 does not introduce concurrent controller ownership.

## Client contract additions

`GET /api/client-info` now advertises:

- persistent VerbaNode instance ID/name
- PIN-or-trusted-device authentication
- trusted-device login endpoint
- pairing endpoints
- mDNS service type and enabled state
- stable HTTPS SPKI identity
- feature flags for discovery, pairing, trusted devices, and revocation

The REST API remains v1 and WebSocket Protocol remains v1, so the new Android client builds on the contracts stabilized in v0.8 rather than requiring another backend rewrite.

## Web dashboard device management

The existing framework-free web dashboard now includes a Devices settings panel with:

- discovery status
- pairing QR code
- short pairing code
- pairing expiry/claim status
- trusted-device list
- rename
- revoke
- delete

## Packaging and dependencies

- Added `zeroconf` for DNS-SD/mDNS advertisement.
- Added `qrcode` for local pairing QR generation.
- Added an explicit `cryptography` dependency because stable certificate public-key identity is now a product feature.
- Updated PyInstaller collection so the packaged Windows application includes the new mobile/discovery dependencies.

## Security boundary

v0.9.0 remains intentionally **LAN-only**. It does not add a cloud relay, Internet remote control, NAT traversal, or a VerbaNode account service.

Manual server address entry remains supported even when mDNS discovery is available.

## Validation

The clean v0.9.0 Core tree passes **222 automated tests**, including new coverage for schema v5, QR/code pairing, trusted credentials, revocation, trusted controller sessions, and stable SPKI identity across certificate refreshes.

The Android application is maintained as a separate project/repository and has its own release version. VerbaNode Core v0.9.0 provides the local discovery/pairing/device-management contract it consumes.
