from __future__ import annotations

import pytest

from app.config import Settings
from app.plugins.builtin import builtin_plugins
from app.plugins.manager import PluginManager
from app.services.tools import ToolService


def test_builtin_capabilities_are_registered_independently() -> None:
    manager = PluginManager(Settings(open_browser=False))
    for plugin in builtin_plugins():
        manager.register(plugin)

    assert manager.registry.ids() == [
        "get_current_time",
        "get_location",
        "get_weather",
        "handle_exit_intent",
    ]
    assert all(plugin.schema for plugin in manager.registry.list())


def test_tool_service_remains_backwards_compatible() -> None:
    service = ToolService(Settings(open_browser=False))
    enabled = service.manager.registry.ids()

    assert service.match_core_intent("Hello Ropi, what time is it?", enabled) == (
        "get_current_time",
        {},
    )
    assert service.match_core_intent("What is time complexity?", enabled) is None
    assert {item["function"]["name"] for item in service.schemas(enabled)} == set(enabled)


@pytest.mark.asyncio
async def test_plugin_execution_and_metrics() -> None:
    service = ToolService(
        Settings(open_browser=False, default_timezone="Asia/Jakarta")
    )
    result = await service.execute("get_current_time")

    assert result["timezone"] == "Asia/Jakarta"
    health = {item["id"]: item for item in service.plugin_health()}
    assert health["get_current_time"]["executions"] == 1
    assert health["get_current_time"]["errors"] == 0
    assert health["get_current_time"]["last_latency_ms"] >= 0


@pytest.mark.asyncio
async def test_unknown_plugin_preserves_old_error_contract() -> None:
    service = ToolService(Settings(open_browser=False))
    assert await service.execute("missing_plugin") == {
        "error": "Unknown tool: missing_plugin"
    }
