from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.version import APP_VERSION, BUILD_LABEL  # noqa: E402


_GENERATED_PATTERNS = (
    "**/__pycache__/*",
    ".pytest_cache/**/*",
    "data/*.db*",
    "certs/*.key",
    "certs/*.pem",
    "certs/*.crt",
    "certs/*.cnf",
    "logs/*",
    "diagnostics/*",
    "runtime_audio/*",
    "audio_library/*",
    "backups/*",
)


def fail(message: str) -> None:
    raise SystemExit(f"RELEASE CHECK FAILED: {message}")


def check_version_consistency() -> None:
    runtime = (PROJECT_ROOT / "app/static/js/runtime.js").read_text(encoding="utf-8")
    index = (PROJECT_ROOT / "app/static/index.html").read_text(encoding="utf-8")
    inno = (PROJECT_ROOT / "packaging/VerbaNode.iss").read_text(encoding="utf-8")
    release_notes = (PROJECT_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
    changelog = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

    if f"const FRONTEND_VERSION = '{APP_VERSION}'" not in runtime:
        fail("frontend version does not match app/version.py")
    if f'id="appVersion">v{APP_VERSION}<' not in index:
        fail("dashboard fallback version does not match app/version.py")
    if f'#define MyAppVersion "{APP_VERSION}"' not in inno:
        fail("Inno Setup default version does not match app/version.py")
    if not release_notes.startswith(f"# VerbaNode v{APP_VERSION}"):
        fail("RELEASE_NOTES.md is not for the current version")
    if f"## v{APP_VERSION}" not in changelog:
        fail("CHANGELOG.md is missing the current version")

    static_refs = re.findall(r'(?:src|href)="(/static/[^\"]+\?v=([^\"]+))"', index)
    stale = [path for path, version in static_refs if version != APP_VERSION]
    if stale:
        fail(f"stale static cache-buster(s): {', '.join(stale)}")
    print("[release] Version/cache-buster consistency OK")


def check_javascript() -> None:
    node = shutil.which("node")
    scripts = sorted((PROJECT_ROOT / "app/static").rglob("*.js"))
    if node is None:
        print("[release] Node.js not found; JavaScript syntax check skipped")
        return
    for script in scripts:
        subprocess.run([node, "--check", str(script)], check=True)
    print(f"[release] JavaScript syntax: {len(scripts)} file(s) OK")


def check_python_compile() -> None:
    files: list[Path] = []
    for root_name in ("app", "scripts", "tests"):
        files.extend(sorted((PROJECT_ROOT / root_name).rglob("*.py")))
    for path in files:
        try:
            source = path.read_text(encoding="utf-8")
            compile(source, str(path), "exec")
        except (OSError, UnicodeError, SyntaxError) as exc:
            fail(f"Python compilation failed for {path.relative_to(PROJECT_ROOT)}: {exc}")
    print(f"[release] Python syntax: {len(files)} file(s) OK")


def check_routes() -> None:
    """Build the real FastAPI app without writing runtime state into the source tree."""
    old_frozen = getattr(sys, "frozen", None)
    had_frozen = hasattr(sys, "frozen")
    old_meipass = getattr(sys, "_MEIPASS", None)
    had_meipass = hasattr(sys, "_MEIPASS")
    old_data_dir = os.environ.get("VERBANODE_USER_DATA_DIR")

    with tempfile.TemporaryDirectory(prefix="verbanode-release-routes-") as tmp:
        sys.frozen = True
        sys._MEIPASS = str(PROJECT_ROOT)
        os.environ["VERBANODE_USER_DATA_DIR"] = tmp
        try:
            from app.main import app

            seen: dict[tuple[str, str], str] = {}
            duplicates: list[str] = []
            for route in app.routes:
                path = getattr(route, "path", None)
                methods = getattr(route, "methods", None) or set()
                if not path:
                    continue
                if not methods and path == "/ws":
                    methods = {"WEBSOCKET"}
                for method in methods:
                    key = (str(method), str(path))
                    name = str(getattr(route, "name", ""))
                    if key in seen:
                        duplicates.append(f"{method} {path} ({seen[key]} / {name})")
                    else:
                        seen[key] = name
            if duplicates:
                fail("duplicate API route(s): " + "; ".join(duplicates))
            print(f"[release] Routes: {len(seen)} method/path pairs, no duplicates")
        finally:
            if old_data_dir is None:
                os.environ.pop("VERBANODE_USER_DATA_DIR", None)
            else:
                os.environ["VERBANODE_USER_DATA_DIR"] = old_data_dir
            if had_frozen:
                sys.frozen = old_frozen
            else:
                delattr(sys, "frozen")
            if had_meipass:
                sys._MEIPASS = old_meipass
            else:
                delattr(sys, "_MEIPASS")


def generated_files() -> list[Path]:
    files: list[Path] = []
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        files.append(env_file)
    for pattern in _GENERATED_PATTERNS:
        files.extend(path for path in PROJECT_ROOT.glob(pattern) if path.is_file())
    # Preserve placeholder files that intentionally keep empty runtime directories.
    return sorted({path for path in files if path.name != ".gitkeep"})


def check_clean_tree() -> None:
    forbidden_files = generated_files()
    if forbidden_files:
        shown = ", ".join(str(path.relative_to(PROJECT_ROOT)) for path in forbidden_files[:12])
        fail(f"generated/private files remain in source tree: {shown}")
    print("[release] Clean-tree private/generated file check OK")


def cleanup_verification_artifacts() -> None:
    """Only called after a clean-tree precheck, so removing new artifacts is safe."""
    for path in generated_files():
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    for directory in sorted(PROJECT_ROOT.rglob("__pycache__"), reverse=True):
        shutil.rmtree(directory, ignore_errors=True)
    shutil.rmtree(PROJECT_ROOT / ".pytest_cache", ignore_errors=True)


def run_pytest(*, clean_tree: bool) -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    command = [sys.executable, "-m", "pytest", "-q"]
    if clean_tree:
        command += ["-p", "no:cacheprovider"]
    subprocess.run(command, cwd=PROJECT_ROOT, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify VerbaNode release invariants")
    parser.add_argument("--full", action="store_true", help="also run the complete pytest suite")
    parser.add_argument(
        "--clean-tree",
        action="store_true",
        help="require a source tree free of generated/private runtime files and clean test artifacts afterwards",
    )
    args = parser.parse_args()

    print(f"[release] VerbaNode v{APP_VERSION} ({BUILD_LABEL})")
    if args.clean_tree:
        check_clean_tree()
    check_version_consistency()
    check_python_compile()
    check_javascript()
    check_routes()
    try:
        if args.full:
            run_pytest(clean_tree=args.clean_tree)
    finally:
        if args.clean_tree:
            cleanup_verification_artifacts()
    if args.clean_tree:
        check_clean_tree()
    print("[release] Verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
