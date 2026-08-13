from __future__ import annotations

from dataclasses import dataclass
import re

from app.capabilities.models import CapabilityDescriptor
from app.capabilities.permissions import (
    ALLOWED_PERMISSIONS,
    normalize_capability_name,
    permission_for_capability,
)
from app.capabilities.provider import CapabilityProvider


_PROVIDER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


class CapabilityRegistrationError(ValueError):
    """Raised when a provider exposes an invalid or duplicate capability."""


@dataclass(frozen=True, slots=True)
class RegisteredCapability:
    provider: CapabilityProvider
    descriptor: CapabilityDescriptor


class CapabilityRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, CapabilityProvider] = {}
        self._capabilities: dict[str, RegisteredCapability] = {}

    def register(self, provider: CapabilityProvider) -> None:
        provider_id = str(provider.id or "").strip().lower()
        if not provider_id:
            raise CapabilityRegistrationError("Capability provider id is required")
        if str(provider.id) != provider_id or not _PROVIDER_ID_PATTERN.fullmatch(provider_id):
            raise CapabilityRegistrationError(
                "Capability provider id must be a lowercase identifier using letters, "
                "numbers, and underscores"
            )
        if provider_id in self._providers:
            raise CapabilityRegistrationError(
                f"Capability provider '{provider_id}' is already registered"
            )
        descriptors = tuple(provider.capabilities or ())
        if not descriptors:
            raise CapabilityRegistrationError(
                f"Capability provider '{provider_id}' exposes no capabilities"
            )

        normalized: list[tuple[str, CapabilityDescriptor]] = []
        for descriptor in descriptors:
            name = normalize_capability_name(descriptor.name)
            if descriptor.name != name:
                raise CapabilityRegistrationError(
                    f"Capability name '{descriptor.name}' must use canonical lowercase form '{name}'"
                )
            permission = str(descriptor.permission or "").strip()
            if permission not in ALLOWED_PERMISSIONS:
                raise CapabilityRegistrationError(
                    f"Capability '{name}' uses unsupported permission '{permission}'"
                )
            required_permission = permission_for_capability(name)
            if permission != required_permission:
                raise CapabilityRegistrationError(
                    f"Capability '{name}' must use permission '{required_permission}', "
                    f"not '{permission}'"
                )
            if name in self._capabilities or any(existing == name for existing, _ in normalized):
                raise CapabilityRegistrationError(
                    f"Capability '{name}' is already registered"
                )
            normalized.append((name, descriptor))

        self._providers[provider_id] = provider
        for name, descriptor in normalized:
            self._capabilities[name] = RegisteredCapability(provider, descriptor)

    def resolve(self, capability: str) -> RegisteredCapability | None:
        return self._capabilities.get(normalize_capability_name(capability))

    def providers(self) -> list[CapabilityProvider]:
        return list(self._providers.values())

    def provider(self, provider_id: str) -> CapabilityProvider | None:
        return self._providers.get(str(provider_id).strip().lower())

    def describe(self) -> list[dict[str, object]]:
        payload: list[dict[str, object]] = []
        for provider_id in sorted(self._providers):
            provider = self._providers[provider_id]
            payload.append(
                {
                    "id": provider_id,
                    "name": provider.name or provider_id,
                    "max_concurrency": max(1, int(provider.max_concurrency)),
                    "default_timeout_seconds": provider.default_timeout_seconds,
                    "capabilities": [
                        {
                            "name": item.name,
                            "permission": item.permission,
                            "description": item.description,
                            "destructive": bool(item.destructive),
                        }
                        for item in provider.capabilities
                    ],
                }
            )
        return payload


__all__ = [
    "CapabilityRegistrationError",
    "CapabilityRegistry",
    "RegisteredCapability",
]
