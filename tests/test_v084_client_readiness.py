from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.client_contract import client_info_payload, feature_manifest
from app.api.protocol import API_VERSION, MIN_API_VERSION, PROTOCOL_VERSION
from app.config import Settings
from app.http import install_http_hardening
from app.schemas import LoginRequest
from app.services.controller import ControllerManager
from app.version import APP_VERSION, BUILD_LABEL

ROOT = Path(__file__).resolve().parents[1]


def test_v084_metadata_and_public_client_contract() -> None:
    assert APP_VERSION == "0.8.4"
    assert BUILD_LABEL == "client-readiness"
    assert API_VERSION == 1
    assert MIN_API_VERSION == 1
    assert PROTOCOL_VERSION == 1

    payload = client_info_payload()
    assert payload["contract_version"] == 1
    assert payload["product"] == "VerbaNode"
    assert payload["server"] == {"version": "0.8.4", "build": "client-readiness"}
    assert payload["api"]["version"] == 1
    assert payload["authentication"]["mode"] == "pin_session"
    assert payload["authentication"]["session_header"] == "X-Session-Token"
    assert payload["authentication"]["controller_policy"] == "single_active_controller"
    assert payload["websocket"]["protocol_version"] == 1
    assert payload["websocket"]["ticket_required"] is True
    assert payload["endpoints"]["session"] == "/api/session"

    features = feature_manifest()
    assert features["client_metadata"] is True
    assert features["modular_web_client"] is True
    assert features["mobile_pairing"] is False
    assert features["lan_discovery"] is False


def test_controller_session_carries_non_secret_client_metadata(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "test.db", pin="2468", open_browser=False)
    manager = ControllerManager(settings)

    login = manager.login(
        "2468",
        "Dashboard",
        client_type="web",
        client_version="0.8.4",
        api_version=1,
    )
    assert login["status"] == "granted"
    assert login["session_id"]

    active = manager.active_info()
    assert active is not None
    assert active["session_id"] == login["session_id"]
    assert active["client_name"] == "Dashboard"
    assert active["client_type"] == "web"
    assert active["client_version"] == "0.8.4"
    assert active["api_version"] == 1
    assert "token" not in active


def test_login_request_remains_legacy_compatible_and_accepts_client_metadata() -> None:
    legacy = LoginRequest(pin="1234")
    assert legacy.client_name == "Browser"
    assert legacy.client_type == "unknown"
    assert legacy.client_version is None
    assert legacy.api_version is None

    modern = LoginRequest(
        pin="1234",
        client_name="Web Dashboard",
        client_type="web",
        client_version="0.8.4",
        api_version=1,
    )
    assert modern.client_type == "web"
    assert modern.client_version == "0.8.4"
    assert modern.api_version == 1


def test_api_responses_expose_client_compatibility_headers() -> None:
    app = FastAPI()
    install_http_hardening(app)

    @app.get("/api/example")
    async def api_example() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/plain")
    async def plain() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    response = client.get("/api/example")
    assert response.status_code == 200
    assert response.headers["X-VerbaNode-Version"] == "0.8.4"
    assert response.headers["X-VerbaNode-API-Version"] == "1"
    assert response.headers["X-VerbaNode-WebSocket-Protocol"] == "1"
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["X-Request-ID"]

    plain_response = client.get("/plain")
    assert "X-VerbaNode-Version" not in plain_response.headers


def test_client_readiness_endpoints_and_protocol_guard_are_present() -> None:
    system_api = (ROOT / "app" / "api" / "system.py").read_text(encoding="utf-8")
    auth_api = (ROOT / "app" / "api" / "auth.py").read_text(encoding="utf-8")

    assert '@router.get("/api/client-info")' in system_api
    assert '@router.get("/api/session")' in auth_api
    assert 'code="incompatible_api_version"' in auth_api
    assert 'websocket.close(code=4406)' in auth_api
    assert '"protocol_error"' in auth_api
    assert "client_type=payload.client_type" in auth_api
    assert "client_version=payload.client_version" in auth_api
    assert "api_version=payload.api_version" in auth_api


def test_dashboard_is_split_into_ordered_client_modules() -> None:
    index = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    runtime = (ROOT / "app" / "static" / "js" / "runtime.js").read_text(encoding="utf-8")
    client = (ROOT / "app" / "static" / "js" / "client.js").read_text(encoding="utf-8")
    browser_ptt = (ROOT / "app" / "static" / "js" / "browser-ptt.js").read_text(encoding="utf-8")
    app_js = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")

    tags = [
        '/static/js/runtime.js?v=0.8.4',
        '/static/js/client.js?v=0.8.4',
        '/static/js/browser-ptt.js?v=0.8.4',
        '/static/js/diagnostics.js?v=0.8.4',
        '/static/app.js?v=0.8.4',
    ]
    positions = [index.index(tag) for tag in tags]
    assert positions == sorted(positions)

    assert "const FRONTEND_VERSION = '0.8.4'" in runtime
    assert "const CLIENT_API_VERSION = 1" in runtime
    assert "const WEBSOCKET_PROTOCOL_VERSION = 1" in runtime
    assert "async function api(" in client
    assert "function connectWebSocket(" in client
    assert "function wsCommand(" in client
    assert "client_type: 'web'" in client
    assert "api_version: CLIENT_API_VERSION" in client
    assert "let payload = null" in client
    assert "function startBrowserPttCapture(" in browser_ptt
    assert "function stopBrowserPttCapture(" in browser_ptt
    assert "async function api(" not in app_js
    assert "function connectWebSocket(" not in app_js
    assert "function startBrowserPttCapture(" not in app_js
    assert len(app_js.splitlines()) < 1800
