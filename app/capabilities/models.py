from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


TERMINAL_CAPABILITY_STATES = frozenset(
    {"completed", "failed", "timed_out", "cancelled", "expired"}
)


@dataclass(frozen=True, slots=True)
class CapabilityDescriptor:
    """One operation exposed by a capability provider."""

    name: str
    permission: str
    description: str = ""
    destructive: bool = False


@dataclass(frozen=True, slots=True)
class CapabilityRequest:
    """Normalized request passed to a capability provider."""

    operation_id: str
    capability: str
    plugin_id: str
    arguments: dict[str, Any]
    parent_action_id: str | None = None
    created_at: str = ""
    expires_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CapabilityResult:
    """Provider-independent result returned through ``CapabilityGateway``."""

    operation_id: str
    capability: str
    provider_id: str
    data: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    status: str = "completed"
    verified: bool = True
    error: str | None = None
    error_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = dict(self.data)
        payload["_capability"] = {
            "operation_id": self.operation_id,
            "capability": self.capability,
            "provider_id": self.provider_id,
            "success": bool(self.success),
            "status": self.status,
            "verified": bool(self.verified),
        }
        if self.error:
            payload.setdefault("error", self.error)
        if self.error_code:
            payload["_capability"]["error_code"] = self.error_code
        return payload


__all__ = [
    "CapabilityDescriptor",
    "CapabilityRequest",
    "CapabilityResult",
    "TERMINAL_CAPABILITY_STATES",
]
