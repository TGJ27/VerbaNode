from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.config import Settings
from app.plugins.builtin.time import CurrentTimePlugin
from app.plugins.manager import PluginManager


def write_plugin(
    root: Path,
    *,
    folder: str = "sample",
    plugin_id: str = "sample_echo",
    response: str = "first",
    sdk_version: str = "1.0",
) -> Path:
    plugin_dir = root / folder
    plugin_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": plugin_id,
        "name": "Sample Echo",
        "version": "1.0.0",
        "author": "Tests",
        "description": "External test plugin",
        "entry": "plugin.py",
        "sdk_version": sdk_version,
        "permissions": [],
    }
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    (plugin_dir / "plugin.py").write_text(
        f'''from app.plugins import Plugin, PluginResult\n\nclass SamplePlugin(Plugin):\n    schema = {{"type": "function", "function": {{"name": "{plugin_id}", "description": "test", "parameters": {{"type": "object", "properties": {{}}}}}}}}\n    async def execute(self, context):\n        return PluginResult(response="{response}")\n\ndef create_plugin():\n    return SamplePlugin()\n''',
        encoding="utf-8",
    )
    return plugin_dir


@pytest.mark.asyncio
async def test_external_plugin_discovery_execution_and_reload(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugin_dir = write_plugin(plugins_dir)
    settings = Settings(db_path=tmp_path / "db.sqlite", external_plugins_path=plugins_dir)
    manager = PluginManager(settings)
    manager.register(CurrentTimePlugin())

    result = manager.discover_external(plugins_dir)
    assert result["loaded"] == 1
    assert manager.summary()["builtin"] == 1
    assert manager.summary()["external"] == 1
    health = manager.plugin_health("sample_echo")
    assert health["source"] == "external"
    assert health["reloadable"] is True
    assert (await manager.execute("sample_echo"))["message"] == "first"

    write_plugin(plugins_dir, response="second")
    await manager.reload_external("sample_echo")
    assert (await manager.execute("sample_echo"))["message"] == "second"

    shutil.rmtree(plugin_dir)
    await manager.reload_external()
    assert manager.registry.get("sample_echo") is None


@pytest.mark.asyncio
async def test_external_plugin_failure_is_isolated_and_recoverable(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    plugin_dir = write_plugin(plugins_dir, sdk_version="9.0")
    settings = Settings(db_path=tmp_path / "db.sqlite", external_plugins_path=plugins_dir)
    manager = PluginManager(settings)
    manager.register(CurrentTimePlugin())

    result = manager.discover_external(plugins_dir)
    assert result["loaded"] == 0
    assert result["failed"] == 1
    failure = next(item for item in manager.health() if item["status"] == "incompatible")
    assert failure["source"] == "external"
    assert "Unsupported SDK version" in failure["last_error"]
    assert manager.registry.get("get_current_time") is not None

    manifest_path = plugin_dir / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sdk_version"] = "1.0"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    await manager.reload_external(failure["id"])
    assert manager.registry.get("sample_echo") is not None
    assert not any(item["status"] in {"load_error", "incompatible", "invalid"} for item in manager.health())


def test_duplicate_external_id_does_not_replace_builtin(tmp_path: Path) -> None:
    plugins_dir = tmp_path / "plugins"
    write_plugin(plugins_dir, plugin_id="get_current_time")
    settings = Settings(db_path=tmp_path / "db.sqlite", external_plugins_path=plugins_dir)
    manager = PluginManager(settings)
    built_in = CurrentTimePlugin()
    manager.register(built_in)

    result = manager.discover_external(plugins_dir)
    assert result["failed"] == 1
    assert manager.registry.get("get_current_time") is built_in


def test_phase3_ui_and_endpoints_are_present() -> None:
    root = Path(__file__).resolve().parents[1]
    html = (root / "app" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    plugins_api = (root / "app" / "api" / "plugins.py").read_text(encoding="utf-8")
    assert 'id="reloadExternalPluginsBtn"' in html
    assert 'id="externalPluginDirectory"' in html
    assert "dataset.reloadPlugin" in javascript
    assert '@router.post("/api/plugins/reload")' in plugins_api
    assert '@router.post("/api/plugins/{plugin_id}/reload")' in plugins_api
    assert "app.include_router(plugins_router)" in main
