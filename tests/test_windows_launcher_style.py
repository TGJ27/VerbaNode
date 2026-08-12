from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_launcher_uses_dashboard_style_customtkinter() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "import customtkinter as ctk" in source
    assert '"background": "#F2F6FF"' in source
    assert '"primary": "#5363F5"' in source
    assert 'resource_path("VerbaNode.png")' in source
    assert 'resource_path("app", "static", "VerbaNode.png")' in source
    assert 'resource_path("packaging", "assets", "VerbaNode.png")' in source
    assert 'text="VN"' not in source
    assert 'self.brand_image = self._load_brand_image(52)' in source
    assert '"Dashboard addresses"' in source
    assert 'text="Copy PIN"' in source
    assert 'text="Open dashboard"' in source
    assert "corner_radius: int = 18" in source


def test_packaging_includes_customtkinter_and_brand_assets() -> None:
    requirements = (ROOT / "packaging" / "requirements-packaging.txt").read_text(encoding="utf-8")
    spec = (ROOT / "packaging" / "VerbaNode.spec").read_text(encoding="utf-8")
    assert "customtkinter==6.0.0" in requirements
    assert "pillow==12.3.0" in requirements.lower()
    assert '"customtkinter"' in spec
    assert '"PIL"' in spec
    assert '"VerbaNode.png"' in spec
    assert '"packaging/assets"' in spec
    assert '(str(ROOT / "packaging" / "assets" / "VerbaNode.png"), ".")' in spec


def test_launcher_has_png_fallback_without_pillow() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "self.tk.PhotoImage(file=str(image_path))" in source
    assert "image.subsample(subsample, subsample)" in source


def test_launcher_rounds_brand_image_corners() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert 'from PIL import ImageChops, ImageDraw' in source
    assert 'min(image.size) * 0.22' in source
    assert 'ImageDraw.Draw(corner_mask).rounded_rectangle(' in source
    assert 'image.putalpha(ImageChops.multiply(existing_alpha, corner_mask))' in source


def test_launcher_is_fixed_and_screen_aware() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "def _configure_fixed_window(self)" in source
    assert "self.root.winfo_screenwidth()" in source
    assert "self.root.winfo_screenheight()" in source
    assert "target_width = min(1000" in source
    assert "target_height = min(535" in source
    assert "self.root.resizable(False, False)" in source


def test_launcher_single_window_layout_keeps_actions_visible() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert 'overview = ctk.CTkFrame(outer, fg_color="transparent")' in source
    assert 'health.grid(row=0, column=0' in source
    assert 'dash.grid(row=0, column=1' in source
    assert 'height=138' in source
    assert 'text="Open dashboard"' in source
    assert 'text="Restart services"' in source
    assert 'text="Minimize"' in source
    assert 'text="Exit"' in source


def test_launcher_alignment_avoids_clipped_header_and_address_rows() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert 'fg_color="transparent", height=66' in source
    assert "health.configure(height=220)" in source
    assert "dash.configure(height=220)" in source
    assert 'row = ctk.CTkFrame(services, fg_color="transparent", height=42)' in source
    assert 'border_color="#CAD6EA"' in source
    assert 'height=62' in source


def test_launcher_fonts_scale_up_for_readability() -> None:
    source = (ROOT / "launcher.py").read_text(encoding="utf-8")
    assert "self.font_scale = 1.45" in source
    assert "self.font_scale = 1.35" in source
    assert "self.font_scale = 1.28" in source
    assert "scaled_size = max(size + 2" in source
    assert "screen_width <= 1366 or screen_height <= 768" in source
