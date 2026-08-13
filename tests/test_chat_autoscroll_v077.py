from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_chat_has_strict_autoscroll_lock_and_new_message_jump() -> None:
    html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
    javascript = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "app/static/js/runtime.js",
            "app/static/js/chat.js",
            "app/static/app.js",
        )
    )
    css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    assert 'id="autoScrollToggle"' in html
    assert 'id="newMessagesBtn"' in html
    assert "verbanode_chat_auto_scroll" in javascript
    assert "setChatAutoScroll" in javascript
    assert "jumpToNewestMessages" in javascript
    assert "chatUnreadMessages" in javascript
    assert "scroll-locked" in javascript
    assert ".message-list.scroll-locked" in css
    assert "overflow-y: hidden" in css
    assert "touch-action: none" in css
    assert ".new-messages-btn" in css


def test_chat_header_surfaces_active_language_stt_tts_and_model() -> None:
    javascript = (ROOT / "app" / "static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")

    assert "agent-context-chip" in javascript
    assert "agent-context-row" in javascript
    assert "Bahasa Indonesia" in javascript
    assert "agent.stt_model" in javascript
    assert "agent.tts_mode" in javascript
    assert "agent.llm_model" in javascript
    assert ".agent-context-chip" in css
    assert ".agent-context-row" in css
