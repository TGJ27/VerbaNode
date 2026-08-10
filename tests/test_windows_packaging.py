from __future__ import annotations

import re
import socket
from pathlib import Path
from types import SimpleNamespace

import app.paths as paths
from app.services import https_cert


def test_source_mode_keeps_existing_repository_data_layout() -> None:
    if paths.IS_FROZEN:
        return
    assert paths.USER_DATA_ROOT == paths.SOURCE_ROOT
    assert paths.DATA_DIR == paths.SOURCE_ROOT / "data"
    assert paths.PLUGIN_DIR == paths.SOURCE_ROOT / "plugins"
    assert paths.CONFIG_DIR == paths.SOURCE_ROOT


def test_network_discovery_filters_loopback_link_local_and_virtual(monkeypatch) -> None:
    monkeypatch.setattr(
        https_cert.psutil,
        "net_if_stats",
        lambda: {
            "Ethernet": SimpleNamespace(isup=True),
            "WSL": SimpleNamespace(isup=True),
            "Down": SimpleNamespace(isup=False),
        },
    )
    monkeypatch.setattr(
        https_cert.psutil,
        "net_if_addrs",
        lambda: {
            "Ethernet": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.18.121"),
                SimpleNamespace(family=socket.AF_INET, address="169.254.1.2"),
            ],
            "WSL": [SimpleNamespace(family=socket.AF_INET, address="172.25.0.1")],
            "Down": [SimpleNamespace(family=socket.AF_INET, address="10.0.0.2")],
        },
    )
    assert https_cert.discover_ipv4_addresses() == [("Ethernet", "192.168.18.121")]


def test_certificate_address_list_always_contains_localhost(monkeypatch) -> None:
    monkeypatch.setattr(
        https_cert,
        "discover_ipv4_addresses",
        lambda **_: [("Wi-Fi", "192.168.1.10"), ("Ethernet", "192.168.18.121")],
    )
    assert https_cert.certificate_addresses() == ["127.0.0.1", "192.168.1.10", "192.168.18.121"]


def test_windows_build_assets_exist() -> None:
    root = Path(__file__).resolve().parent.parent
    assert (root / "VerbaNode.spec").exists()
    assert (root / "build_windows.bat").exists()
    assert (root / "requirements-packaging.txt").exists()
    assert (root / "packaging" / "WINDOWS_APP.md").exists()


def test_frozen_env_seed_generates_six_digit_pin(tmp_path) -> None:
    env_example = tmp_path / ".env.example"
    env_file = tmp_path / ".env"
    env_example.write_text("VERBANODE_PIN=CHANGE_ME\nVERBANODE_PORT=8002\n", encoding="utf-8")

    paths._ensure_frozen_env(env_file, env_example)

    content = env_file.read_text(encoding="utf-8")
    match = re.search(r"^VERBANODE_PIN=(\d{6})$", content, flags=re.MULTILINE)
    assert match is not None
    assert "VERBANODE_PORT=8002" in content


def test_frozen_env_seed_preserves_existing_pin(tmp_path) -> None:
    env_example = tmp_path / ".env.example"
    env_file = tmp_path / ".env"
    env_example.write_text("VERBANODE_PIN=CHANGE_ME\n", encoding="utf-8")
    env_file.write_text("VERBANODE_PIN=654321\nVERBANODE_PORT=9000\n", encoding="utf-8")

    paths._ensure_frozen_env(env_file, env_example)

    content = env_file.read_text(encoding="utf-8")
    assert "VERBANODE_PIN=654321" in content
    assert "VERBANODE_PORT=9000" in content
