from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import get_settings
from app.db import Database


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or migrate the VerbaNode SQLite database.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing database before creating a fresh one.",
    )
    args = parser.parse_args()

    settings = get_settings()
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    if args.reset and db_path.exists():
        db_path.unlink()
        for suffix in ("-shm", "-wal"):
            sidecar = Path(f"{db_path}{suffix}")
            if sidecar.exists():
                sidecar.unlink()
        print(f"Removed existing database: {db_path}")

    existed = db_path.exists()
    Database(settings).initialize()
    action = "Migrated" if existed else "Created"
    print(f"{action} database: {db_path}")
    print("Default agent: Ropi")
    print("Default model: qwen3.5:0.8b")
    print("Default STT confidence threshold: 70%")
    print("Default maximum response tokens: 224")


if __name__ == "__main__":
    main()
