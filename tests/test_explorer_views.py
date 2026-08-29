from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_knowledge_replaces_legacy_information_and_plugin_explorer_remains() -> None:
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "js" / "runtime.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    assert 'data-page="knowledge"' in html
    assert 'id="page-knowledge"' in html
    assert 'data-page="information"' not in html
    assert 'id="page-information"' not in html
    assert 'data-view-target="information"' not in html
    assert 'data-explorer-view="information"' not in html

    assert 'data-view-target="plugins"' in html
    assert 'data-explorer-view="plugins"' in html
    for mode in ("cards", "list", "details"):
        assert f'data-view-mode="{mode}"' in html
    # Plugin cards use the normal card grid as their default mode; only list
    # and details need mode-specific CSS. The retired Information CSS must not
    # be kept merely to satisfy a generic `view-cards` string check.
    for mode in ("list", "details"):
        assert f'#pluginGrid.view-{mode}' in css

    assert "function applyExplorerView" in javascript
    assert "localStorage.setItem(explorerViewKey(target), resolved)" in javascript
    assert ".plugin-details-head" in css
