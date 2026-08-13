from pathlib import Path

from app.version import APP_VERSION, BUILD_LABEL

ROOT = Path(__file__).resolve().parents[1]


def test_diagnostics_bootstrap_capability_and_version_guard_are_present() -> None:
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    system_api = (ROOT / "app" / "api" / "system.py").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    diagnostics_js = (ROOT / "app" / "static" / "js" / "diagnostics.js").read_text(encoding="utf-8")
    assert '"diagnostics": True' in system_api
    assert '"diagnostics_api_version": 1' in system_api
    assert "function diagnosticsBackendSupported" in javascript
    assert "function renderDiagnosticsUnavailable" in javascript
    assert "error.status = response.status" in javascript
    assert "The diagnostics API returned 404 Not Found" in diagnostics_js
    assert "version-mismatch" in javascript


def test_diagnostics_cards_use_consistent_alignment() -> None:
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    assert html.count("diagnostic-skeleton") == 4
    assert html.count("diagnostic-panel-card") == 4
    assert ".diagnostics-control-grid,.diagnostics-detail-grid" in css
    assert "align-items:stretch" in css
    assert ".diagnostic-compatibility-card" in css
    assert APP_VERSION == "0.8.2"
    assert BUILD_LABEL == "capability-foundation"
