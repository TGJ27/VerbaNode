from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CERT_DIR = ROOT / "certs"
CERT_FILE = CERT_DIR / "verbanode-local-ca.crt"
KEY_FILE = CERT_DIR / "verbanode-local-ca.key"
STAMP_FILE = CERT_DIR / "local-ip.txt"
CONFIG_FILE = CERT_DIR / "openssl-local.cnf"


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def openssl_path() -> str:
    candidates = [
        shutil.which("openssl"),
        str(Path(os.environ.get("CONDA_PREFIX", "")) / "Library" / "bin" / "openssl.exe"),
        str(Path(os.environ.get("CONDA_PREFIX", "")) / "bin" / "openssl"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise SystemExit("OpenSSL was not found in the active Conda environment.")


def main() -> None:
    address = local_ip()
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    if CERT_FILE.exists() and KEY_FILE.exists() and STAMP_FILE.exists() and STAMP_FILE.read_text().strip() == address:
        print(f"Local HTTPS certificate already matches {address}")
        return
    CONFIG_FILE.write_text(
        f"""[req]\nprompt = no\ndistinguished_name = dn\nx509_extensions = extensions\n\n[dn]\nCN = VerbaNode Local\nO = Sari Technology Global\n\n[extensions]\nbasicConstraints = critical,CA:TRUE\nkeyUsage = critical,digitalSignature,keyEncipherment,keyCertSign\nextendedKeyUsage = serverAuth\nsubjectAltName = @names\n\n[names]\nDNS.1 = localhost\nIP.1 = 127.0.0.1\nIP.2 = {address}\n""",
        encoding="utf-8",
    )
    command = [
        openssl_path(), "req", "-x509", "-nodes", "-newkey", "rsa:2048",
        "-keyout", str(KEY_FILE), "-out", str(CERT_FILE), "-days", "3650",
        "-config", str(CONFIG_FILE), "-extensions", "extensions",
    ]
    subprocess.run(command, check=True)
    STAMP_FILE.write_text(address, encoding="utf-8")
    print(f"Generated local HTTPS certificate for 127.0.0.1 and {address}")
    print(f"Certificate to trust on the phone: {CERT_FILE}")


if __name__ == "__main__":
    main()
