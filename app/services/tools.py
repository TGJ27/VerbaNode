from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.config import Settings
from app.plugins.builtin import builtin_plugins
from app.plugins.builtin.weather import WEATHER_DESCRIPTIONS
from app.plugins.manager import PluginManager


class ToolService:
    """Compatibility facade over VerbaNode's unified plugin manager.

    Built-in capabilities and trusted local external plugins share one registry.
    Existing conversation and LLM code can continue calling ``schemas``,
    ``match_core_intent``, ``execute``, and ``format_result``.
    """

    def __init__(self, settings: Settings, manager: PluginManager | None = None):
        self.settings = settings
        self.manager = manager or PluginManager(settings)
        if not self.manager.registry.ids():
            for plugin in builtin_plugins():
                self.manager.register(plugin)

    def load_external_plugins(self, directory: Path | None = None) -> dict[str, Any]:
        return self.manager.discover_external(directory or self.settings.external_plugins_dir)

    async def reload_external_plugins(self, plugin_id: str | None = None) -> dict[str, Any]:
        return await self.manager.reload_external(plugin_id)

    async def shutdown_plugins(self) -> None:
        await self.manager.shutdown()

    async def cancel_active_plugins(self, plugin_id: str | None = None) -> int:
        return await self.manager.cancel_active(plugin_id)

    async def recover_plugin(self, plugin_id: str) -> dict[str, Any]:
        return await self.manager.recover(plugin_id)

    def external_plugins_directory(self) -> Path:
        return self.manager.external_directory()

    def schemas(self, enabled: list[str]) -> list[dict[str, Any]]:
        return self.manager.schemas(enabled)

    def match_core_intent(
        self,
        text: str,
        enabled: list[str],
    ) -> tuple[str, dict[str, Any]] | None:
        return self.manager.match_core_intent(text, enabled)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        action_id: str | None = None,
    ) -> dict[str, Any]:
        return await self.manager.execute(name, arguments, action_id=action_id)

    def format_result(
        self,
        name: str,
        result: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self.manager.format_result(name, result, metadata=metadata)

    def configure_disabled_plugins(self, plugin_ids: Iterable[str]) -> None:
        self.manager.configure_disabled(plugin_ids)

    def disabled_plugin_ids(self) -> list[str]:
        return self.manager.disabled_ids()

    def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        return self.manager.set_enabled(plugin_id, enabled)

    def reset_plugin_metrics(self, plugin_id: str | None = None) -> None:
        self.manager.reset_metrics(plugin_id)

    def plugin_health(self) -> list[dict[str, Any]]:
        return self.manager.health()

    def plugin_summary(self) -> dict[str, Any]:
        return self.manager.summary()

    def action_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.manager.action_audit(limit)

    def action_status(self, action_id: str) -> dict[str, Any] | None:
        return self.manager.action_status(action_id)


# Compatibility exports for code that imports the old module-level constants.
_COMPATIBILITY_PLUGINS = builtin_plugins()
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    plugin.id: plugin.schema for plugin in _COMPATIBILITY_PLUGINS
}

__all__ = ["ToolService", "TOOL_SCHEMAS", "WEATHER_DESCRIPTIONS"]
