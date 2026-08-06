from __future__ import annotations

import logging
from typing import Any

from app.plugins.base import Plugin

LOGGER = logging.getLogger(__name__)


class PluginRegistry:
    """Ordered registry shared by built-in and external capability plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._generation = 0

    @property
    def generation(self) -> int:
        return self._generation

    def register(self, plugin: Plugin) -> None:
        if not plugin.id:
            raise ValueError("A plugin must define a non-empty id")
        if plugin.id in self._plugins:
            raise ValueError(f"Plugin '{plugin.id}' is already registered")
        self._plugins[plugin.id] = plugin
        self._generation += 1
        LOGGER.info(
            "Registered %s plugin: %s v%s",
            plugin.source,
            plugin.id,
            plugin.version,
        )

    def replace(self, plugin: Plugin) -> Plugin | None:
        previous = self._plugins.get(plugin.id)
        self._plugins[plugin.id] = plugin
        self._generation += 1
        LOGGER.info(
            "%s plugin: %s v%s",
            "Replaced" if previous is not None else "Registered",
            plugin.id,
            plugin.version,
        )
        return previous

    def unregister(self, plugin_id: str) -> Plugin | None:
        plugin = self._plugins.pop(plugin_id, None)
        if plugin is not None:
            self._generation += 1
            LOGGER.info("Unregistered %s plugin: %s", plugin.source, plugin_id)
        return plugin

    def get(self, plugin_id: str) -> Plugin | None:
        return self._plugins.get(plugin_id)

    def list(self) -> list[Plugin]:
        return sorted(self._plugins.values(), key=lambda item: (item.priority, item.id))

    def ids(self) -> list[str]:
        return [plugin.id for plugin in self.list()]

    def raw_schemas(self) -> list[dict[str, Any]]:
        return [plugin.schema for plugin in self.list() if plugin.schema]
