from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.capabilities.models import CapabilityResult
from app.capabilities.permissions import (
    CapabilityPermissionError,
    permission_for_capability,
)

if TYPE_CHECKING:
    from app.capabilities.service import CapabilityService


@dataclass(frozen=True, slots=True)
class CapabilityGateway:
    """Permission-aware provider boundary exposed to plugins.

    External plugins remain trusted local Python code, so this is not an OS
    sandbox. The gateway is the supported application-level path for future
    robot/display/camera/serial/MQTT providers and enforces declared permissions,
    provider routing, execution limits, cancellation, and request expiry.
    """

    plugin_id: str
    permissions: frozenset[str]
    service: CapabilityService | None = None
    action_id: str | None = None

    def allows(self, permission: str) -> bool:
        return str(permission) in self.permissions

    def require(self, permission: str) -> None:
        permission = str(permission)
        if permission not in self.permissions:
            raise CapabilityPermissionError(
                f"Plugin '{self.plugin_id}' requires undeclared permission '{permission}'"
            )

    def require_all(self, *permissions: str) -> None:
        for permission in permissions:
            self.require(permission)

    async def invoke(
        self,
        capability: str,
        arguments: dict[str, Any] | None = None,
        *,
        timeout_seconds: float | None = None,
        expires_in_seconds: float | None = None,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CapabilityResult:
        """Invoke a registered provider after enforcing the plugin manifest permission."""
        self.require(permission_for_capability(capability))
        if self.service is None:
            raise RuntimeError("Capability provider service is not available")
        return await self.service.invoke(
            plugin_id=self.plugin_id,
            permissions=self.permissions,
            capability=capability,
            arguments=arguments,
            parent_action_id=self.action_id,
            timeout_seconds=timeout_seconds,
            expires_in_seconds=expires_in_seconds,
            expires_at=expires_at,
            metadata=metadata,
        )


__all__ = ["CapabilityGateway", "CapabilityPermissionError"]
