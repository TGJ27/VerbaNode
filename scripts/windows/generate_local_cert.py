from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.services.https_cert import ensure_local_certificate


def main() -> None:
    cert, _key, addresses, generated = ensure_local_certificate()
    if generated:
        print("Generated local HTTPS certificate for " + ", ".join(addresses))
    else:
        print("Local HTTPS certificate already matches " + ", ".join(addresses))
    print(f"Certificate to trust on the phone: {cert}")


if __name__ == "__main__":
    main()
