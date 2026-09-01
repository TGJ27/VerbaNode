from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import Database
from app.http import install_http_hardening
from app.plugins import Plugin, PluginResult
from app.plugins.manager import PluginManager
from app.version import APP_VERSION, BUILD_LABEL

ROOT = Path(__file__).resolve().parents[1]


class _ImmediatePlugin(Plugin):
    id = "v081_immediate"
    name = "v0.8.2 immediate action"
    description = "Exercises same-loop action leader reservation."
    permissions = ("robot",)
    schema = {
        "type": "function",
        "function": {
            "name": id,
            "description": "Immediate concurrency test.",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, context):
        context.require_permission("robot")
        self.calls += 1
        await asyncio.sleep(0)
        return PluginResult(response="ok", verified=True)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "verbanode.db",
        open_browser=False,
        capability_audit_path=tmp_path / "capability-actions.jsonl",
    )


def test_v081_metadata_and_router_split() -> None:
    assert APP_VERSION == "0.12.1"
    assert BUILD_LABEL == "local-mobile"

    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert len(main.splitlines()) < 180
    for router_name in (
        "system_router",
        "diagnostics_router",
        "audio_router",
        "ai_router",
        "tts_router",
    ):
        assert f"app.include_router({router_name})" in main

    assert '"/api/diagnostics"' not in main
    assert '"/api/audio/devices"' not in main
    assert '"/api/ai/restart-engine"' not in main
    assert '"/api/tts/edge-voices"' not in main


def test_legacy_takeover_approval_flow_is_removed() -> None:
    auth = (ROOT / "app" / "api" / "auth.py").read_text(encoding="utf-8")
    controller = (ROOT / "app" / "services" / "controller.py").read_text(encoding="utf-8")
    schemas = (ROOT / "app" / "schemas.py").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    client_js = (ROOT / "app" / "static" / "js" / "client.js").read_text(encoding="utf-8")

    combined = "\n".join((auth, controller, schemas, javascript, client_js))
    assert "/api/auth/takeover" not in combined
    assert "takeover_request" not in combined
    assert "TakeoverRequest" not in combined
    assert "TakeoverResponse" not in combined
    assert "force_takeover" not in combined
    # Valid PIN control transfer is intentionally retained as the one policy.
    assert '"takeover": old_token is not None' in controller
    assert '"automatic_takeover"' in auth


def test_request_ids_and_structured_http_errors() -> None:
    app = FastAPI()
    install_http_hardening(app)

    @app.get("/boom")
    async def boom() -> None:
        raise HTTPException(status_code=409, detail="conflict")

    client = TestClient(app)
    response = client.get("/boom", headers={"X-Request-ID": "test-request-081"})
    assert response.status_code == 409
    assert response.headers["X-Request-ID"] == "test-request-081"
    payload = response.json()
    assert payload["detail"] == "conflict"
    assert payload["error"] == {
        "code": "http_409",
        "message": "conflict",
        "request_id": "test-request-081",
    }


def test_validation_errors_use_same_error_envelope() -> None:
    app = FastAPI()
    install_http_hardening(app)

    @app.get("/number")
    async def number(value: int) -> dict[str, int]:
        return {"value": value}

    client = TestClient(app)
    response = client.get("/number?value=nope")
    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"] == "Request validation failed"
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["request_id"] == response.headers["X-Request-ID"]
    assert payload["error"]["details"]


@pytest.mark.asyncio
async def test_many_same_loop_duplicates_share_one_execution(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    Database(settings).initialize()
    manager = PluginManager(settings)
    plugin = _ImmediatePlugin()
    manager.register(plugin)

    results = await asyncio.gather(
        *[
            manager.execute(plugin.id, {}, action_id="v081-one-leader")
            for _ in range(20)
        ]
    )

    assert plugin.calls == 1
    assert all(result == results[0] for result in results)
    assert results[0]["_action"]["status"] == "completed"


def test_dashboard_diagnostics_is_split_into_a_separate_script() -> None:
    index = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    diagnostics_js = (ROOT / "app" / "static" / "js" / "diagnostics.js").read_text(
        encoding="utf-8"
    )

    diagnostics_tag = '/static/js/diagnostics.js?v=0.12.1'
    app_tag = '/static/app.js?v=0.12.1'
    assert diagnostics_tag in index
    assert index.index(diagnostics_tag) < index.index(app_tag)
    assert "function renderDiagnostics(" not in app_js
    assert "function renderDiagnostics(" in diagnostics_js
    assert len(app_js.splitlines()) < 2300


def test_frontend_understands_structured_api_error_metadata() -> None:
    javascript = (ROOT / "app" / "static" / "js" / "client.js").read_text(encoding="utf-8")
    assert "payload.error?.message" in javascript
    assert "error.requestId" in javascript
    assert "error.code" in javascript
