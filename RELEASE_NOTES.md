# VerbaNode v0.12.5 — Connection + Discovery Hardening

## LAN discovery

- Keeps DNS-SD/mDNS advertisement on `_verbanode._tcp.local.`.
- Adds active UDP discovery protocol v1 on the configured VerbaNode port (UDP 8002 by default).
- Discovery responses expose only product/version/instance/API/WS/HTTPS-port/SPKI metadata. No PIN, session, device token, or pairing secret is transmitted.
- Android v0.5.2 verifies every discovery hint against HTTPS `/api/client-info` and the presented certificate before it can be used for authenticated connection.

## Windows networking

- Development firewall helper now opens the configured VerbaNode port for both HTTPS TCP and active-discovery UDP on Private networks, while retaining mDNS UDP 5353.
- The packaged installer remains executable-scoped and protocol-agnostic, so the VerbaNode executable can receive both TCP and UDP traffic on Private networks.

REST API v1, WebSocket protocol v1, mobile contract v1, and database schema v14 are unchanged.
