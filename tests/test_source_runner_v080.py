from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_nested_python_helpers_bootstrap_repository_root() -> None:
    helpers = [
        ROOT / "scripts" / "windows" / "generate_local_cert.py",
        ROOT / "scripts" / "windows" / "test_audio.py",
        ROOT / "scripts" / "setup" / "setup_database.py",
    ]
    for helper in helpers:
        source = helper.read_text(encoding="utf-8")
        assert "Path(__file__).resolve().parents[2]" in source, helper
        assert "sys.path.insert(0, str(PROJECT_ROOT))" in source, helper


def test_nested_batch_helpers_export_repository_pythonpath() -> None:
    wrappers = [
        ROOT / "scripts" / "windows" / "test_audio.bat",
        ROOT / "scripts" / "setup" / "setup_database.bat",
    ]
    for wrapper in wrappers:
        source = wrapper.read_text(encoding="utf-8")
        assert "PYTHONPATH=%CD%" in source, wrapper
