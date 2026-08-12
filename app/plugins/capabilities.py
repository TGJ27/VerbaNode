from __future__ import annotations

from dataclasses import dataclass


class CapabilityPermissionError(PermissionError):
    """Raised when a plugin requests a capability it did not declare."""


@dataclass(frozen=True, slots=True)
class CapabilityGateway:
    """Permission-aware capability boundary exposed to plugins.

    External plugins are still trusted local Python code, so this is not a
    sandbox. It establishes the supported path for future robot/display/camera
    services and centralizes permission checks before those services exist.
    """

    plugin_id: str
    permissions: frozenset[str]

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
