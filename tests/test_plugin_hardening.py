from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.config import Settings
from app.plugins import Plugin, PluginResult
from app.plugins.manager import PluginManager


class _FailingPlugin(Plugin):
    id = "failing_test"
    name = "Failing Test"
    description = "Always raises for hardening tests."
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Fail deliberately.",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    async def execute(self, context):
        raise RuntimeError("deliberate failure")


class _SlowPlugin(Plugin):
    id = "slow_test"
    name = "Slow Test"
    description = "Sleeps for timeout tests."
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Sleep deliberately.",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    async def execute(self, context):
        await asyncio.sleep(10)
        return PluginResult(response="late")


def _write_external(root: Path, *, response: str = "working") -> Path:
    folder = root / "stable_plugin"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "plugin.json").write_text(
        json.dumps(
            {
                "id": "stable_plugin",
                "name": "Stable Plugin",
                "version": "1.0.0",
                "author": "Tests",
                "description": "Used for safe reload tests.",
                "entry": "plugin.py",
                "sdk_version": "1.0",
                "permissions": [],
            }
        ),
        encoding="utf-8",
    )
    (folder / "plugin.py").write_text(
        f'''from app.plugins import Plugin, PluginResult\n\nclass StablePlugin(Plugin):\n    schema = {{"type": "function", "function": {{"name": "stable_plugin", "description": "Return a stable value.", "parameters": {{"type": "object", "properties": {{}}}}}}}}\n    async def execute(self, context):\n        return PluginResult(response={response!r})\n\ndef create_plugin():\n    return StablePlugin()\n''',
        encoding="utf-8",
    )
    return folder


@pytest.mark.asyncio
async def test_repeated_exceptions_mark_plugin_unhealthy() -> None:
    settings = Settings(open_browser=False, plugin_failure_threshold=2)
    manager = PluginManager(settings)
    manager.register(_FailingPlugin())

    assert "failed" in (await manager.execute("failing_test"))["error"]
    assert "failed" in (await manager.execute("failing_test"))["error"]
    health = manager.plugin_health("failing_test")
    assert health["status"] == "unhealthy"
    assert health["consecutive_failures"] == 2
    assert manager.schemas(["failing_test"]) == []
    assert "unhealthy" in (await manager.execute("failing_test"))["error"]

    recovered = await manager.recover("failing_test")
    assert recovered["status"] == "healthy"


@pytest.mark.asyncio
async def test_plugin_timeout_is_counted_and_cancellable() -> None:
    settings = Settings(open_browser=False, plugin_failure_threshold=1)
    settings.plugin_execution_timeout_seconds = 0.03
    manager = PluginManager(settings)
    manager.register(_SlowPlugin())

    result = await manager.execute("slow_test")
    assert "timed out" in result["error"]
    health = manager.plugin_health("slow_test")
    assert health["timeouts"] == 1
    assert health["status"] == "unhealthy"

    await manager.recover("slow_test")
    settings.plugin_execution_timeout_seconds = 5
    task = asyncio.create_task(manager.execute("slow_test"))
    await asyncio.sleep(0.02)
    assert await manager.cancel_active("slow_test") == 1
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_failed_reload_keeps_previous_working_plugin(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    folder = _write_external(plugin_root, response="old version")
    settings = Settings(open_browser=False, external_plugins_path=plugin_root)
    manager = PluginManager(settings)
    assert manager.discover_external(plugin_root)["loaded"] == 1
    assert (await manager.execute("stable_plugin"))["message"] == "old version"

    (folder / "plugin.py").write_text("this is not valid python !!!", encoding="utf-8")
    await manager.reload_external("stable_plugin")

    assert (await manager.execute("stable_plugin"))["message"] == "old version"
    health = manager.plugin_health("stable_plugin")
    assert health["status"] == "healthy"
    assert health["reload_errors"] == 1
    assert "Import failed" in health["last_reload_error"]


def test_invalid_permissions_and_schema_are_rejected(tmp_path: Path) -> None:
    plugin_root = tmp_path / "plugins"
    folder = _write_external(plugin_root)
    manifest_path = folder / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["permissions"] = ["superuser"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    manager = PluginManager(Settings(open_browser=False, external_plugins_path=plugin_root))
    assert manager.discover_external(plugin_root)["failed"] == 1
    failure = manager.health()[0]
    assert failure["status"] == "invalid"
    assert "Unsupported permissions" in failure["last_error"]

    manifest["permissions"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "plugin.py").write_text(
        '''from app.plugins import Plugin, PluginResult\nclass Bad(Plugin):\n    schema = {"type": "function", "function": {"name": "wrong_name", "description": "bad", "parameters": {"type": "object", "properties": {}}}}\n    async def execute(self, context):\n        return PluginResult(response="bad")\ndef create_plugin():\n    return Bad()\n''',
        encoding="utf-8",
    )
    manager = PluginManager(Settings(open_browser=False, external_plugins_path=plugin_root))
    assert manager.discover_external(plugin_root)["failed"] == 1
    failure = manager.health()[0]
    assert failure["status"] == "invalid"
    assert "function.name" in failure["last_error"]


def test_hardening_api_and_ui_are_present() -> None:
    root = Path(__file__).resolve().parents[1]
    main = (root / "app" / "main.py").read_text(encoding="utf-8")
    plugins_api = (root / "app" / "api" / "plugins.py").read_text(encoding="utf-8")
    javascript = (root / "app" / "static" / "app.js").read_text(encoding="utf-8")
    env = (root / ".env.example").read_text(encoding="utf-8")
    assert '@router.post("/api/plugins/{plugin_id}/recover")' in plugins_api
    assert "app.include_router(plugins_router)" in main
    assert "dataset.recoverPlugin" in javascript
    assert "VERBANODE_PLUGIN_FAILURE_THRESHOLD" in env
    assert "VERBANODE_PLUGIN_EXECUTION_TIMEOUT_SECONDS" in env
