from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_information_and_plugin_explorer_views_are_present() -> None:
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    for target in ("information", "plugins"):
        assert f'data-view-target="{target}"' in html
        assert f'data-explorer-view="{target}"' in html

    for mode in ("cards", "list", "details"):
        assert f'data-view-mode="{mode}"' in html
        assert f'view-{mode}' in css

    assert "function applyExplorerView" in javascript
    assert "function initializeExplorerViews" in javascript
    assert "localStorage.setItem(explorerViewKey(target), resolved)" in javascript
    assert ".information-details-head" in css
    assert ".plugin-details-head" in css
