from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.schemas import PluginStateUpdate
from app.services.tools import ToolService
from app.version import APP_VERSION, BUILD_LABEL

ROOT = Path(__file__).resolve().parents[1]


def test_plugin_manager_can_disable_and_restore_a_capability() -> None:
    service = ToolService(Settings(open_browser=False))
    all_ids = service.manager.registry.ids()

    disabled = service.set_plugin_enabled("get_current_time", False)
    assert disabled["enabled"] is False
    assert disabled["status"] == "disabled"
    assert service.match_core_intent("what time is it?", all_ids) is None
    assert "get_current_time" not in {
        item["function"]["name"] for item in service.schemas(all_ids)
    }

    enabled = service.set_plugin_enabled("get_current_time", True)
    assert enabled["enabled"] is True
    assert service.match_core_intent("what time is it?", all_ids) == (
        "get_current_time",
        {},
    )


@pytest.mark.asyncio
async def test_disabled_plugin_cannot_execute_and_metrics_can_reset() -> None:
    service = ToolService(Settings(open_browser=False))
    service.set_plugin_enabled("get_location", False)
    assert await service.execute("get_location") == {
        "error": "Tool 'get_location' is disabled"
    }

    service.set_plugin_enabled("get_location", True)
    await service.execute("get_location")
    health = {item["id"]: item for item in service.plugin_health()}
    assert health["get_location"]["executions"] == 1

    service.reset_plugin_metrics("get_location")
    health = {item["id"]: item for item in service.plugin_health()}
    assert health["get_location"]["executions"] == 0
    assert health["get_location"]["errors"] == 0


def test_disabled_plugin_ids_persist_in_existing_settings_table(tmp_path: Path) -> None:
    db = Database(Settings(db_path=tmp_path / "plugin-state.db", open_browser=False))
    db.initialize()
    disabled = ["get_weather", "handle_exit_intent"]
    db.set_setting("disabled_builtin_plugins", json.dumps(disabled))
    assert json.loads(db.get_setting("disabled_builtin_plugins", "[]") or "[]") == disabled


def test_plugin_state_schema_and_metadata() -> None:
    assert PluginStateUpdate(enabled=False).enabled is False
    service = ToolService(Settings(open_browser=False))
    weather = {item["id"]: item for item in service.plugin_health()}["get_weather"]
    assert weather["category"] == "Online information"
    assert weather["permissions"] == ["internet"]
    assert weather["author"] == "Sari Technology Global"


def test_plugin_manager_dashboard_and_api_are_present() -> None:
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert 'data-page="plugins"' in html
    assert 'id="page-plugins"' in html
    assert 'id="pluginGrid"' in html
    assert "function renderPlugins" in javascript
    assert "/api/plugins/reset-metrics" in javascript
    assert ".plugin-grid" in css
    assert '.get("/api/plugins")' in main
    assert '.put("/api/plugins/{plugin_id}")' in main
    assert '"plugin_manager": True' in main
    assert APP_VERSION == "0.7.2"
    assert BUILD_LABEL == "bilingual-hardening-beta"
