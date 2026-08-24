from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.auth as auth_api
from app.http import install_http_hardening


class _FakeEvents:
    def __init__(self, *, connected_after_drop: bool) -> None:
        self.connected_after_drop = connected_after_drop
        self.disconnects: list[tuple[str, object]] = []

    async def disconnect(self, token: str, websocket: object) -> None:
        self.disconnects.append((token, websocket))

    async def is_connected(self, token: str) -> bool:
        return self.connected_after_drop


class _FakeConversation:
    def __init__(self) -> None:
        self.mode = "ptt"
        self.cancel_calls = 0

    async def cancel_ptt(self) -> None:
        self.cancel_calls += 1
        self.mode = "idle"


@pytest.mark.asyncio
async def test_dropped_controller_socket_cancels_host_ptt_even_while_session_remains_valid(monkeypatch) -> None:
    events = _FakeEvents(connected_after_drop=False)
    conversation = _FakeConversation()
    # Deliberately expose a controller that would still validate the token. The
    # v0.9.6 bug used session validity here and therefore left the mic recording.
    controller = SimpleNamespace(validate=lambda *_args, **_kwargs: True)
    monkeypatch.setattr(auth_api, "state", SimpleNamespace(events=events, conversation=conversation, controller=controller))

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(auth_api.asyncio, "sleep", no_wait)
    websocket = object()
    await auth_api._cleanup_disconnected_host_ptt("controller-token", websocket)

    assert events.disconnects == [("controller-token", websocket)]
    assert conversation.cancel_calls == 1
    assert conversation.mode == "idle"


@pytest.mark.asyncio
async def test_fast_same_token_reconnect_keeps_host_ptt_active(monkeypatch) -> None:
    events = _FakeEvents(connected_after_drop=True)
    conversation = _FakeConversation()
    monkeypatch.setattr(auth_api, "state", SimpleNamespace(events=events, conversation=conversation))

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(auth_api.asyncio, "sleep", no_wait)
    await auth_api._cleanup_disconnected_host_ptt("controller-token", object())

    assert conversation.cancel_calls == 0
    assert conversation.mode == "ptt"


def test_unhandled_http_exception_returns_request_id_without_leaking_details() -> None:
    app = FastAPI()
    install_http_hardening(app)

    @app.get("/api/boom")
    async def boom() -> None:
        raise RuntimeError("database-password-should-not-leak")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/boom", headers={"X-Request-ID": "phase1-request"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "phase1-request"
    payload = response.json()
    assert payload["detail"] == "Internal server error"
    assert payload["error"] == {
        "code": "internal_server_error",
        "message": "Internal server error",
        "request_id": "phase1-request",
    }
    assert "database-password" not in response.text
