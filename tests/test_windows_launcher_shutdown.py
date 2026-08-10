from __future__ import annotations

from pathlib import Path

from app.process_control import request_shutdown, shutdown_requested


def test_process_control_shutdown_event_is_idempotent() -> None:
    shutdown_requested.clear()
    assert shutdown_requested.is_set() is False
    request_shutdown()
    assert shutdown_requested.is_set() is True
    request_shutdown()
    assert shutdown_requested.is_set() is True
    shutdown_requested.clear()


def test_frozen_launcher_uses_graceful_shutdown_before_tree_kill() -> None:
    source = (Path(__file__).parents[1] / "launcher.py").read_text(encoding="utf-8")
    assert "/internal/launcher/shutdown" in source
    assert "VERBANODE_LAUNCHER_SHUTDOWN_TOKEN" in source
    assert '["taskkill", "/PID", str(process.pid), "/T", "/F"]' in source
    assert "process.terminate()" not in source[source.index("    def stop_server"):source.index("    def restart_server")]


def test_launcher_exit_marks_shutdown_before_stopping() -> None:
    source = (Path(__file__).parents[1] / "launcher.py").read_text(encoding="utf-8")
    block = source[source.index("    def exit_app"):source.index("    def run(self)")]
    assert "self.exiting = True" in block
    assert block.index("self.exiting = True") < block.index("self.stop_server()")
