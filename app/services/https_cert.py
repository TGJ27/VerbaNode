from __future__ import annotations

import ipaddress
import os
import shutil
import socket
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import psutil

from app.paths import CERT_DIR

CERT_FILE = CERT_DIR / "verbanode-local-ca.crt"
KEY_FILE = CERT_DIR / "verbanode-local-ca.key"
STAMP_FILE = CERT_DIR / "local-ips.txt"
CONFIG_FILE = CERT_DIR / "openssl-local.cnf"

_VIRTUAL_INTERFACE_MARKERS = (
    "docker",
    "wsl",
    "vmware",
    "virtualbox",
    "vbox",
    "vethernet",
    "hyper-v",
    "loopback",
)


def discover_ipv4_addresses(*, include_virtual: bool = False) -> list[tuple[str, str]]:
    results: list[tuple[str, str]] = []
    seen: set[str] = set()
    stats = psutil.net_if_stats()
    for interface, addresses in psutil.net_if_addrs().items():
        if stats.get(interface) is not None and not stats[interface].isup:
            continue
        lowered = interface.casefold()
        if not include_virtual and any(marker in lowered for marker in _VIRTUAL_INTERFACE_MARKERS):
            continue
        for entry in addresses:
            if entry.family != socket.AF_INET:
                continue
            value = str(entry.address or "").strip()
            if not value or value in seen:
                continue
            try:
                parsed = ipaddress.ip_address(value)
            except ValueError:
                continue
            if parsed.is_loopback or parsed.is_link_local or parsed.is_unspecified:
                continue
            seen.add(value)
            results.append((interface, value))
    results.sort(key=lambda item: (item[0].casefold(), ipaddress.ip_address(item[1])))
    return results


def certificate_addresses() -> list[str]:
    return ["127.0.0.1", *[address for _, address in discover_ipv4_addresses()]]


def _stamp(addresses: Iterable[str]) -> str:
    return "\n".join(sorted(set(addresses))) + "\n"


def _openssl_path() -> str | None:
    candidates = [
        shutil.which("openssl"),
        str(Path(os.environ.get("CONDA_PREFIX", "")) / "Library" / "bin" / "openssl.exe"),
        str(Path(os.environ.get("CONDA_PREFIX", "")) / "bin" / "openssl"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _generate_with_cryptography(addresses: list[str]) -> None:
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
    except ImportError as exc:  # pragma: no cover - used by packaged build
        raise RuntimeError("Neither OpenSSL nor the bundled cryptography package is available") from exc

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "VerbaNode Local"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Sari Technology Global"),
        ]
    )
    now = datetime.now(timezone.utc)
    san = [x509.DNSName("localhost")]
    san.extend(x509.IPAddress(ipaddress.ip_address(value)) for value in addresses)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=True,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .sign(key, hashes.SHA256())
    )
    KEY_FILE.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    CERT_FILE.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))


def _generate_with_openssl(openssl: str, addresses: list[str]) -> None:
    lines = ["DNS.1 = localhost"]
    for index, address in enumerate(addresses, start=1):
        lines.append(f"IP.{index} = {address}")
    CONFIG_FILE.write_text(
        "[req]\nprompt = no\ndistinguished_name = dn\nx509_extensions = extensions\n\n"
        "[dn]\nCN = VerbaNode Local\nO = Sari Technology Global\n\n"
        "[extensions]\nbasicConstraints = critical,CA:TRUE\n"
        "keyUsage = critical,digitalSignature,keyEncipherment,keyCertSign\n"
        "extendedKeyUsage = serverAuth\nsubjectAltName = @names\n\n[names]\n"
        + "\n".join(lines)
        + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            openssl,
            "req",
            "-x509",
            "-nodes",
            "-newkey",
            "rsa:2048",
            "-keyout",
            str(KEY_FILE),
            "-out",
            str(CERT_FILE),
            "-days",
            "3650",
            "-config",
            str(CONFIG_FILE),
            "-extensions",
            "extensions",
        ],
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def ensure_local_certificate() -> tuple[Path, Path, list[str], bool]:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    addresses = certificate_addresses()
    expected_stamp = _stamp(addresses)
    if (
        CERT_FILE.exists()
        and KEY_FILE.exists()
        and STAMP_FILE.exists()
        and STAMP_FILE.read_text(encoding="utf-8", errors="ignore") == expected_stamp
    ):
        return CERT_FILE, KEY_FILE, addresses, False

    openssl = _openssl_path()
    if openssl:
        _generate_with_openssl(openssl, addresses)
    else:
        _generate_with_cryptography(addresses)
    STAMP_FILE.write_text(expected_stamp, encoding="utf-8")
    return CERT_FILE, KEY_FILE, addresses, True
