from __future__ import annotations

from abc import ABC, abstractmethod

from app.capabilities.models import CapabilityDescriptor, CapabilityRequest, CapabilityResult


class CapabilityProvider(ABC):
    """Stable provider contract for future robot/device integrations.

    Providers own the actual hardware/service boundary. Plugins should request
    provider operations through ``PluginContext.gateway`` instead of importing a
    robot, display, camera, serial, or MQTT implementation directly.
    """

    id: str = ""
    name: str = ""
    capabilities: tuple[CapabilityDescriptor, ...] = ()
    max_concurrency: int = 1
    default_timeout_seconds: float | None = None

    @abstractmethod
    async def execute(self, request: CapabilityRequest) -> CapabilityResult:
        """Execute one capability operation."""

    async def cancel(self, operation_id: str) -> bool:
        """Best-effort provider-specific cancellation hook."""
        return False

    async def shutdown(self) -> None:
        """Optional lifecycle hook for closing hardware/service resources."""
        return None


__all__ = ["CapabilityProvider"]
