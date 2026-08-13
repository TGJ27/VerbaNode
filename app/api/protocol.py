from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

API_VERSION = 1
MIN_API_VERSION = 1
PROTOCOL_VERSION = 1

WS_CLOSE_UNAUTHORIZED = 4401
WS_CLOSE_ORIGIN_REJECTED = 4403
WS_CLOSE_PROTOCOL_UNSUPPORTED = 4406
WS_CLOSE_HEARTBEAT_TIMEOUT = 4408


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def event_envelope(
    event: str,
    data: Any = None,
    *,
    request_id: str | None = None,
) -> dict[str, Any]:
    """Versioned WebSocket event with a legacy ``event`` compatibility field."""
    payload: dict[str, Any] = {
        "protocol": PROTOCOL_VERSION,
        "type": str(event),
        "event": str(event),
        "timestamp": _timestamp(),
        "data": data,
    }
    if request_id:
        payload["request_id"] = str(request_id)
    return payload


def parse_command(payload: Any) -> tuple[str | None, dict[str, Any], str | None]:
    """Accept protocol-v1 commands and the v0.7 legacy command shape."""
    if not isinstance(payload, dict):
        return None, {}, None

    request_id = payload.get("request_id")
    request_id = str(request_id) if request_id else None

    legacy = payload.get("command")
    if legacy:
        data = {key: value for key, value in payload.items() if key not in {"command", "protocol", "type", "request_id"}}
        return str(legacy), data, request_id

    message_type = str(payload.get("type") or "")
    if not message_type.startswith("command."):
        return None, {}, request_id
    command = message_type.removeprefix("command.")
    data = payload.get("data")
    return command, dict(data) if isinstance(data, dict) else {}, request_id


__all__ = [
    "API_VERSION",
    "MIN_API_VERSION",
    "PROTOCOL_VERSION",
    "WS_CLOSE_HEARTBEAT_TIMEOUT",
    "WS_CLOSE_ORIGIN_REJECTED",
    "WS_CLOSE_PROTOCOL_UNSUPPORTED",
    "WS_CLOSE_UNAUTHORIZED",
    "event_envelope",
    "parse_command",
]
