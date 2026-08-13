from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
