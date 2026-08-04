from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.plugins.context import PluginContext
from app.plugins.result import PluginResult


class Plugin(ABC):
    """Base class for every VerbaNode capability plugin.

    Built-in and external plugins share the same runtime contract. External
    plugins are trusted local Python code loaded from the top-level ``plugins``
    directory; they are isolated from loader errors, but they are not a secure
    Python sandbox.
    """

    id: str = ""
    name: str = ""
    version: str = "1.0.0"
    author: str = "Sari Technology Global"
    description: str = ""
    category: str = "General"
    permissions: tuple[str, ...] = ()
    priority: int = 100
    enabled: bool = True
    schema: dict[str, Any] = {}

    # Runtime metadata assigned by the manager/loader.
    source: str = "builtin"
    plugin_path: Path | None = None
    manifest_path: Path | None = None
    reloadable: bool = False
    sdk_version: str = "1"

    def match(self, context: PluginContext) -> dict[str, Any] | None:
        """Return deterministic tool arguments when this plugin can handle text."""
        return None

    @abstractmethod
    async def execute(self, context: PluginContext) -> PluginResult:
        """Execute the capability and return a normalized result."""

    def format_result(self, result: dict[str, Any], context: PluginContext) -> str:
        """Create a concise direct-response fallback for a tool result."""
        if result.get("error"):
            return str(result["error"])
        return str(result.get("message") or result)

    async def shutdown(self) -> None:
        """Optional lifecycle hook called before unload or application shutdown."""
        return None


# Backwards-compatible name used by the Phase 1 built-in modules.
BuiltinPlugin = Plugin

__all__ = ["Plugin", "BuiltinPlugin"]
