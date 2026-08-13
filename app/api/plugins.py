from __future__ import annotations

import json
from collections import Counter
from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import Token
from app.schemas import PluginStateUpdate
from app.state import state

router = APIRouter(tags=["plugins"])


def plugin_payload() -> dict[str, Any]:
    """Return dashboard-safe metadata and runtime metrics for all plugins."""
    usage: Counter[str] = Counter()
    agents = state.db.list_agents()
    for agent in agents:
        usage.update(str(item) for item in agent.get("tools_enabled", []))

    plugins: list[dict[str, Any]] = []
    for item in state.tools.plugin_health():
        plugin = dict(item)
        plugin["agent_count"] = int(usage.get(plugin["id"], 0))
        plugin["agent_total"] = len(agents)
        plugins.append(plugin)

    summary = state.tools.plugin_summary()
    summary["agent_assignments"] = sum(usage.values())
    return {
        "sdk": "verbanode-plugins/1",
        "hardening": True,
        "external_plugins_supported": True,
        "external_plugins_directory": str(state.tools.external_plugins_directory()),
        "plugins": plugins,
        "summary": summary,
    }


def persist_plugin_state() -> None:
    payload = json.dumps(state.tools.disabled_plugin_ids(), separators=(",", ":"))
    state.db.set_setting("disabled_plugins", payload)
    state.db.set_setting("disabled_builtin_plugins", payload)


@router.get("/api/plugins")
async def list_plugins(token: Token) -> dict[str, Any]:
    return plugin_payload()


@router.put("/api/plugins/{plugin_id}")
async def update_plugin_state(
    plugin_id: str,
    payload: PluginStateUpdate,
    token: Token,
) -> dict[str, Any]:
    try:
        state.tools.set_plugin_enabled(plugin_id, payload.enabled)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Plugin not found") from exc
    persist_plugin_state()
    result = plugin_payload()
    await state.events.broadcast("plugins_changed", result)
    return result


@router.post("/api/plugins/reload")
async def reload_external_plugins(token: Token) -> dict[str, Any]:
    await state.tools.reload_external_plugins()
    result = plugin_payload()
    await state.events.broadcast("plugins_changed", result)
    return result


@router.post("/api/plugins/{plugin_id}/reload")
async def reload_external_plugin(plugin_id: str, token: Token) -> dict[str, Any]:
    try:
        await state.tools.reload_external_plugins(plugin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="External plugin not found") from exc
    result = plugin_payload()
    await state.events.broadcast("plugins_changed", result)
    return result


@router.post("/api/plugins/{plugin_id}/recover")
async def recover_plugin(plugin_id: str, token: Token) -> dict[str, Any]:
    try:
        await state.tools.recover_plugin(plugin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Plugin not found") from exc
    result = plugin_payload()
    await state.events.broadcast("plugins_changed", result)
    return result


@router.post("/api/plugins/reset-metrics")
async def reset_all_plugin_metrics(token: Token) -> dict[str, Any]:
    state.tools.reset_plugin_metrics()
    result = plugin_payload()
    await state.events.broadcast("plugins_changed", result)
    return result


@router.post("/api/plugins/{plugin_id}/reset-metrics")
async def reset_one_plugin_metrics(plugin_id: str, token: Token) -> dict[str, Any]:
    try:
        state.tools.reset_plugin_metrics(plugin_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Plugin not found") from exc
    result = plugin_payload()
    await state.events.broadcast("plugins_changed", result)
    return result


@router.get("/api/plugins/actions")
async def plugin_action_audit(token: Token, limit: int = 100) -> dict[str, Any]:
    resolved = max(1, min(int(limit), 500))
    return {"actions": state.tools.action_audit(resolved), "limit": resolved}


__all__ = ["plugin_payload", "persist_plugin_state", "router"]
