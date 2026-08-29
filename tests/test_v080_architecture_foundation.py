from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.migrations import CURRENT_SCHEMA_VERSION
from app.api.protocol import PROTOCOL_VERSION, event_envelope, parse_command
from app.config import Settings
from app.db import Database
from app.plugins import Plugin, PluginResult
from app.plugins.manager import PluginManager
from app.version import APP_VERSION, BUILD_LABEL

ROOT = Path(__file__).resolve().parents[1]


class _SlowActionPlugin(Plugin):
    id = "v080_slow_action"
    name = "v0.8 slow action"
    description = "Exercises persistent and concurrent action idempotency."
    permissions = ("robot",)
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Test action ledger.",
            "parameters": {
                "type": "object",
                "properties": {"target": {"type": "string"}},
            },
        },
    }

    def __init__(self, delay: float = 0.0) -> None:
        self.calls = 0
        self.delay = delay

    async def execute(self, context):
        context.require_permission("robot")
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return PluginResult(
            response=f"moved:{context.arguments.get('target', '')}",
            verified=True,
        )


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "verbanode.db",
        open_browser=False,
        capability_audit_path=tmp_path / "capability-actions.jsonl",
    )


def test_v080_metadata_and_schema_migration(tmp_path: Path) -> None:
    assert APP_VERSION == "0.12.0"
    assert BUILD_LABEL == "local-mobile"

    db = Database(_settings(tmp_path))
    db.initialize()
    assert db.get_setting("schema_version") == str(CURRENT_SCHEMA_VERSION)
    with sqlite3.connect(tmp_path / "verbanode.db") as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "action_ledger" in tables


@pytest.mark.asyncio
async def test_action_id_replays_after_manager_restart(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Database(settings).initialize()

    first_manager = PluginManager(settings)
    first_plugin = _SlowActionPlugin()
    first_manager.register(first_plugin)
    first = await first_manager.execute(
        first_plugin.id,
        {"target": "lobby"},
        action_id="action-persistent-1",
    )
    assert first_plugin.calls == 1

    second_manager = PluginManager(settings)
    second_plugin = _SlowActionPlugin()
    second_manager.register(second_plugin)
    replay = await second_manager.execute(
        second_plugin.id,
        {"target": "lobby"},
        action_id="action-persistent-1",
    )

    assert second_plugin.calls == 0
    assert replay == first
    stored = second_manager.action_status("action-persistent-1")
    assert stored is not None
    assert stored["status"] == "completed"
    assert stored["verified"] is True


@pytest.mark.asyncio
async def test_concurrent_duplicate_action_executes_only_once(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Database(settings).initialize()
    manager = PluginManager(settings)
    plugin = _SlowActionPlugin(delay=0.08)
    manager.register(plugin)

    first, second = await asyncio.gather(
        manager.execute(plugin.id, {"target": "kitchen"}, action_id="action-concurrent-1"),
        manager.execute(plugin.id, {"target": "kitchen"}, action_id="action-concurrent-1"),
    )

    assert plugin.calls == 1
    assert first == second
    assert first["_action"]["status"] == "completed"


@pytest.mark.asyncio
async def test_reusing_action_id_for_different_payload_is_rejected(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Database(settings).initialize()
    manager = PluginManager(settings)
    plugin = _SlowActionPlugin()
    manager.register(plugin)

    await manager.execute(plugin.id, {"target": "kitchen"}, action_id="bound-action")
    conflict = await manager.execute(plugin.id, {"target": "garage"}, action_id="bound-action")

    assert plugin.calls == 1
    assert conflict["_action"]["status"] == "conflict"
    assert "different plugin or argument payload" in conflict["error"]


def test_websocket_protocol_v1_is_versioned_and_legacy_compatible() -> None:
    event = event_envelope("agents_changed", {"count": 2}, request_id="req-1")
    assert event["protocol"] == PROTOCOL_VERSION == 1
    assert event["type"] == "agents_changed"
    assert event["event"] == "agents_changed"
    assert event["request_id"] == "req-1"

    command, data, request_id = parse_command(
        {
            "protocol": 1,
            "type": "command.ptt_start",
            "request_id": "req-2",
            "data": {"source": "mobile"},
        }
    )
    assert (command, data, request_id) == ("ptt_start", {"source": "mobile"}, "req-2")

    legacy_command, legacy_data, _ = parse_command({"command": "heartbeat", "client": "web"})
    assert legacy_command == "heartbeat"
    assert legacy_data == {"client": "web"}


def test_main_is_router_oriented_and_mobile_ready_protocol_is_present() -> None:
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    auth = (ROOT / "app" / "api" / "auth.py").read_text(encoding="utf-8")
    system_api = (ROOT / "app" / "api" / "system.py").read_text(encoding="utf-8")
    client_contract = (ROOT / "app" / "api" / "client_contract.py").read_text(encoding="utf-8")
    javascript = "\n".join(
        (ROOT / "app" / "static" / path).read_text(encoding="utf-8")
        for path in ("app.js", "js/client.js")
    )

    for router_name in (
        "actions_router",
        "agents_router",
        "backup_router",
        "conversations_router",
        "information_router",
        "models_router",
        "plugins_router",
        "scripts_router",
    ):
        assert f"app.include_router({router_name})" in main

    assert '@app.get("/api/agents")' not in main
    assert '@app.get("/api/plugins")' not in main
    assert '@app.get("/api/backup")' not in main
    assert '"websocket_protocol_version": PROTOCOL_VERSION' in client_contract
    assert '"persistent_action_ledger": True' in client_contract
    assert '"mobile_pairing": True' in client_contract
    assert '"lan_discovery": True' in client_contract
    assert "parse_command(payload)" in auth
    assert "protocol: WEBSOCKET_PROTOCOL_VERSION" in javascript
    assert "type: `command.${command}`" in javascript


def test_backup_router_streams_restore_through_validated_backup_service() -> None:
    api_source = (ROOT / "app" / "api" / "backup.py").read_text(encoding="utf-8")
    service_source = (ROOT / "app" / "services" / "backup.py").read_text(encoding="utf-8")
    assert "MAX_BACKUP_UPLOAD_BYTES" in api_source
    assert "await file.read(1024 * 1024)" in api_source
    assert "validate_backup_archive" in api_source
    assert "state.db.restore_from" in api_source
    assert "BACKUP_FORMAT_VERSION = 3" in service_source
    assert '"sha256"' in service_source
    assert '"product": "VerbaNode"' in service_source
