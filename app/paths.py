from __future__ import annotations

import os
import secrets
import shutil
import sys
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parent.parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", SOURCE_ROOT)).resolve() if IS_FROZEN else SOURCE_ROOT


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _local_appdata() -> Path:
    override = os.environ.get("VERBANODE_USER_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    value = os.environ.get("LOCALAPPDATA")
    if value:
        return Path(value).expanduser().resolve() / "VerbaNode"
    return Path.home() / "AppData" / "Local" / "VerbaNode"


# v0.9.1: mutable identity/state is stable across source-folder and packaged
# upgrades. Developers who explicitly want the historical repo-local behavior
# can opt into portable mode.
PORTABLE_SOURCE_MODE = bool(not IS_FROZEN and _truthy_env("VERBANODE_PORTABLE_MODE"))
USER_DATA_ROOT = SOURCE_ROOT if PORTABLE_SOURCE_MODE else _local_appdata()
CONFIG_DIR = SOURCE_ROOT if PORTABLE_SOURCE_MODE else USER_DATA_ROOT / "config"
DATA_DIR = USER_DATA_ROOT / "data"
CERT_DIR = USER_DATA_ROOT / "certs"
MODEL_DIR = USER_DATA_ROOT / "models" if IS_FROZEN else SOURCE_ROOT / "models"
PLUGIN_DIR = USER_DATA_ROOT / "plugins" if IS_FROZEN else SOURCE_ROOT / "plugins"
DIAGNOSTICS_DIR = USER_DATA_ROOT / "diagnostics"
RUNTIME_AUDIO_DIR = USER_DATA_ROOT / "runtime_audio"
AUDIO_LIBRARY_DIR = USER_DATA_ROOT / "audio_library"
BACKUP_DIR = USER_DATA_ROOT / "backups"
LOG_DIR = USER_DATA_ROOT / "logs"


def _copy_if_missing(source: Path, destination: Path) -> None:
    if not source.exists() or destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _migrate_legacy_source_runtime_once() -> None:
    """Move v0.9.0 source-mode identity/state to stable LocalAppData once.

    A clean source update used to create a new database/certificate identity and
    therefore looked like a different VerbaNode to Android. From v0.9.1 source
    mode shares the same persistent runtime root as packaged builds. Existing
    files are copied only when the stable destination does not already exist.
    """
    if IS_FROZEN or PORTABLE_SOURCE_MODE or USER_DATA_ROOT == SOURCE_ROOT:
        return
    marker = USER_DATA_ROOT / ".source-runtime-migrated-v091"
    if marker.exists():
        return
    USER_DATA_ROOT.mkdir(parents=True, exist_ok=True)

    # Preserve controller PIN/configuration, database identity/trusted devices,
    # certificate private key/SPKI, recovery data and user-created audio.
    _copy_if_missing(SOURCE_ROOT / ".env", CONFIG_DIR / ".env")
    for name in ("data", "certs", "backups", "diagnostics", "runtime_audio", "audio_library", "logs"):
        _copy_if_missing(SOURCE_ROOT / name, USER_DATA_ROOT / name)
    marker.write_text("VerbaNode source runtime migrated to stable user data in v0.9.1\n", encoding="utf-8")


def _ensure_env_file(env_file: Path, env_example: Path) -> None:
    """Seed config once and ensure it has a non-placeholder controller PIN."""
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


def _ensure_frozen_env(env_file: Path, env_example: Path) -> None:
    """Backward-compatible wrapper retained for packaging/tests."""
    _ensure_env_file(env_file, env_example)


def resource_path(*parts: str) -> Path:
    return RESOURCE_ROOT.joinpath(*parts)


def ensure_runtime_layout() -> None:
    _migrate_legacy_source_runtime_once()
    for directory in (
        USER_DATA_ROOT,
        CONFIG_DIR,
        DATA_DIR,
        CERT_DIR,
        MODEL_DIR,
        PLUGIN_DIR,
        DIAGNOSTICS_DIR,
        RUNTIME_AUDIO_DIR,
        AUDIO_LIBRARY_DIR,
        BACKUP_DIR,
        LOG_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    env_file = CONFIG_DIR / ".env"
    env_example = resource_path(".env.example")
    _ensure_env_file(env_file, env_example)

    if not IS_FROZEN:
        return

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
