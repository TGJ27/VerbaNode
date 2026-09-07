from __future__ import annotations

from app.api.client_contract import MOBILE_CONTRACT_VERSION, client_info_payload, mobile_contract_manifest
from app.main import app
from app.schemas import DeviceLoginRequest, LoginRequest, PairingClaimRequest, PairingStartRequest


def test_mobile_contract_manifest_is_versioned_and_routes_exist() -> None:
    manifest = mobile_contract_manifest()
    assert MOBILE_CONTRACT_VERSION == 1
    assert client_info_payload()["mobile_contract"] == manifest
    assert manifest["contract_version"] == 1
    assert manifest["api_version"] == 1
    assert manifest["websocket_protocol_version"] == 1
    assert manifest["session_header"] == "X-Session-Token"

    actual = {
        (method, route.path)
        for route in app.routes
        for method in (getattr(route, "methods", None) or set())
    }
    endpoints = manifest["endpoints"]
    assert len(endpoints) >= 80
    for operation, spec in endpoints.items():
        assert (spec["method"], spec["path"]) in actual, operation


def test_mobile_contract_critical_request_fields_match_pydantic_schemas() -> None:
    manifest = mobile_contract_manifest()
    fields = manifest["request_fields"]
    assert fields["auth_login"] == list(LoginRequest.model_fields)
    assert fields["auth_device_login"] == list(DeviceLoginRequest.model_fields)
    assert fields["pairing_start"] == list(PairingStartRequest.model_fields)
    assert fields["pairing_claim"] == list(PairingClaimRequest.model_fields)


def test_mobile_contract_declares_critical_response_fields_and_close_codes() -> None:
    manifest = mobile_contract_manifest()
    assert manifest["response_fields"]["auth_grant"] == [
        "token",
        "server_version",
        "api_version",
        "websocket_protocol_version",
        "heartbeat_interval_seconds",
        "heartbeat_timeout_seconds",
        "session",
    ]
    assert manifest["response_fields"]["ws_ticket"] == ["ticket"]
    assert set(manifest["response_fields"]["pairing_start"]) >= {"pairing_id", "pairing_uri"}
    assert set(manifest["response_fields"]["pairing_claim"]) >= {"device_id", "device_token"}
    assert manifest["websocket_close_codes"] == {
        "unauthorized": 4401,
        "origin_rejected": 4403,
        "protocol_unsupported": 4406,
        "heartbeat_timeout": 4408,
    }
