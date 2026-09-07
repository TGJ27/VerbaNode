from pathlib import Path

from app.config import Settings
from app.db import Database
from app.schemas import ConversationSettingsUpdate
from app.version import APP_VERSION


ROOT = Path(__file__).resolve().parents[1]


def test_rejected_stt_visibility_defaults_and_persists(tmp_path: Path) -> None:
    db = Database(Settings(db_path=tmp_path / "test.db", open_browser=False))
    db.initialize()
    assert db.get_runtime_settings()["show_rejected_stt_transcripts"] is True

    db.set_setting("show_rejected_stt_transcripts", "false")
    assert db.get_runtime_settings()["show_rejected_stt_transcripts"] is False


def test_conversation_settings_schema_exposes_rejected_stt_visibility() -> None:
    payload = ConversationSettingsUpdate(show_rejected_stt_transcripts=False)
    assert payload.show_rejected_stt_transcripts is False


def test_settings_ui_is_split_into_submenus_and_rejected_messages_are_muted() -> None:
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    for panel in ("conversation", "audio", "models", "runtime", "diagnostics", "data"):
        assert f'data-settings-panel="{panel}"' in html
        assert f'data-settings-panel-content="{panel}"' in html

    assert 'id="showRejectedSttToggle"' in html
    assert "show_rejected_stt_transcripts" in javascript
    assert ".message.user.rejected-transcript" in css
    assert ".message-list.hide-rejected-transcripts .rejected-transcript" in css
    assert APP_VERSION == "0.12.3"
