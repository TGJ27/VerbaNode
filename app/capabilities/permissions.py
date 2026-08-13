from __future__ import annotations

import re


ALLOWED_PERMISSIONS = frozenset(
    {
        "internet",
        "network",
        "filesystem_read",
        "filesystem_write",
        "camera",
        "microphone",
        "display",
        "robot",
        "serial",
        "mqtt",
        "shell",
    }
)

_CAPABILITY_NAME_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
)

_PREFIX_PERMISSIONS = {
    "filesystem.read": "filesystem_read",
    "filesystem.write": "filesystem_write",
}


class CapabilityPermissionError(PermissionError):
    """Raised when a caller requests a capability it did not declare."""


class CapabilityNameError(ValueError):
    """Raised when a capability name does not follow the namespaced contract."""


def normalize_capability_name(capability: str) -> str:
    value = str(capability or "").strip().lower()
    if not _CAPABILITY_NAME_PATTERN.fullmatch(value):
        raise CapabilityNameError(
            "Capability names must be lowercase dot-separated identifiers, "
            "for example 'robot.navigate' or 'display.show'"
        )
    return value


def permission_for_capability(capability: str) -> str:
    """Resolve the manifest permission required by a namespaced capability."""
    value = normalize_capability_name(capability)
    for prefix, permission in _PREFIX_PERMISSIONS.items():
        if value == prefix or value.startswith(prefix + "."):
            return permission
    root = value.split(".", 1)[0]
    if root not in ALLOWED_PERMISSIONS:
        raise CapabilityPermissionError(
            f"Capability '{value}' has no supported permission namespace"
        )
    return root


__all__ = [
    "ALLOWED_PERMISSIONS",
    "CapabilityNameError",
    "CapabilityPermissionError",
    "normalize_capability_name",
    "permission_for_capability",
]
