from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from app.api.client_contract import client_info_payload, feature_manifest
from app.config import Settings
from app.db import Database
from app.migrations import CURRENT_SCHEMA_VERSION
from app.services.controller import ControllerManager
from app.services.devices import DeviceManager
from app.version import APP_VERSION, BUILD_LABEL


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "verbanode.db",
        backup_path=tmp_path / "backups",
        pin="246810",
        open_browser=False,
        mobile_pairing_ttl_seconds=180,
    )


def test_v090_metadata_and_mobile_contract() -> None:
    assert APP_VERSION == "0.9.9"
    assert BUILD_LABEL == "local-mobile"
    assert CURRENT_SCHEMA_VERSION == 10
    features = feature_manifest()
    assert features["mobile_pairing"] is True
    assert features["trusted_devices"] is True
    assert features["device_revocation"] is True
    assert features["lan_discovery"] is True
    assert features["mdns_service_type"] == "_verbanode._tcp.local."

    info = client_info_payload()
    assert info["authentication"]["mode"] == "pin_or_trusted_device"
    assert info["authentication"]["device_login_endpoint"] == "/api/auth/device-login"
    assert info["authentication"]["pairing_claim_endpoint"] == "/api/pairing/claim"
    assert info["discovery"]["service_type"] == "_verbanode._tcp.local."
    assert "certificate_spki_sha256" in info["tls"]


def test_v5_trusted_device_schema_is_migrated(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()
    with sqlite3.connect(settings.db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(trusted_devices)")}
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 10
    assert {
        "device_id",
        "name",
        "device_type",
        "credential_hash",
        "created_at",
        "last_seen_at",
        "revoked_at",
        "metadata_json",
    } <= columns


def test_qr_pairing_claim_stores_only_credential_hash_and_can_revoke(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()
    devices = DeviceManager(db, pairing_ttl_seconds=180)

    pairing = devices.create_pairing(
        server_url="https://192.168.1.20:8002",
        certificate_fingerprint_sha256="a" * 64,
        certificate_spki_sha256="b" * 64,
    )
    uri = urlsplit(pairing["pairing_uri"])
    query = parse_qs(uri.query)
    assert uri.scheme == "verbanode"
    assert uri.netloc == "pair"
    assert query["pairing_id"][0] == pairing["pairing_id"]
    assert query["secret"][0]
    assert query["spki"][0] == "b" * 64

    public_status = devices.pairing_status(pairing["pairing_id"])
    assert public_status is not None
    assert public_status["short_code"] is None
    assert public_status["pairing_uri"] is None

    claimed = devices.claim_pairing(
        client_key="192.168.1.44",
        pairing_id=pairing["pairing_id"],
        secret=query["secret"][0],
        short_code=None,
        device_name="Pixel Test",
        device_type="mobile",
        device_version="0.1.0",
        platform="android",
    )
    token = claimed["device_token"]
    assert claimed["certificate_spki_sha256"] == "b" * 64
    assert devices.verify_device(claimed["device_id"], token) is not None

    with db.connect() as conn:
        row = conn.execute(
            "SELECT credential_hash,metadata_json FROM trusted_devices WHERE device_id=?",
            (claimed["device_id"],),
        ).fetchone()
    assert row is not None
    assert token not in str(row["credential_hash"])
    assert len(str(row["credential_hash"])) == 64
    assert "android" in str(row["metadata_json"])

    assert devices.revoke_device(claimed["device_id"]) is True
    assert devices.verify_device(claimed["device_id"], token) is None


def test_short_code_pairing_and_device_rename_delete(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    db = Database(settings)
    db.initialize()
    devices = DeviceManager(db)
    pairing = devices.create_pairing(
        server_url="https://10.0.0.10:8002",
        certificate_fingerprint_sha256="c" * 64,
        certificate_spki_sha256="d" * 64,
    )
    claimed = devices.claim_pairing(
        client_key="10.0.0.11",
        pairing_id=None,
        secret=None,
        short_code=pairing["short_code"],
        device_name="Workshop tablet",
        device_type="mobile",
        device_version="0.1.0",
        platform="android",
    )
    renamed = devices.rename_device(claimed["device_id"], "Workshop Controller")
    assert renamed is not None and renamed["name"] == "Workshop Controller"
    assert devices.revoke_device(claimed["device_id"]) is True
    assert devices.delete_device(claimed["device_id"]) is True
    assert all(item["device_id"] != claimed["device_id"] for item in devices.list_devices())


def test_trusted_device_controller_session_carries_device_identity(tmp_path: Path) -> None:
    manager = ControllerManager(_settings(tmp_path))
    result = manager.login_trusted_device(
        "Pixel Test",
        device_id="device-123",
        client_type="mobile",
        client_version="0.1.0",
        api_version=1,
    )
    assert result["status"] == "granted"
    active = manager.active_info()
    assert active is not None
    assert active["device_id"] == "device-123"
    assert active["client_type"] == "mobile"


def test_local_certificate_regeneration_preserves_spki_identity(monkeypatch, tmp_path: Path) -> None:
    import app.services.https_cert as certs

    monkeypatch.setattr(certs, "CERT_FILE", tmp_path / "local.crt")
    monkeypatch.setattr(certs, "KEY_FILE", tmp_path / "local.key")
    monkeypatch.setattr(certs, "STAMP_FILE", tmp_path / "ips.txt")
    monkeypatch.setattr(certs, "CONFIG_FILE", tmp_path / "openssl.cnf")
    monkeypatch.setattr(certs, "_openssl_path", lambda: None)

    addresses = {"value": ["127.0.0.1", "192.168.1.10"]}
    monkeypatch.setattr(certs, "certificate_addresses", lambda: list(addresses["value"]))
    certs.ensure_local_certificate()
    first_spki = certs.certificate_spki_sha256()
    first_cert = certs.certificate_fingerprint_sha256()

    addresses["value"] = ["127.0.0.1", "192.168.1.25"]
    _cert, _key, _addresses, regenerated = certs.ensure_local_certificate()
    assert regenerated is True
    assert certs.certificate_spki_sha256() == first_spki
    assert certs.certificate_fingerprint_sha256() != first_cert


def test_dashboard_csp_allows_authenticated_pairing_qr_blob() -> None:
    from app.http import _SECURITY_HEADERS

    csp = _SECURITY_HEADERS["Content-Security-Policy"]
    assert "img-src 'self' data: blob:" in csp
