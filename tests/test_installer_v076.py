from __future__ import annotations

from pathlib import Path


def test_online_installer_has_model_wizard_and_upgrade_safe_paths() -> None:
    text = Path("packaging/VerbaNode.iss").read_text(encoding="utf-8")
    assert 'SetupIconFile=assets\\VerbaNode.ico' in text
    assert 'English - prepare SenseVoiceSmall' in text
    assert 'Bahasa Indonesia - prepare OpenAI Whisper through FunASR' in text
    assert 'Whisper Base + Small' in text
    assert 'Download Kokoro local TTS model' in text
    assert 'Install/configure Ollama local LLM runtime' in text
    assert 'https://ollama.com/download/OllamaSetup.exe' in text
    assert '--setup-database' in text
    assert '--setup-https' in text
    assert '--setup-download-sensevoice' in text
    assert '--setup-download-whisper ' in text
    assert '--setup-download-kokoro' in text
    assert '--setup-ollama-pull' in text


def test_installer_detects_updates_and_does_not_reinstall_models_by_default() -> None:
    text = Path("packaging/VerbaNode.iss").read_text(encoding="utf-8")
    assert 'function DetectExistingInstall(): Boolean;' in text
    assert 'DisplayVersion' in text
    assert 'Update application only (recommended) - keep current AI models and components' in text
    assert 'Update application and review/add AI components' in text
    assert 'function ShouldConfigureComponents(): Boolean;' in text
    assert 'if not ShouldConfigureComponents() then' in text
    assert 'already-installed models are never downloaded again' in text
    assert 'Existing Kokoro, Ollama and Ollama models are detected and reused instead of reinstalled.' in text


def test_installer_warning_fixes_are_present() -> None:
    text = Path("packaging/VerbaNode.iss").read_text(encoding="utf-8")
    assert '{userstartup}' not in text
    assert '{commonstartup}\\VerbaNode' in text
    assert 'RunOnceId: "VerbaNodeFirewallRemove"' in text


def test_installer_build_output_is_ignored() -> None:
    text = Path(".gitignore").read_text(encoding="utf-8")
    assert "dist-installer/" in text.splitlines()
