from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.db import Database
from app.plugins import Plugin, PluginResult
from app.plugins.manager import PluginManager
from app.services.controller import ControllerManager
from app.version import APP_VERSION, BUILD_LABEL

ROOT = Path(__file__).resolve().parents[1]


class _RobotActionPlugin(Plugin):
    id = "robot_action_test"
    name = "Robot action test"
    description = "Exercises the v0.7.7 capability contract."
    permissions = ("robot",)
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Test action.",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, context):
        context.require_permission("robot")
        self.calls += 1
        return PluginResult(response="robot action completed", verified=True)


class _UndeclaredPermissionPlugin(Plugin):
    id = "undeclared_permission_test"
    name = "Undeclared permission test"
    description = "Attempts to use a capability it did not declare."
    permissions = ()
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Test permission failure.",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    async def execute(self, context):
        context.require_permission("robot")
        return PluginResult(response="should not run")


def test_controller_rate_limits_repeated_bad_pin_attempts(tmp_path: Path) -> None:
    manager = ControllerManager(
        Settings(
            db_path=tmp_path / "db.sqlite",
            pin="2468",
            open_browser=False,
            login_max_attempts=2,
            login_lockout_base_seconds=5,
            login_lockout_max_seconds=5,
        )
    )

    assert manager.login("0000", "Browser", client_key="192.0.2.10")["status"] == "invalid_pin"
    second = manager.login("0000", "Browser", client_key="192.0.2.10")
    assert second["status"] == "invalid_pin"
    assert second["retry_after_seconds"] >= 1
    limited = manager.login("2468", "Browser", client_key="192.0.2.10")
    assert limited["status"] == "rate_limited"
    assert limited["retry_after_seconds"] >= 1


def test_websocket_ticket_is_short_lived_single_use_credential(tmp_path: Path) -> None:
    manager = ControllerManager(
        Settings(db_path=tmp_path / "db.sqlite", pin="2468", open_browser=False)
    )
    session = manager.login("2468", "Browser")
    token = session["token"]

    ticket = manager.create_ws_ticket(token)
    assert ticket
    assert ticket != token
    assert manager.consume_ws_ticket(ticket) == token
    assert manager.consume_ws_ticket(ticket) is None
    assert manager.create_ws_ticket("wrong-token") is None


@pytest.mark.asyncio
async def test_plugin_action_contract_is_verified_idempotent_and_audited(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "actions.db",
        open_browser=False,
        capability_audit_path=tmp_path / "capability-actions.jsonl",
    )
    manager = PluginManager(settings)
    plugin = _RobotActionPlugin()
    manager.register(plugin)

    first = await manager.execute(plugin.id, {}, action_id="action-123")
    second = await manager.execute(plugin.id, {}, action_id="action-123")

    assert plugin.calls == 1
    assert first == second
    assert first["message"] == "robot action completed"
    assert first["_action"] == {
        "id": "action-123",
        "success": True,
        "status": "completed",
        "verified": True,
    }
    audit = manager.action_audit()
    assert len(audit) == 1
    assert audit[0]["action_id"] == "action-123"
    assert audit[0]["status"] == "completed"
    assert settings.capability_audit_path.exists()


@pytest.mark.asyncio
async def test_capability_gateway_rejects_undeclared_permission(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "actions.db",
        open_browser=False,
        capability_audit_path=tmp_path / "capability-actions.jsonl",
    )
    manager = PluginManager(settings)
    manager.register(_UndeclaredPermissionPlugin())

    result = await manager.execute("undeclared_permission_test")
    assert "undeclared permission 'robot'" in result["error"]
    assert manager.action_audit()[-1]["status"] == "failed"


def test_database_has_numbered_schema_version(tmp_path: Path) -> None:
    db = Database(Settings(db_path=tmp_path / "versioned.db", open_browser=False))
    db.initialize()
    assert db.get_setting("schema_version") == "13"


def test_v077_hardening_layout_and_ci_are_present() -> None:
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    auth = (ROOT / "app" / "api" / "auth.py").read_text(encoding="utf-8")
    javascript = "\n".join(
        (ROOT / "app" / "static" / path).read_text(encoding="utf-8")
        for path in ("app.js", "js/client.js")
    )
    workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    build_windows = (ROOT / "build_windows.bat").read_text(encoding="utf-8")
    build_installer = (ROOT / "build_installer.bat").read_text(encoding="utf-8")
    installer = (ROOT / "packaging" / "VerbaNode.iss").read_text(encoding="utf-8")
    index_html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    assert APP_VERSION == "0.11.0"
    assert BUILD_LABEL == "local-mobile"
    assert "app.include_router(auth_router)" in main
    assert '@router.post("/api/auth/ws-ticket")' in auth
    assert '@router.websocket("/ws")' in auth
    assert "/ws?ticket=" in javascript
    assert "/ws?token=" not in javascript
    assert "python -m ruff check app scripts tests" in workflow
    assert 'select = ["E9", "F601", "F811", "F821"]' in pyproject
    assert "verbanode-build" in build_windows
    assert 'findstr /B /C:"APP_VERSION =" app\\version.py' in build_windows
    assert "/DMyAppVersion=%APP_VERSION%" in build_installer
    assert "#ifndef MyAppVersion" in installer
    assert '/static/VerbaNode.png?v=0.11.0' in index_html
    assert 'styles.css?v=0.11.0' in index_html
    assert 'app.js?v=0.11.0' in index_html
    assert 'id="appVersion">v0.11.0<' in index_html
    assert 'class="brand-mark large">VN<' not in index_html
    assert 'class="brand-mark">VN<' not in index_html
    assert ".brand-mark img" in styles
    assert (ROOT / "app" / "static" / "VerbaNode.png").is_file()


def test_setup_cli_duplicate_definitions_are_removed() -> None:
    source = (ROOT / "app" / "setup_cli.py").read_text(encoding="utf-8")
    assert source.count("def _modelscope_cache_roots()") == 1
    assert source.count("def sensevoice_cache_status()") == 1
    assert source.count("if ollama_model_installed(model):") == 1
    assert source.count('"sensevoice": sensevoice_cache_status(),') == 1
    assert source.count('"ollama_models": sorted(_ollama_model_names()),') == 1
