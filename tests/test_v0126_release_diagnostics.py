from __future__ import annotations

from app.api.client_contract import (
    MOBILE_CONTRACT_FINGERPRINT,
    client_info_payload,
    mobile_contract_fingerprint,
    mobile_contract_manifest,
)


def test_mobile_contract_fingerprint_is_stable_and_published() -> None:
    manifest = mobile_contract_manifest()
    assert "diagnostics_logs_get" in manifest["endpoints"]
    assert manifest["endpoints"]["diagnostics_logs_get"] == {
        "method": "GET",
        "path": "/api/diagnostics/logs",
    }
    assert mobile_contract_fingerprint(manifest) == MOBILE_CONTRACT_FINGERPRINT
    assert client_info_payload()["mobile_contract_fingerprint"] == MOBILE_CONTRACT_FINGERPRINT
    assert len(MOBILE_CONTRACT_FINGERPRINT) == 64


def test_diagnostics_snapshot_contract_metadata_is_non_secret() -> None:
    from app.api.diagnostics import diagnostics_snapshot

    payload = diagnostics_snapshot()
    compatibility = payload["compatibility"]
    assert compatibility["mobile_contract_fingerprint"] == MOBILE_CONTRACT_FINGERPRINT
    assert compatibility["api_version"] == 1
    assert compatibility["websocket_protocol_version"] == 1
    serialized = str(compatibility).lower()
    assert "token" not in serialized
    assert "pin" not in serialized
    assert "secret" not in serialized


def test_diagnostics_redacts_mobile_credentials() -> None:
    from app.services.diagnostics import _redact

    value = _redact(
        "Authorization: Bearer abc123 X-Session-Token=zzzsession999 pairing secret=hunter2 "
        "device_token=device-secret pin=1234"
    )
    lowered = value.lower()
    for secret in ("abc123", "zzzsession999", "hunter2", "device-secret", "1234"):
        assert secret not in lowered
    assert lowered.count("<redacted>") >= 5
