from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_launcher_uses_dashboard_style_customtkinter() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "import customtkinter as ctk" in source
    assert '"background": "#F2F6FF"' in source
    assert '"primary": "#5363F5"' in source
    assert 'text="VN"' in source
    assert '"Dashboard addresses"' in source
    assert 'text="Copy PIN"' in source
    assert 'text="Open dashboard"' in source
    assert "corner_radius: int = 18" in source


def test_packaging_includes_customtkinter_assets() -> None:
    requirements = (ROOT / "requirements-packaging.txt").read_text(encoding="utf-8")
    spec = (ROOT / "VerbaNode.spec").read_text(encoding="utf-8")
    assert "customtkinter>=6.0,<7.0" in requirements
    assert '"customtkinter"' in spec


def test_launcher_is_fixed_and_screen_aware() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "def _configure_fixed_window(self)" in source
    assert "self.root.winfo_screenwidth()" in source
    assert "self.root.winfo_screenheight()" in source
    assert "target_width = min(980" in source
    assert "target_height = min(585" in source
    assert "self.root.resizable(False, False)" in source


def test_launcher_single_window_layout_keeps_actions_visible() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert 'overview = ctk.CTkFrame(outer, fg_color="transparent")' in source
    assert 'health.grid(row=0, column=0' in source
    assert 'dash.grid(row=0, column=1' in source
    assert 'height=115' in source
    assert 'text="Open dashboard"' in source
    assert 'text="Restart services"' in source
    assert 'text="Minimize"' in source
    assert 'text="Exit"' in source


def test_launcher_compact_alignment_and_readability() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "health.configure(height=204)" in source
    assert "dash.configure(height=204)" in source
    assert "health.grid_propagate(False)" in source
    assert "dash.grid_propagate(False)" in source
    assert 'font=self._font(23, "bold")' in source
    assert 'font=self._font(15, "bold")' in source
    assert 'row = ctk.CTkFrame(services, fg_color="transparent", height=40)' in source


def test_launcher_fonts_scale_up_for_readability() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "self.font_scale = 1.45" in source
    assert "self.font_scale = 1.35" in source
    assert "self.font_scale = 1.28" in source
    assert "scaled_size = max(size + 2" in source
    assert "screen_width <= 1366 or screen_height <= 768" in source
