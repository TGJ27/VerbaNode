from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_repository_cleanup_layout() -> None:
    old_root_helpers = [
        "setup_windows.bat",
        "setup_database.bat",
        "download_funasr.bat",
        "download_whisper.bat",
        "download_kokoro.bat",
        "allow_firewall.bat",
        "test_audio.bat",
        "VerbaNode.spec",
        "requirements-packaging.txt",
        "ICON_HOTFIX_README.txt",
    ]
    for name in old_root_helpers:
        assert not (ROOT / name).exists(), name

    required = [
        ROOT / "scripts" / "setup" / "setup_windows.bat",
        ROOT / "scripts" / "setup" / "setup_database.bat",
        ROOT / "scripts" / "models" / "download_funasr.bat",
        ROOT / "scripts" / "models" / "download_whisper.bat",
        ROOT / "scripts" / "models" / "download_kokoro.bat",
        ROOT / "scripts" / "windows" / "allow_firewall.bat",
        ROOT / "scripts" / "windows" / "test_audio.bat",
        ROOT / "packaging" / "VerbaNode.spec",
        ROOT / "packaging" / "requirements-packaging.txt",
        ROOT / "packaging" / "VerbaNode.iss",
        ROOT / "docs" / "README.md",
        ROOT / "scripts" / "README.md",
        ROOT / "packaging" / "README.md",
    ]
    for path in required:
        assert path.exists(), path


def test_build_scripts_follow_clean_packaging_layout() -> None:
    build = (ROOT / "build_windows.bat").read_text(encoding="utf-8")
    assert "packaging\\requirements-packaging.txt" in build
    assert "packaging\\VerbaNode.spec" in build

    spec = (ROOT / "packaging" / "VerbaNode.spec").read_text(encoding="utf-8")
    assert "ROOT = Path(SPECPATH).resolve().parent" in spec


def test_https_launcher_uses_reorganized_certificate_helper() -> None:
    run_https = (ROOT / "run_https.bat").read_text(encoding="utf-8")
    assert "scripts\\windows\\generate_local_cert.py" in run_https
