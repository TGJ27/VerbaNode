from __future__ import annotations

import os
import secrets
import shutil
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent.parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)).resolve() if IS_FROZEN else SOURCE_ROOT


def _local_appdata() -> Path:
    override = os.environ.get("VERBANODE_USER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    value = os.environ.get("LOCALAPPDATA")
    if value:
        return Path(value).expanduser().resolve() / "VerbaNode"
    return Path.home() / "AppData" / "Local" / "VerbaNode"


# Development/source mode intentionally preserves the historical repository-local
# layout. Frozen builds move mutable data to LocalAppData so Program Files stays
# read-only and application upgrades cannot overwrite user state.
USER_DATA_ROOT = _local_appdata() if IS_FROZEN else SOURCE_ROOT
CONFIG_DIR = USER_DATA_ROOT / "config" if IS_FROZEN else SOURCE_ROOT
DATA_DIR = USER_DATA_ROOT / "data"
CERT_DIR = USER_DATA_ROOT / "certs"
MODEL_DIR = USER_DATA_ROOT / "models" if IS_FROZEN else SOURCE_ROOT / "models"
PLUGIN_DIR = USER_DATA_ROOT / "plugins" if IS_FROZEN else SOURCE_ROOT / "plugins"
DIAGNOSTICS_DIR = USER_DATA_ROOT / "diagnostics"
RUNTIME_AUDIO_DIR = USER_DATA_ROOT / "runtime_audio"
BACKUP_DIR = USER_DATA_ROOT / "backups"
LOG_DIR = USER_DATA_ROOT / "logs"


def _ensure_frozen_env(env_file: Path, env_example: Path) -> None:
    """Seed frozen config once and ensure it has a usable controller PIN.

    Existing user configuration is never replaced. The only value repaired in
    an existing file is the shipped placeholder/blank controller PIN.
    """
    if not env_file.exists():
        if env_example.exists():
            shutil.copy2(env_example, env_file)
        else:
            env_file.write_text("VERBANODE_PIN=CHANGE_ME\n", encoding="utf-8")

    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    pin_index: int | None = None
    pin_value = ""
    for index, line in enumerate(lines):
        if line.strip().upper().startswith("VERBANODE_PIN="):
            pin_index = index
            pin_value = line.split("=", 1)[1].strip()
            break

    if pin_value and pin_value.upper() != "CHANGE_ME":
        return

    generated_pin = str(secrets.randbelow(900000) + 100000)
    replacement = f"VERBANODE_PIN={generated_pin}"
    if pin_index is None:
        lines.append(replacement)
    else:
        lines[pin_index] = replacement

    try:
        env_file.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    except OSError:
        return


def resource_path(*parts: str) -> Path:
    return RESOURCE_ROOT.joinpath(*parts)


def ensure_runtime_layout() -> None:
    for directory in (
        USER_DATA_ROOT,
        CONFIG_DIR,
        DATA_DIR,
        CERT_DIR,
        MODEL_DIR,
        PLUGIN_DIR,
        DIAGNOSTICS_DIR,
        RUNTIME_AUDIO_DIR,
        BACKUP_DIR,
        LOG_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    if not IS_FROZEN:
        return

    env_file = CONFIG_DIR / ".env"
    env_example = resource_path(".env.example")
    _ensure_frozen_env(env_file, env_example)

    # Seed documentation/template/reference plugins only when absent. Existing
    # plugins are never overwritten by an application upgrade.
    bundled_plugins = resource_path("plugins")
    if bundled_plugins.exists():
        for name in ("README.md", "_template", "example_echo"):
            source = bundled_plugins / name
            destination = PLUGIN_DIR / name
            if not source.exists() or destination.exists():
                continue
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
