from __future__ import annotations

from pathlib import Path

import pytest

from app import setup_cli


def test_ollama_model_name_validation() -> None:
    assert setup_cli._safe_model_name("qwen3.5:0.8b") == "qwen3.5:0.8b"
    assert setup_cli._safe_model_name("org/model-name:tag") == "org/model-name:tag"
    with pytest.raises(ValueError):
        setup_cli._safe_model_name('bad model & calc.exe')


def test_setup_parser_dispatches_health_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_cli, "health_check", lambda: 17)
    assert setup_cli.run_from_argv(["--setup-health-check"]) == 17


def test_whisper_selection_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    prepared: list[str] = []
    monkeypatch.setattr(setup_cli, "ensure_runtime_layout", lambda: None)
    monkeypatch.setattr(setup_cli, "_prepare_whisper", prepared.append)
    assert setup_cli.download_whisper("both") == 0
    assert prepared == ["Whisper-base", "Whisper-small"]
    with pytest.raises(ValueError):
        setup_cli.download_whisper("large")


def test_sensevoice_download_skips_existing_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_cli, "ensure_runtime_layout", lambda: None)
    monkeypatch.setattr(
        setup_cli,
        "sensevoice_cache_status",
        lambda: {"downloaded": True, "path": "C:/cache/model.pt"},
    )
    assert setup_cli.download_sensevoice() == 0


def test_ollama_pull_skips_existing_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(setup_cli, "_ensure_ollama_running", lambda: None)
    monkeypatch.setattr(setup_cli, "ollama_model_installed", lambda _name: True)
    assert setup_cli.pull_ollama_model("qwen3.5:0.8b") == 0


def test_final_icon_exists_and_is_ico() -> None:
    icon = Path("packaging/assets/VerbaNode.ico")
    assert icon.exists()
    assert icon.read_bytes()[:4] == b"\x00\x00\x01\x00"
