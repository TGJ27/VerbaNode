from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings
from app.plugins.capabilities import CapabilityGateway


@dataclass(slots=True)
class PluginContext:
    """Runtime context shared with capability plugins.

    Plugins should prefer this stable capability boundary rather than importing
    VerbaNode internals. Future physical capabilities can be exposed through
    ``gateway`` while permission checks remain centralized.
    """

    settings: Settings
    text: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    action_id: str | None = None
    gateway: CapabilityGateway | None = None

    def require_permission(self, permission: str) -> None:
        if self.gateway is None:
            raise RuntimeError("Capability gateway is not available for this plugin execution")
        self.gateway.require(permission)

    def has_permission(self, permission: str) -> bool:
        return bool(self.gateway and self.gateway.allows(permission))
