from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

import pytest

from app.capabilities import (
    CapabilityDescriptor,
    CapabilityPermissionError,
    CapabilityProvider,
    CapabilityRegistrationError,
    CapabilityResult,
    CapabilityService,
)
from app.config import Settings
from app.db import Database
from app.plugins import Plugin, PluginResult
from app.plugins.manager import PluginManager
from app.version import APP_VERSION, BUILD_LABEL

ROOT = Path(__file__).resolve().parents[1]


class _RobotProvider(CapabilityProvider):
    id = "test_robot"
    name = "Test Robot"
    capabilities = (
        CapabilityDescriptor(
            "robot.navigate",
            "robot",
            "Navigate to a named target.",
            destructive=True,
        ),
    )
    max_concurrency = 1
    default_timeout_seconds = 0.5

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay
        self.calls = 0
        self.cancel_calls = 0
        self.active = 0
        self.max_active = 0

    async def execute(self, request):
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            if self.delay:
                await asyncio.sleep(self.delay)
            return CapabilityResult(
                operation_id=request.operation_id,
                capability=request.capability,
                provider_id=self.id,
                data={"target": request.arguments.get("target")},
                verified=True,
            )
        finally:
            self.active -= 1

    async def cancel(self, operation_id: str) -> bool:
        self.cancel_calls += 1
        return True


class _BadPermissionProvider(CapabilityProvider):
    id = "bad_permission"
    capabilities = (CapabilityDescriptor("robot.navigate", "network"),)

    async def execute(self, request):  # pragma: no cover - registration must fail first
        raise AssertionError("should not execute")


class _GatewayPlugin(Plugin):
    id = "v082_gateway_plugin"
    name = "v0.8.2 gateway plugin"
    description = "Exercises provider-backed capability execution."
    permissions = ("robot",)
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Navigate through a capability provider.",
            "parameters": {
                "type": "object",
                "properties": {"target": {"type": "string"}},
            },
        },
    }

    async def execute(self, context):
        result = await context.gateway.invoke(
            "robot.navigate",
            {"target": context.arguments.get("target")},
            expires_in_seconds=2,
        )
        return PluginResult(
            data=result.as_dict(),
            success=result.success,
            status=result.status,
            verified=result.verified,
            error_code=result.error_code,
        )


class _SlowPlugin(Plugin):
    id = "v082_slow_plugin"
    name = "v0.8.2 slow plugin"
    description = "Exercises top-level action expiry."
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Wait.",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    async def execute(self, context):
        await asyncio.sleep(0.2)
        return PluginResult(response="done")


def _settings(tmp_path: Path, **overrides) -> Settings:
    return Settings(
        db_path=tmp_path / "verbanode.db",
        open_browser=False,
        capability_audit_path=tmp_path / "capability-actions.jsonl",
        capability_execution_timeout_seconds=0.5,
        capability_max_concurrent_executions=4,
        capability_provider_max_concurrent_executions=1,
        capability_default_ttl_seconds=2,
        capability_max_ttl_seconds=30,
        **overrides,
    )


def test_v082_capability_expiry_survives_current_schema(tmp_path: Path) -> None:
    assert APP_VERSION == "0.9.2"
    assert BUILD_LABEL == "local-mobile"

    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()
    assert db.get_setting("schema_version") == "8"
    with sqlite3.connect(settings.db_path) as conn:
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(action_ledger)").fetchall()
        }
    assert "expires_at" in columns


def test_provider_registration_enforces_namespace_permission(tmp_path: Path) -> None:
    service = CapabilityService(_settings(tmp_path))
    with pytest.raises(CapabilityRegistrationError, match="must use permission 'robot'"):
        service.register(_BadPermissionProvider())


@pytest.mark.asyncio
async def test_gateway_requires_declared_permission_and_routes_provider(tmp_path: Path) -> None:
    service = CapabilityService(_settings(tmp_path))
    provider = _RobotProvider()
    service.register(provider)

    with pytest.raises(CapabilityPermissionError):
        await service.invoke(
            plugin_id="no_robot_permission",
            permissions=frozenset(),
            capability="robot.navigate",
            arguments={"target": "lobby"},
        )

    result = await service.invoke(
        plugin_id="robot_plugin",
        permissions=frozenset({"robot"}),
        capability="robot.navigate",
        arguments={"target": "lobby"},
    )
    assert result.success is True
    assert result.verified is True
    assert result.data == {"target": "lobby"}
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_provider_execution_is_bounded_per_provider(tmp_path: Path) -> None:
    service = CapabilityService(_settings(tmp_path))
    provider = _RobotProvider(delay=0.04)
    service.register(provider)

    await asyncio.gather(
        *[
            service.invoke(
                plugin_id=f"plugin_{index}",
                permissions=frozenset({"robot"}),
                capability="robot.navigate",
                arguments={"target": str(index)},
            )
            for index in range(3)
        ]
    )
    assert provider.calls == 3
    assert provider.max_active == 1


@pytest.mark.asyncio
async def test_provider_request_expires_and_calls_cancel_hook(tmp_path: Path) -> None:
    service = CapabilityService(_settings(tmp_path))
    provider = _RobotProvider(delay=0.2)
    service.register(provider)

    result = await service.invoke(
        plugin_id="robot_plugin",
        permissions=frozenset({"robot"}),
        capability="robot.navigate",
        arguments={"target": "kitchen"},
        expires_in_seconds=0.03,
    )
    assert result.success is False
    assert result.status == "expired"
    assert result.error_code == "capability_expired"
    assert provider.cancel_calls >= 1


@pytest.mark.asyncio
async def test_plugin_gateway_uses_registered_provider(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Database(settings).initialize()
    manager = PluginManager(settings)
    provider = _RobotProvider()
    manager.register_capability_provider(provider)
    plugin = _GatewayPlugin()
    manager.register(plugin)

    result = await manager.execute(
        plugin.id,
        {"target": "charging_station"},
        action_id="v082-provider-action",
    )
    assert result["_action"]["status"] == "completed"
    assert result["_capability"]["provider_id"] == provider.id
    assert result["target"] == "charging_station"


@pytest.mark.asyncio
async def test_top_level_action_expiry_is_persisted(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Database(settings).initialize()
    manager = PluginManager(settings)
    plugin = _SlowPlugin()
    manager.register(plugin)

    result = await manager.execute(
        plugin.id,
        {},
        action_id="v082-expiring-action",
        expires_in_seconds=0.03,
    )
    assert result["_action"]["status"] == "expired"
    stored = manager.action_status("v082-expiring-action")
    assert stored is not None
    assert stored["status"] == "expired"
    assert stored["expires_at"]


@pytest.mark.asyncio
async def test_cancel_action_propagates_to_active_provider(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Database(settings).initialize()
    manager = PluginManager(settings)
    provider = _RobotProvider(delay=5)
    manager.register_capability_provider(provider)
    plugin = _GatewayPlugin()
    manager.register(plugin)

    task = asyncio.create_task(
        manager.execute(
            plugin.id,
            {"target": "garage"},
            action_id="v082-cancel-action",
        )
    )
    for _ in range(100):
        if manager.capability_status()["active_operations"]:
            break
        await asyncio.sleep(0.005)
    else:
        pytest.fail("provider operation did not become active")

    stored = await manager.cancel_action("v082-cancel-action")
    await asyncio.gather(task, return_exceptions=True)
    assert stored is not None
    assert stored["status"] == "cancelled"
    assert provider.cancel_calls >= 1
    assert manager.capability_status()["active_operations"] == []


def test_capability_api_and_deferred_mobile_scope_are_explicit() -> None:
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    capability_api = (ROOT / "app" / "api" / "capabilities.py").read_text(encoding="utf-8")
    actions_api = (ROOT / "app" / "api" / "actions.py").read_text(encoding="utf-8")
    system_api = (ROOT / "app" / "api" / "system.py").read_text(encoding="utf-8")
    client_contract = (ROOT / "app" / "api" / "client_contract.py").read_text(encoding="utf-8")

    assert "app.include_router(capabilities_router)" in main
    assert '@router.get("/api/capabilities")' in capability_api
    assert 'actions/{operation_id}/cancel' in capability_api
    assert '@router.post("/api/actions/{action_id}/cancel")' in actions_api
    assert '"capability_provider_framework": True' in client_contract
    assert '"capability_action_expiry": True' in client_contract
    assert '"capability_cancellation": True' in client_contract
    assert '"mobile_pairing": True' in client_contract
    assert '"lan_discovery": True' in client_contract
