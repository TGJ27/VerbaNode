from __future__ import annotations

import logging
from collections.abc import Iterable
from typing import Any

from app.plugins.base import Plugin
from app.plugins.context import PluginContext

LOGGER = logging.getLogger(__name__)


class PluginRegistry:
    """Ordered registry shared by built-in and external capability plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}

    def register(self, plugin: Plugin) -> None:
        if not plugin.id:
            raise ValueError("A plugin must define a non-empty id")
        if plugin.id in self._plugins:
            raise ValueError(f"Plugin '{plugin.id}' is already registered")
        self._plugins[plugin.id] = plugin
        LOGGER.info(
            "Registered %s plugin: %s v%s",
            plugin.source,
            plugin.id,
            plugin.version,
        )

    def replace(self, plugin: Plugin) -> Plugin | None:
        previous = self._plugins.get(plugin.id)
        self._plugins[plugin.id] = plugin
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
            LOGGER.info("Unregistered %s plugin: %s", plugin.source, plugin_id)
        return plugin

    def get(self, plugin_id: str) -> Plugin | None:
        return self._plugins.get(plugin_id)

    def list(self) -> list[Plugin]:
        return sorted(self._plugins.values(), key=lambda item: (item.priority, item.id))

    def ids(self) -> list[str]:
        return [plugin.id for plugin in self.list()]

    def schemas(self, enabled: Iterable[str]) -> list[dict[str, Any]]:
        enabled_set = set(enabled or [])
        return [
            plugin.schema
            for plugin in self.list()
            if plugin.enabled and plugin.id in enabled_set and plugin.schema
        ]

    def resolve(
        self,
        text: str,
        enabled: Iterable[str],
        base_context: PluginContext,
    ) -> tuple[Plugin, dict[str, Any]] | None:
        enabled_set = set(enabled or [])
        for plugin in self.list():
            if not plugin.enabled or plugin.id not in enabled_set:
                continue
            context = PluginContext(
                settings=base_context.settings,
                text=text,
                metadata=dict(base_context.metadata),
            )
            arguments = plugin.match(context)
            if arguments is not None:
                return plugin, arguments
        return None
