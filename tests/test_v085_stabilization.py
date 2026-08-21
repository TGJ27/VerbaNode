from __future__ import annotations

import asyncio
import io
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile

from app.api.auth import websocket_origin_allowed
from app.api.client_contract import client_info_payload, feature_manifest
from app.api.uploads import read_upload_limited
from app.config import Settings
from app.db import Database
from app.http import install_http_hardening
from app.migrations import CURRENT_SCHEMA_VERSION
from app.paths import _ensure_env_file
from app.services.actions import ActionLedger
from app.services.controller import ControllerManager
from app.version import APP_VERSION, BUILD_LABEL

ROOT = Path(__file__).resolve().parents[1]


def test_v085_metadata_and_transport_contract() -> None:
    assert APP_VERSION == "0.9.2"
    assert BUILD_LABEL == "local-mobile"
    features = feature_manifest()
    assert features["websocket_heartbeat"] is True
    assert features["same_origin_websocket_guard"] is True
    assert features["security_headers"] is True
    assert features["bounded_uploads"] is True
    assert features["mobile_pairing"] is True
    assert features["lan_discovery"] is True

    info = client_info_payload()
    assert info["server"] == {"version": "0.9.2", "build": "local-mobile"}
    assert info["authentication"]["idle_timeout_seconds"] >= 30
    assert info["websocket"]["heartbeat_interval_seconds"] >= 5
    assert info["websocket"]["heartbeat_timeout_seconds"] >= 15
    assert info["websocket"]["same_origin_browser_required"] is True
    assert info["websocket"]["originless_native_clients_allowed"] is True


def test_clean_source_env_seed_generates_pin_without_overwriting_config(tmp_path: Path) -> None:
    env_example = tmp_path / ".env.example"
    env_file = tmp_path / ".env"
    env_example.write_text(
        "VERBANODE_PIN=CHANGE_ME\nVERBANODE_PORT=8123\n",
        encoding="utf-8",
    )
    _ensure_env_file(env_file, env_example)
    first = env_file.read_text(encoding="utf-8")
    pin = next(line.split("=", 1)[1] for line in first.splitlines() if line.startswith("VERBANODE_PIN="))
    assert pin.isdigit() and len(pin) == 6
    assert "VERBANODE_PORT=8123" in first

    _ensure_env_file(env_file, env_example)
    assert env_file.read_text(encoding="utf-8") == first


def test_http_security_headers_and_json_body_limit() -> None:
    app = FastAPI()
    install_http_hardening(app, max_json_body_bytes=65536)

    @app.post("/api/echo")
    async def echo() -> dict[str, bool]:
        return {"ok": True}

    client = TestClient(app)
    normal = client.post("/api/echo", json={"value": "small"})
    assert normal.status_code == 200
    assert normal.headers["X-Content-Type-Options"] == "nosniff"
    assert normal.headers["X-Frame-Options"] == "DENY"
    assert normal.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in normal.headers["Content-Security-Policy"]

    oversized = client.post(
        "/api/echo",
        content=b'"' + (b"x" * 70000) + b'"',
        headers={"Content-Type": "application/json"},
    )
    assert oversized.status_code == 413
    payload = oversized.json()
    assert payload["error"]["code"] == "request_too_large"
    assert payload["error"]["details"]["max_bytes"] == 65536


def test_bounded_upload_reader_rejects_before_unbounded_memory_read() -> None:
    upload = UploadFile(file=io.BytesIO(b"a" * 15000), filename="sample.wav")

    async def run() -> None:
        try:
            await read_upload_limited(
                upload,
                max_bytes=8192,
                too_large_message="too large",
                chunk_size=4096,
            )
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 413
            assert getattr(exc, "detail", None) == "too large"
        else:
            raise AssertionError("oversized upload was accepted")

    asyncio.run(run())


def test_websocket_origin_guard_allows_same_origin_and_native_clients() -> None:
    same = SimpleNamespace(headers={"origin": "https://192.168.1.20:8002", "host": "192.168.1.20:8002"})
    native = SimpleNamespace(headers={"host": "192.168.1.20:8002"})
    cross_site = SimpleNamespace(headers={"origin": "https://evil.example", "host": "192.168.1.20:8002"})
    assert websocket_origin_allowed(same) is True
    assert websocket_origin_allowed(native) is True
    assert websocket_origin_allowed(cross_site) is False


def test_stale_controller_session_also_invalidates_ws_tickets(monkeypatch, tmp_path: Path) -> None:
    import app.services.controller as controller_module

    clock = {"now": 100.0}
    monkeypatch.setattr(controller_module.time, "monotonic", lambda: clock["now"])
    settings = Settings(
        db_path=tmp_path / "test.db",
        pin="246810",
        controller_timeout_seconds=90,
        open_browser=False,
    )
    manager = ControllerManager(settings)
    login = manager.login("246810", "Dashboard")
    ticket = manager.create_ws_ticket(login["token"])
    assert ticket

    clock["now"] = 191.0
    assert manager.active_info() is None
    assert manager.consume_ws_ticket(ticket) is None


def test_startup_recovery_terminalizes_recent_inherited_actions(tmp_path: Path) -> None:
    ledger = ActionLedger(tmp_path / "actions.db")
    assert ledger.claim("active-1", "demo", {"value": 1}).state == "claimed"
    assert ledger.mark_running("active-1") is True

    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    assert ledger.claim(
        "active-2",
        "demo",
        {"value": 2},
        expires_at=future.isoformat(timespec="milliseconds"),
    ).state == "claimed"

    counts = ledger.recover_active_on_startup()
    assert counts == {"interrupted": 2, "expired": 0, "total": 2}
    assert ledger.get("active-1")["status"] == "interrupted"
    assert ledger.get("active-2")["status"] == "interrupted"


def test_startup_recovery_marks_inherited_past_deadline_expired(tmp_path: Path) -> None:
    ledger = ActionLedger(tmp_path / "actions.db")
    assert ledger.claim("active", "demo", {}).state == "claimed"
    assert ledger.mark_running("active") is True
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="milliseconds")
    with sqlite3.connect(tmp_path / "actions.db") as conn:
        conn.execute("UPDATE action_ledger SET expires_at=? WHERE action_id='active'", (past,))
    counts = ledger.recover_active_on_startup()
    assert counts == {"interrupted": 0, "expired": 1, "total": 1}
    assert ledger.get("active")["status"] == "expired"


def test_upgrade_path_from_numbered_v1_preserves_existing_data(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
        open_browser=False,
    )
    db = Database(settings)
    db.initialize()
    db.set_setting("v077_upgrade_marker", "preserve-me")

    with sqlite3.connect(settings.db_path) as conn:
        conn.execute("DROP TABLE IF EXISTS action_ledger")
        conn.execute("DROP TABLE IF EXISTS schema_migrations")
        conn.execute("UPDATE settings SET value='1' WHERE key='schema_version'")
        conn.execute("PRAGMA user_version=0")
        conn.execute("PRAGMA application_id=0")
        conn.commit()

    db.initialize()
    assert db.schema_version() == CURRENT_SCHEMA_VERSION
    assert db.get_setting("v077_upgrade_marker") == "preserve-me"
    with sqlite3.connect(settings.db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "action_ledger" in tables
        assert "schema_migrations" in tables


def test_dashboard_transport_and_feature_code_is_modularized() -> None:
    index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    client = (ROOT / "app/static/js/client.js").read_text(encoding="utf-8")
    expected = [
        "runtime.js",
        "client.js",
        "browser-ptt.js",
        "diagnostics.js",
        "chat.js",
        "agents.js",
        "plugins.js",
        "settings.js",
        "data-recovery.js",
        "app.js",
    ]
    positions = [index.index(f"/static/{'js/' if name != 'app.js' else ''}{name}?v=0.9.2") for name in expected]
    assert positions == sorted(positions)
    assert len(app_js.splitlines()) < 1000
    assert "function renderMessages(" not in app_js
    assert "function renderPlugins(" not in app_js
    assert "function renderSettings(" not in app_js
    assert "function openAgentModal(" not in app_js
    assert "heartbeatWatchdogTimer" in client
    assert "reconnectDelayMs" in client
    assert "2 ** Math.min(attempt, 5)" in client
    assert "initializeClientTransport" in client


def test_backup_restore_ui_surfaces_recovery_state() -> None:
    index = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    data_js = (ROOT / "app/static/js/data-recovery.js").read_text(encoding="utf-8")
    assert 'id="backupStatus"' in index
    assert 'id="restoreStatus"' in index
    assert "loadBackupStatus" in data_js
    assert "/api/backup/status" in data_js
    assert "Safety snapshot" in data_js


def test_release_verifier_is_wired_into_ci_and_windows_build() -> None:
    verifier = ROOT / "scripts/release/verify_release.py"
    workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    build = (ROOT / "build_windows.bat").read_text(encoding="utf-8")
    assert verifier.is_file()
    assert "check_version_consistency" in verifier.read_text(encoding="utf-8")
    assert "scripts/release/verify_release.py" in workflow
    assert "scripts\\release\\verify_release.py" in build
