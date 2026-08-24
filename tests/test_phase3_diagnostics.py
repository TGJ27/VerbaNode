from __future__ import annotations

import json
import logging
import time
import zipfile
from pathlib import Path

from app.config import Settings
from app.services.diagnostics import DiagnosticsManager, RingLogHandler
from app.services.pipeline import PipelineMonitor
from app.version import APP_VERSION, BUILD_LABEL


ROOT = Path(__file__).resolve().parents[1]


def test_ring_log_handler_redacts_controller_tokens() -> None:
    handler = RingLogHandler(capacity=20)
    logger = logging.getLogger("verbanode-test-redaction")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info("WebSocket /ws?token=super-secret-value accepted")
        logger.info("STT result confidence=95% text=\'private speech\'")
        logger.info("Queued TTS sentence 2: private assistant response")
    finally:
        logger.removeHandler(handler)
    entries = handler.entries()
    assert len(entries) == 3
    combined = "\n".join(entry["formatted"] for entry in entries)
    assert "super-secret-value" not in combined
    assert "private speech" not in combined
    assert "private assistant response" not in combined
    assert "token=<redacted>" in combined
    assert "<content redacted>" in combined


def test_pipeline_monitor_records_recent_turn_latency() -> None:
    monitor = PipelineMonitor()
    turn = monitor.begin_turn("browser_ptt", audio=True)
    monitor.mark("stt_started")
    time.sleep(0.002)
    monitor.mark("stt_completed")
    monitor.duration("stt_total", "stt_started", "stt_completed")
    monitor.finish_turn()
    history = monitor.recent_turns()
    assert len(history) == 1
    assert history[0]["turn_id"] == turn.turn_id
    assert history[0]["source"] == "browser_ptt"
    assert history[0]["latency_ms"]["stt_total"] >= 0
    assert history[0]["latency_ms"]["turn_total"] >= 0


def test_diagnostics_report_excludes_private_runtime_files(tmp_path: Path) -> None:
    manager = DiagnosticsManager(
        tmp_path / "diagnostics",
        app_version=APP_VERSION,
        build_label=BUILD_LABEL,
    )
    path = manager.create_report(
        {"pipeline": {"state": "idle"}},
        recent_turns=[{"turn_id": "abc", "latency_ms": {"turn_total": 10}}],
        self_test={"overall": "pass", "checks": []},
    )
    assert path.exists()
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert names == {
            "diagnostics.json",
            "recent-logs.txt",
            "recent-turns.json",
            "README.txt",
        }
        report = json.loads(archive.read("diagnostics.json"))
    assert report["privacy"]["environment_file_included"] is False
    assert report["privacy"]["database_included"] is False
    assert report["privacy"]["conversation_content_included"] is False


def test_soak_monitor_can_start_sample_and_stop(tmp_path: Path) -> None:
    manager = DiagnosticsManager(
        tmp_path / "diagnostics",
        app_version=APP_VERSION,
        build_label=BUILD_LABEL,
    )
    samples = 0

    def sample_provider():
        nonlocal samples
        samples += 1
        return {
            "system": {"cpu_percent": 10, "ram_percent": 20},
            "processes": {},
            "audio_restart_count": 0,
            "ai_restart_count": 0,
            "pipeline_errors": 0,
        }

    status = manager.start_soak(
        sample_provider,
        duration_seconds=60,
        interval_seconds=2,
    )
    assert status["active"] is True
    deadline = time.time() + 2
    while samples < 1 and time.time() < deadline:
        time.sleep(0.02)
    stopped = manager.stop_soak()
    assert stopped["active"] is False
    assert stopped["sample_count"] >= 1
    assert stopped["stop_reason"] == "stopped_by_user"


def test_diagnostics_ui_and_endpoints_are_present() -> None:
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    diagnostics_api = (ROOT / "app" / "api" / "diagnostics.py").read_text(encoding="utf-8")
    assert 'data-settings-panel="diagnostics"' in html
    assert 'data-settings-panel-content="diagnostics"' in html
    assert 'id="runDiagnosticSelfTestBtn"' in html
    assert 'id="startSoakTestBtn"' in html
    assert 'id="downloadDiagnosticsBtn"' in html
    assert "function renderDiagnostics" in javascript
    assert '@router.get("/api/diagnostics")' in diagnostics_api
    assert '@router.post("/api/diagnostics/self-test")' in diagnostics_api
    assert '@router.get("/api/diagnostics/export")' in diagnostics_api
    assert APP_VERSION == "0.9.9"


def test_diagnostics_directory_is_runtime_only(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "data" / "test.db",
        tts_cache_path=tmp_path / "cache",
        open_browser=False,
    )
    # The property itself is fixed to the repository runtime directory; verify
    # the package ignore rule rather than creating user data in the source tree.
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "diagnostics/" in ignore
    assert settings.db_path.name == "test.db"
