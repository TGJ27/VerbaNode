from __future__ import annotations

import json
import socket
import time
from pathlib import Path

from app.config import Settings
from app.services.discovery import (
    ACTIVE_DISCOVERY_MAGIC,
    ACTIVE_DISCOVERY_PROTOCOL_VERSION,
    LanDiscoveryAdvertiser,
    build_active_discovery_response,
    is_active_discovery_request,
)


def _free_udp_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
    finally:
        sock.close()


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
        port=8002,
        lan_discovery_enabled=True,
        lan_discovery_udp_port=_free_udp_port(),
        open_browser=False,
    )


def test_active_discovery_request_is_exact_and_versioned() -> None:
    assert ACTIVE_DISCOVERY_PROTOCOL_VERSION == 1
    assert is_active_discovery_request(ACTIVE_DISCOVERY_MAGIC)
    assert not is_active_discovery_request(b"VERBANODE_DISCOVER/0")
    assert not is_active_discovery_request(ACTIVE_DISCOVERY_MAGIC + b" extra")


def test_active_discovery_response_contains_only_public_identity_fields() -> None:
    payload = build_active_discovery_response(
        instance_id="instance-123",
        instance_name="Studio PC",
        version="0.12.5",
        https_port=8002,
        api_version=1,
        ws_version=1,
        spki_sha256="a" * 64,
    )
    assert payload == {
        "product": "VerbaNode",
        "discovery_protocol": 1,
        "instance_id": "instance-123",
        "instance_name": "Studio PC",
        "version": "0.12.5",
        "https_port": 8002,
        "api_version": 1,
        "websocket_protocol_version": 1,
        "spki_sha256": "a" * 64,
    }
    assert "pin" not in json.dumps(payload).lower()
    assert "token" not in json.dumps(payload).lower()


def test_udp_responder_answers_valid_request_and_stops(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("app.services.discovery.certificate_spki_sha256", lambda: "b" * 64)
    advertiser = LanDiscoveryAdvertiser(
        _settings(tmp_path),
        instance_id="instance-udp",
        version="0.12.5",
        api_version=1,
        ws_version=1,
    )
    assert advertiser.start_active_udp() is True
    status = advertiser.status()
    udp_port = status["active_udp_port"]
    assert status["active_udp_enabled"] is True
    assert isinstance(udp_port, int) and udp_port > 0

    client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client.settimeout(1.5)
    client.sendto(ACTIVE_DISCOVERY_MAGIC, ("127.0.0.1", udp_port))
    body, _ = client.recvfrom(8192)
    response = json.loads(body.decode("utf-8"))
    assert response["product"] == "VerbaNode"
    assert response["instance_id"] == "instance-udp"
    assert response["https_port"] == 8002
    assert response["spki_sha256"] == "b" * 64
    client.close()

    advertiser.stop()
    time.sleep(0.05)
    assert advertiser.status()["active_udp_enabled"] is False


def test_client_info_advertises_active_discovery(tmp_path: Path) -> None:
    from app.api.client_contract import client_info_payload, feature_manifest
    from app.config import get_settings

    get_settings.cache_clear()
    info = client_info_payload(instance_id="instance-test", instance_name="Test PC")
    assert feature_manifest()["active_lan_discovery"] is True
    assert feature_manifest()["active_lan_discovery_protocol_version"] == 1
    assert info["discovery"]["active_udp_enabled"] is True
    assert info["discovery"]["active_udp_protocol_version"] == 1
    assert info["discovery"]["active_udp_port"] == get_settings().lan_discovery_udp_port == 8002


def test_windows_firewall_helper_allows_active_udp_discovery() -> None:
    root = Path(__file__).resolve().parent.parent
    script = (root / "scripts" / "windows" / "allow_firewall.bat").read_text(encoding="utf-8")
    assert 'protocol=UDP localport=%DISCOVERY_PORT% profile=private' in script
    assert 'name="VerbaNode Active Discovery"' in script
    installer = (root / "packaging" / "VerbaNode.iss").read_text(encoding="utf-8")
    # Installer rule is executable-scoped and intentionally protocol-agnostic,
    # so it covers HTTPS TCP plus active-discovery UDP for the packaged app.
    assert 'advfirewall firewall add rule name=""VerbaNode"" dir=in action=allow program=' in installer
