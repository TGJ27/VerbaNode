from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.db import Database
from app.paths import BACKUP_DIR, MODEL_DIR, ensure_runtime_layout
from app.services.https_cert import ensure_local_certificate
from app.services.stt import FunASRService
from app.version import APP_VERSION

KOKORO_ARCHIVE = "kokoro-int8-multi-lang-v1_1.tar.bz2"
KOKORO_RELEASE_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/"
    + KOKORO_ARCHIVE
)
KOKORO_DIR_NAME = "kokoro-int8-multi-lang-v1_1"
OLLAMA_URL = "http://127.0.0.1:11434"
_MODEL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


def _print(message: str) -> None:
    print(message, flush=True)


def _safe_model_name(value: str) -> str:
    model = str(value or "").strip()
    if not _MODEL_NAME_RE.fullmatch(model):
        raise ValueError("Invalid Ollama model name")
    return model


def _backup_database(db_path: Path) -> Path | None:
    if not db_path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"verbanode-before-v{APP_VERSION}-{stamp}.db"
    source = sqlite3.connect(str(db_path))
    target = sqlite3.connect(str(backup_path))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return backup_path


def setup_database() -> int:
    ensure_runtime_layout()
    get_settings.cache_clear()
    settings = get_settings()
    backup = _backup_database(Path(settings.db_path))
    if backup:
        _print(f"Database backup: {backup}")
    Database(settings).initialize()
    _print(f"Database ready: {settings.db_path}")
    return 0


def setup_https() -> int:
    ensure_runtime_layout()
    cert, key, addresses, generated = ensure_local_certificate()
    _print(f"HTTPS certificate: {cert}")
    _print(f"HTTPS key: {key}")
    _print("Certificate generated." if generated else "Existing certificate is valid.")
    if addresses:
        _print("Certificate addresses: " + ", ".join(addresses))
    return 0


def _modelscope_cache_roots() -> list[Path]:
    roots: list[Path] = []
    for variable in ("MODELSCOPE_CACHE", "MODELSCOPE_HOME"):
        value = os.environ.get(variable)
        if value:
            roots.append(Path(value).expanduser())
    roots.append(Path.home() / ".cache" / "modelscope")

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = os.path.normcase(str(root.resolve(strict=False)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(root)
    return unique


def sensevoice_cache_status() -> dict[str, object]:
    """Return whether the configured SenseVoice checkpoint is already cached.

    ModelScope has used more than one cache layout over time, so detection is
    intentionally conservative and checks only directories that can belong to
    the configured model instead of recursively scanning the entire cache.
    """
    settings = get_settings()
    model_id = str(settings.funasr_model or "iic/SenseVoiceSmall").strip()
    org, _, name = model_id.partition("/")
    compact = model_id.replace("/", "--")
    candidates: list[Path] = []

    for root in _modelscope_cache_roots():
        candidates.extend(
            [
                root / "models" / compact,
                root / "models" / org / name if name else root / "models" / compact,
                root / "hub" / org / name if name else root / "hub" / compact,
                root / compact,
            ]
        )

    for directory in candidates:
        if not directory.exists():
            continue
        direct = directory / "model.pt"
        if direct.is_file():
            return {"downloaded": True, "path": str(direct)}
        snapshots = directory / "snapshots"
        if snapshots.exists():
            try:
                for checkpoint in snapshots.glob("*/model.pt"):
                    if checkpoint.is_file():
                        return {"downloaded": True, "path": str(checkpoint)}
            except OSError:
                pass

    return {"downloaded": False, "path": None}


def download_sensevoice() -> int:
    ensure_runtime_layout()
    cached = sensevoice_cache_status()
    if cached.get("downloaded"):
        _print(f"SenseVoiceSmall already cached: {cached.get('path')}")
        return 0

    from funasr import AutoModel

    settings = get_settings()
    _print(f"Preparing SenseVoice model: {settings.funasr_model}")
    AutoModel(
        model=settings.funasr_model,
        trust_remote_code=True,
        disable_update=True,
        device="cpu",
        ncpu=2,
    )
    _print("SenseVoiceSmall is ready.")
    return 0


def _prepare_whisper(model_name: str) -> None:
    from funasr import AutoModel

    status = FunASRService.whisper_cache_status()
    item = status.get("models", {}).get(model_name, {})
    if item.get("downloaded"):
        _print(f"{model_name} already cached: {item.get('path')}")
        return
    _print(f"Preparing Indonesian ASR model: {model_name}")
    try:
        AutoModel(model=model_name, hub="openai", device="cpu", ncpu=2)
    except TypeError:
        AutoModel(model=model_name, hub="openai", device="cpu")
    _print(f"{model_name} is ready.")


def download_whisper(selection: str) -> int:
    ensure_runtime_layout()
    requested = str(selection or "base").strip().lower()
    if requested == "base":
        models = ["Whisper-base"]
    elif requested == "small":
        models = ["Whisper-small"]
    elif requested == "both":
        models = ["Whisper-base", "Whisper-small"]
    else:
        raise ValueError("Whisper selection must be base, small, or both")
    for model_name in models:
        _prepare_whisper(model_name)
    return 0


def _safe_extract_tar(archive: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in archive.getmembers():
        target = (destination / member.name).resolve()
        if target != destination and destination not in target.parents:
            raise RuntimeError(f"Unsafe archive entry: {member.name}")
    archive.extractall(destination)


def download_kokoro() -> int:
    ensure_runtime_layout()
    models_dir = MODEL_DIR / "kokoro"
    destination = models_dir / KOKORO_DIR_NAME
    model_file = destination / "model.int8.onnx"
    voices_file = destination / "voices.bin"
    if model_file.exists() and voices_file.exists():
        _print(f"Kokoro already installed: {destination}")
        return 0

    models_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="verbanode-kokoro-") as temp_name:
        temp = Path(temp_name)
        archive_path = temp / KOKORO_ARCHIVE
        _print(f"Downloading Kokoro from {KOKORO_RELEASE_URL}")
        urllib.request.urlretrieve(KOKORO_RELEASE_URL, archive_path)
        _print("Extracting Kokoro...")
        with tarfile.open(archive_path, "r:bz2") as archive:
            _safe_extract_tar(archive, temp)
        extracted = temp / KOKORO_DIR_NAME
        if not extracted.exists():
            candidates = [path for path in temp.iterdir() if path.is_dir()]
            if len(candidates) != 1:
                raise RuntimeError("Could not identify the extracted Kokoro directory")
            extracted = candidates[0]
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(extracted), str(destination))

    if not model_file.exists() or not voices_file.exists():
        raise RuntimeError("Kokoro extraction completed without required model files")
    _print(f"Kokoro ready: {destination}")
    return 0


def _ollama_executable() -> Path | None:
    found = shutil.which("ollama")
    if found:
        return Path(found)
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidate = Path(local_appdata) / "Programs" / "Ollama" / "ollama.exe"
        if candidate.is_file():
            return candidate
    return None


def _ollama_api_ready(timeout: float = 1.5) -> bool:
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=timeout) as response:
            return int(response.status) == 200
    except (OSError, urllib.error.URLError):
        return False


def ollama_installed() -> bool:
    return _ollama_api_ready() or _ollama_executable() is not None


def setup_ollama_status() -> int:
    if _ollama_api_ready():
        _print("Ollama is installed and the local API is ready.")
        return 0
    executable = _ollama_executable()
    if executable:
        _print(f"Ollama is installed: {executable}")
        return 0
    _print("Ollama is not installed.")
    return 3


def _ensure_ollama_running(timeout_seconds: float = 45.0) -> None:
    if _ollama_api_ready():
        return
    executable = _ollama_executable()
    if executable is None:
        raise RuntimeError("Ollama is not installed")

    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        [str(executable), "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _ollama_api_ready(timeout=2.0):
            return
        time.sleep(1.0)
    raise RuntimeError("Ollama was installed but its local API did not become ready")


def _ollama_model_names() -> set[str]:
    if not _ollama_api_ready(timeout=2.0):
        return set()
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=3.0) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except (OSError, ValueError, urllib.error.URLError):
        return set()

    names: set[str] = set()
    for item in payload.get("models", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        for key in ("name", "model"):
            value = str(item.get(key) or "").strip()
            if value:
                names.add(value)
    return names


def ollama_model_installed(model_name: str) -> bool:
    model = _safe_model_name(model_name)
    names = _ollama_model_names()
    if model in names:
        return True
    if ":" not in model and (model + ":latest") in names:
        return True
    return False


def pull_ollama_model(model_name: str) -> int:
    model = _safe_model_name(model_name)
    _ensure_ollama_running()
    if ollama_model_installed(model):
        _print(f"Ollama model already installed: {model}")
        return 0
    payload = json.dumps({"model": model, "stream": False}).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL + "/api/pull",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    _print(f"Pulling Ollama model: {model}")
    try:
        with urllib.request.urlopen(request, timeout=7200) as response:
            body = response.read().decode("utf-8", errors="replace")
            if int(response.status) != 200:
                raise RuntimeError(f"Ollama pull failed with HTTP {response.status}: {body}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ollama pull failed with HTTP {exc.code}: {detail}") from exc
    _print(f"Ollama model ready: {model}")
    return 0


def health_check() -> int:
    ensure_runtime_layout()
    get_settings.cache_clear()
    settings = get_settings()
    cert, key, _addresses, _generated = ensure_local_certificate()
    whisper = FunASRService.whisper_cache_status()
    report = {
        "version": APP_VERSION,
        "database": str(settings.db_path),
        "database_exists": Path(settings.db_path).exists(),
        "certificate": str(cert),
        "certificate_exists": cert.exists() and key.exists(),
        "sensevoice": sensevoice_cache_status(),
        "whisper": whisper,
        "kokoro_exists": (MODEL_DIR / "kokoro" / KOKORO_DIR_NAME / "model.int8.onnx").exists(),
        "ollama_installed": ollama_installed(),
        "ollama_ready": _ollama_api_ready(),
        "ollama_models": sorted(_ollama_model_names()),
    }
    _print(json.dumps(report, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--setup-database", action="store_true")
    group.add_argument("--setup-https", action="store_true")
    group.add_argument("--setup-download-sensevoice", action="store_true")
    group.add_argument("--setup-download-whisper", metavar="BASE|SMALL|BOTH")
    group.add_argument("--setup-download-kokoro", action="store_true")
    group.add_argument("--setup-ollama-status", action="store_true")
    group.add_argument("--setup-ollama-pull", metavar="MODEL")
    group.add_argument("--setup-health-check", action="store_true")
    return parser


def run_from_argv(argv: list[str]) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.setup_database:
            return setup_database()
        if args.setup_https:
            return setup_https()
        if args.setup_download_sensevoice:
            return download_sensevoice()
        if args.setup_download_whisper:
            return download_whisper(args.setup_download_whisper)
        if args.setup_download_kokoro:
            return download_kokoro()
        if args.setup_ollama_status:
            return setup_ollama_status()
        if args.setup_ollama_pull:
            return pull_ollama_model(args.setup_ollama_pull)
        if args.setup_health_check:
            return health_check()
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"VerbaNode setup command failed: {exc}", file=sys.stderr, flush=True)
        return 1
