# v0.8.0 Architecture Foundation

## Goal

v0.8.0 makes VerbaNode safer to extend before adding mobile discovery/pairing or robot-specific hardware features. The current browser dashboard remains a first-class client. A future mobile application should consume the same REST and WebSocket contracts rather than introducing a second backend path.

## Client-neutral backend

```text
Web dashboard ---------+
                       |
                       +--> REST + WebSocket protocol v1 --> VerbaNode services
                       |
Future mobile app -----+
```

Discovery and pairing are not part of this release. A future mobile app can initially connect by manually entering a VerbaNode address and authenticating through the same controller API; discovery/pairing can be added as a separate onboarding layer later.

## Persistent action lifecycle

```text
request(action_id)
      |
      v
SQLite claim / argument binding
      |
      +-- terminal existing action --> replay stored result
      |
      +-- same active action -------> join/in-progress, never execute twice
      |
      +-- different payload --------> conflict
      |
      v
pending -> running -> completed / failed / timed_out / cancelled
```

The ledger is intentionally conservative after crashes: an unfinished action is not automatically retried. This avoids repeating a physical side effect after the process restarts without knowing whether the hardware already performed it.

## API layout

`app/main.py` remains responsible for application lifecycle, root/health, and runtime-heavy audio/AI/diagnostics surfaces. Product CRUD/control domains are moved into `app/api/` routers so future clients consume explicit backend APIs instead of depending on browser JavaScript internals.

## WebSocket protocol v1

Outbound event envelope:

```json
{
  "protocol": 1,
  "type": "agents_changed",
  "event": "agents_changed",
  "timestamp": "...",
  "data": {}
}
```

`event` remains during the compatibility period. New commands use `type: "command.<name>"` and may carry `request_id` plus a `data` object. The server still accepts the older `{ "command": "..." }` shape.

## Deferred mobile work

The following require product decisions from the actual mobile client and are intentionally postponed:

- local discovery mechanism and service advertisement
- QR/PIN pairing UX
- device identity and trusted credential storage
- revocation/device management
- simultaneous-controller policy
- background connectivity and reconnect behavior
- remote access outside the LAN
