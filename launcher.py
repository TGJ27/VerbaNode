from __future__ import annotations

import json
import multiprocessing
import os
import secrets
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn

from app.config import get_settings
from app.paths import CONFIG_DIR, IS_FROZEN, LOG_DIR, ensure_runtime_layout
from app.process_control import shutdown_requested
from app.services.https_cert import CERT_FILE, KEY_FILE, discover_ipv4_addresses, ensure_local_certificate
from app.version import APP_VERSION


def _ssl_context() -> ssl.SSLContext:
    return ssl._create_unverified_context()


def _json_get(url: str, timeout: float = 1.0) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout, context=_ssl_context()) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _json_post(url: str, *, token: str, timeout: float = 2.0) -> bool:
    request = urllib.request.Request(
        url,
        data=b"{}",
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-VerbaNode-Launcher-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            return 200 <= int(response.status) < 300
    except (OSError, urllib.error.URLError):
        return False


def _ollama_ready(url: str) -> bool:
    endpoint = url.rstrip("/") + "/api/tags"
    try:
        with urllib.request.urlopen(endpoint, timeout=1.0) as response:
            return response.status == 200
    except (OSError, urllib.error.URLError):
        return False


def dashboard_urls(port: int) -> list[tuple[str, str]]:
    urls = [("This computer", f"https://127.0.0.1:{port}")]
    for interface, address in discover_ipv4_addresses():
        urls.append((interface, f"https://{address}:{port}"))
    return urls


def _prepare_https_environment() -> tuple[list[str], bool]:
    ensure_runtime_layout()
    cert, key, addresses, generated = ensure_local_certificate()
    os.environ["VERBANODE_SSL_CERTFILE"] = str(cert)
    os.environ["VERBANODE_SSL_KEYFILE"] = str(key)
    return addresses, generated


def run_server() -> None:
    _prepare_https_environment()
    settings = get_settings()
    ssl_enabled = bool(
        settings.ssl_certfile
        and settings.ssl_keyfile
        and settings.ssl_certfile.exists()
        and settings.ssl_keyfile.exists()
    )
    config = uvicorn.Config(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
        ssl_certfile=str(settings.ssl_certfile) if ssl_enabled else None,
        ssl_keyfile=str(settings.ssl_keyfile) if ssl_enabled else None,
    )
    server = uvicorn.Server(config)

    # The frozen launcher controls the server through a local authenticated
    # endpoint. That endpoint sets this process-local event; the watcher then
    # asks Uvicorn to exit normally so FastAPI's shutdown hook can stop the
    # Audio Engine and AI Engine before the server process disappears.
    def watch_for_shutdown() -> None:
        launcher_pid_text = os.environ.get("VERBANODE_LAUNCHER_PID", "").strip()
        launcher_pid = int(launcher_pid_text) if launcher_pid_text.isdigit() else None
        while not shutdown_requested.wait(timeout=1.0):
            if launcher_pid and os.name == "nt":
                try:
                    import psutil
                    if not psutil.pid_exists(launcher_pid):
                        shutdown_requested.set()
                        break
                except Exception:
                    pass
        server.should_exit = True

    threading.Thread(target=watch_for_shutdown, name="VerbaNodeShutdownWatcher", daemon=True).start()
    server.run()


def run_source_mode() -> None:
    # Preserve the existing developer workflow. run_https.bat still generates
    # the certificate before invoking this file; this fallback also makes
    # direct `python launcher.py` safe.
    settings = get_settings()
    if not (
        settings.ssl_certfile
        and settings.ssl_keyfile
        and settings.ssl_certfile.exists()
        and settings.ssl_keyfile.exists()
    ):
        _prepare_https_environment()
        get_settings.cache_clear()
        settings = get_settings()

    desktop_url = f"https://127.0.0.1:{settings.port}"
    network = dashboard_urls(settings.port)
    print("=" * 68)
    print(f"VerbaNode Standalone v{APP_VERSION}")
    print(f"Desktop:      {desktop_url}")
    for label, url in network[1:]:
        print(f"{label + ':':14}{url}")
    print("TTS playback happens on this PC. Voice input can use the host mic or the dashboard device mic.")
    print("HTTPS is enabled for browser-device microphone access.")
    print("=" * 68)

    if settings.open_browser and os.environ.get("PYTEST_CURRENT_TEST") is None:
        threading.Thread(target=lambda: (time.sleep(1.25), webbrowser.open(desktop_url)), daemon=True).start()
    run_server()


class WindowsLauncher:
    """Small native Windows control surface for the frozen VerbaNode app.

    The web dashboard remains the main interface. This launcher intentionally
    mirrors its visual language so the installed application feels like one
    product instead of a generic Tk utility window.
    """

    COLORS = {
        "background": "#F2F6FF",
        "card": "#FFFFFF",
        "row": "#FBFCFF",
        "border": "#DCE5F4",
        "text": "#17213D",
        "muted": "#6C7A9C",
        "primary": "#5363F5",
        "primary_hover": "#4352E7",
        "primary_soft": "#EEF1FF",
        "link": "#365AE8",
        "green": "#188653",
        "green_bg": "#EBFAF1",
        "green_border": "#BFEBD0",
        "amber": "#A86600",
        "amber_bg": "#FFF7E8",
        "amber_border": "#F3DEAF",
        "red": "#D74A61",
        "red_bg": "#FFF0F2",
        "red_border": "#F4C8D0",
        "gray": "#64748B",
        "gray_bg": "#F1F5F9",
        "gray_border": "#D8E0EA",
    }

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import messagebox

        try:
            import customtkinter as ctk
        except ImportError as exc:  # pragma: no cover - packaging guard
            fallback = tk.Tk()
            fallback.withdraw()
            messagebox.showerror(
                "VerbaNode Launcher",
                "The packaged launcher UI dependency is missing. Rebuild VerbaNode with build_windows.bat.",
                parent=fallback,
            )
            fallback.destroy()
            raise RuntimeError("customtkinter is required by the frozen launcher") from exc

        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.tk = tk
        self.ctk = ctk
        self.messagebox = messagebox
        ensure_runtime_layout()
        _prepare_https_environment()
        get_settings.cache_clear()
        self.settings = get_settings()
        self.server: subprocess.Popen[str] | None = None
        self.log_handle = None
        self.last_ready = False
        self.auto_opened = False
        self.exiting = False
        self.shutdown_token = secrets.token_urlsafe(32)
        self.config_file = CONFIG_DIR / "launcher.json"
        self.preferences = self._load_preferences()

        self.root = ctk.CTk()
        self.root.title(f"VerbaNode {APP_VERSION}")
        self.root.configure(fg_color=self.COLORS["background"])
        self.root.protocol("WM_DELETE_WINDOW", self._minimize)

        # The launcher is intentionally a fixed control panel rather than a
        # resizable application window. Size it once from the current display
        # so the complete control surface remains visible even on laptops or
        # Windows installations using high DPI scaling.
        self._configure_fixed_window()

        self.status_vars = {
            "core": tk.StringVar(master=self.root, value="Starting"),
            "audio": tk.StringVar(master=self.root, value="Waiting"),
            "ai": tk.StringVar(master=self.root, value="Waiting"),
            "ollama": tk.StringVar(master=self.root, value="Checking"),
        }
        self.status_badges: dict[str, Any] = {}
        self.auto_open_var = tk.BooleanVar(
            master=self.root,
            value=bool(self.preferences.get("auto_open_dashboard", True)),
        )
        self.pin_visible = False
        self.pin_var = tk.StringVar(master=self.root, value="•" * max(4, len(str(self.settings.pin))))
        self.note_var = tk.StringVar(master=self.root, value="Starting HTTPS services…")
        self._build_ui()
        self.start_server()
        self.root.after(700, self._poll)

    def _configure_fixed_window(self) -> None:
        # Tk reports geometry in the coordinate system appropriate for the
        # current Windows DPI context, which makes these values suitable for
        # both 100% and scaled displays. Keep a small safety margin for the
        # taskbar and window chrome.
        screen_width = max(800, int(self.root.winfo_screenwidth()))
        screen_height = max(600, int(self.root.winfo_screenheight()))

        # Keep the launcher compact enough that the complete control panel is
        # visible at once. The font scale deliberately has a readable minimum
        # on laptop/small displays instead of shrinking text to make the layout
        # fit. CustomTkinter still applies the native Windows DPI scale on top.
        if screen_width <= 1366 or screen_height <= 768:
            self.font_scale = 1.45
        elif screen_width <= 1600 or screen_height <= 900:
            self.font_scale = 1.35
        else:
            self.font_scale = 1.28

        available_width = max(760, screen_width - 32)
        available_height = max(500, screen_height - 90)
        target_width = min(980, available_width)
        target_height = min(585, available_height)

        x = max(0, (screen_width - target_width) // 2)
        y = max(0, (screen_height - target_height) // 2)
        self.root.geometry(f"{target_width}x{target_height}+{x}+{y}")

        # Disables resizing and greys out the native Windows maximize button.
        self.root.resizable(False, False)

    def _load_preferences(self) -> dict[str, Any]:
        try:
            return json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"auto_open_dashboard": True}

    def _save_preferences(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"auto_open_dashboard": bool(self.auto_open_var.get())}
        self.config_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _font(self, size: int, weight: str = "normal"):
        # Never make the fixed launcher compensate for a smaller screen by
        # making text smaller.  Even the smallest labels gain at least one
        # logical pixel, while laptop-class displays get a larger readability
        # boost. Windows/CustomTkinter DPI scaling is applied separately.
        scale = float(getattr(self, "font_scale", 1.28))
        scaled_size = max(size + 2, int(round(size * scale)))
        return self.ctk.CTkFont(family="Segoe UI", size=scaled_size, weight=weight)

    def _card(self, parent, *, corner_radius: int = 18):
        return self.ctk.CTkFrame(
            parent,
            fg_color=self.COLORS["card"],
            border_width=1,
            border_color=self.COLORS["border"],
            corner_radius=corner_radius,
        )

    def _section_header(self, parent, icon: str, title: str, subtitle: str | None = None) -> None:
        ctk = self.ctk
        heading = ctk.CTkFrame(parent, fg_color="transparent")
        heading.pack(fill="x", padx=14, pady=(8, 4 if subtitle else 6))
        ctk.CTkLabel(
            heading,
            text=icon,
            width=24,
            height=24,
            corner_radius=8,
            fg_color=self.COLORS["primary_soft"],
            text_color=self.COLORS["primary"],
            font=self._font(12, "bold"),
        ).pack(side="left")
        text_area = ctk.CTkFrame(heading, fg_color="transparent")
        text_area.pack(side="left", fill="x", expand=True, padx=(10, 0))
        ctk.CTkLabel(
            text_area,
            text=title,
            text_color=self.COLORS["text"],
            font=self._font(15, "bold"),
            anchor="w",
        ).pack(anchor="w")
        if subtitle:
            ctk.CTkLabel(
                text_area,
                text=subtitle,
                text_color=self.COLORS["muted"],
                font=self._font(10),
                anchor="w",
            ).pack(anchor="w", pady=(1, 0))

    def _build_ui(self) -> None:
        ctk = self.ctk
        root = self.root

        outer = ctk.CTkFrame(root, fg_color="transparent")
        outer.pack(fill="both", expand=True, padx=14, pady=8)

        # Product header -----------------------------------------------------
        top = ctk.CTkFrame(outer, fg_color="transparent", height=48)
        top.pack(fill="x", pady=(0, 6))
        top.pack_propagate(False)
        logo = ctk.CTkLabel(
            top,
            text="VN",
            width=42,
            height=42,
            corner_radius=12,
            fg_color=self.COLORS["primary"],
            text_color="#FFFFFF",
            font=self._font(15, "bold"),
        )
        logo.pack(side="left")
        title_wrap = ctk.CTkFrame(top, fg_color="transparent")
        title_wrap.pack(side="left", fill="x", expand=True, padx=(11, 0))
        ctk.CTkLabel(
            title_wrap,
            text="VerbaNode",
            text_color=self.COLORS["text"],
            font=self._font(23, "bold"),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            title_wrap,
            text="Local AI voice assistant services and dashboard",
            text_color=self.COLORS["muted"],
            font=self._font(10),
            anchor="w",
        ).pack(anchor="w")
        ctk.CTkLabel(
            top,
            text=f"v{APP_VERSION}",
            height=22,
            corner_radius=12,
            fg_color=self.COLORS["primary_soft"],
            text_color=self.COLORS["primary"],
            font=self._font(10, "bold"),
        ).pack(side="right", ipadx=10)

        # Put the two information-heavy cards side by side. This removes the
        # vertical overflow that occurred when Services and Addresses were
        # stacked, while keeping the same dashboard visual language.
        overview = ctk.CTkFrame(outer, fg_color="transparent")
        overview.pack(fill="x", pady=(0, 6))
        overview.grid_columnconfigure(0, weight=1, uniform="overview")
        overview.grid_columnconfigure(1, weight=1, uniform="overview")

        # Service health card ----------------------------------------------
        health = self._card(overview, corner_radius=16)
        health.configure(height=204)
        health.grid_propagate(False)
        health.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        self._section_header(health, "S", "Services")
        services = ctk.CTkFrame(health, fg_color=self.COLORS["row"], corner_radius=11)
        services.pack(fill="x", padx=11, pady=(0, 7))
        service_defs = (
            ("VerbaNode Core", "core", "VN"),
            ("Audio Engine", "audio", "AU"),
            ("AI Engine", "ai", "AI"),
            ("Ollama", "ollama", "OL"),
        )
        for index, (label, key, short) in enumerate(service_defs):
            row = ctk.CTkFrame(services, fg_color="transparent", height=40)
            row.pack(fill="x", padx=6, pady=(2 if index == 0 else 0, 1))
            row.pack_propagate(False)
            ctk.CTkLabel(
                row,
                text=short,
                width=26,
                height=26,
                corner_radius=8,
                fg_color=self.COLORS["primary_soft"],
                text_color=self.COLORS["primary"],
                font=self._font(8, "bold"),
            ).pack(side="left")
            ctk.CTkLabel(
                row,
                text=label,
                text_color=self.COLORS["text"],
                font=self._font(10, "bold"),
                anchor="w",
            ).pack(side="left", padx=(9, 0))
            badge = ctk.CTkLabel(
                row,
                textvariable=self.status_vars[key],
                width=82,
                height=24,
                corner_radius=11,
                fg_color=self.COLORS["gray_bg"],
                text_color=self.COLORS["gray"],
                font=self._font(8, "bold"),
            )
            badge.pack(side="right")
            self.status_badges[key] = badge

        # Addresses card ----------------------------------------------------
        dash = self._card(overview, corner_radius=16)
        dash.configure(height=204)
        dash.grid_propagate(False)
        dash.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self._section_header(
            dash,
            "@",
            "Dashboard addresses",
            "Open on this PC or another device on the same network.",
        )
        self.address_frame = ctk.CTkScrollableFrame(
            dash,
            fg_color="transparent",
            height=115,
            corner_radius=0,
            scrollbar_button_color=self.COLORS["border"],
            scrollbar_button_hover_color="#C7D2E8",
        )
        self.address_frame.pack(fill="x", padx=11, pady=(0, 8))
        self._render_addresses()

        # PIN card ----------------------------------------------------------
        access = self._card(outer, corner_radius=15)
        access.pack(fill="x", pady=(0, 6))
        access_row = ctk.CTkFrame(access, fg_color="transparent", height=50)
        access_row.pack(fill="x", padx=12, pady=6)
        access_row.pack_propagate(False)
        ctk.CTkLabel(
            access_row,
            text="#",
            width=24,
            height=24,
            corner_radius=8,
            fg_color=self.COLORS["primary_soft"],
            text_color=self.COLORS["primary"],
            font=self._font(11, "bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            access_row,
            text="Dashboard PIN",
            width=110,
            text_color=self.COLORS["text"],
            font=self._font(11, "bold"),
            anchor="w",
        ).pack(side="left", padx=(9, 0))
        pin_field = ctk.CTkFrame(
            access_row,
            fg_color=self.COLORS["row"],
            border_width=1,
            border_color=self.COLORS["border"],
            corner_radius=9,
            height=34,
        )
        pin_field.pack(side="left", fill="x", expand=True, padx=(6, 10))
        pin_field.pack_propagate(False)
        ctk.CTkLabel(
            pin_field,
            textvariable=self.pin_var,
            text_color=self.COLORS["text"],
            font=self._font(11, "bold"),
            anchor="w",
        ).pack(side="left", padx=12)
        self.pin_toggle_button = ctk.CTkButton(
            access_row,
            text="Show PIN",
            width=86,
            height=34,
            corner_radius=9,
            fg_color="#FFFFFF",
            hover_color=self.COLORS["primary_soft"],
            border_width=1,
            border_color=self.COLORS["border"],
            text_color=self.COLORS["text"],
            font=self._font(10, "bold"),
            command=self._toggle_pin,
        )
        self.pin_toggle_button.pack(side="right")
        ctk.CTkButton(
            access_row,
            text="Copy PIN",
            width=88,
            height=34,
            corner_radius=9,
            fg_color=self.COLORS["primary"],
            hover_color=self.COLORS["primary_hover"],
            text_color="#FFFFFF",
            font=self._font(10, "bold"),
            command=self._copy_pin,
        ).pack(side="right", padx=(0, 7))

        # Primary actions ---------------------------------------------------
        controls = ctk.CTkFrame(outer, fg_color="transparent", height=40)
        controls.pack(fill="x", pady=(1, 4))
        controls.pack_propagate(False)
        ctk.CTkCheckBox(
            controls,
            text="Open dashboard automatically when ready",
            variable=self.auto_open_var,
            command=self._save_preferences,
            width=26,
            height=20,
            corner_radius=6,
            border_width=2,
            fg_color=self.COLORS["primary"],
            hover_color=self.COLORS["primary_hover"],
            border_color="#B9C5DF",
            text_color=self.COLORS["text"],
            font=self._font(10),
        ).pack(side="left")
        ctk.CTkButton(
            controls,
            text="Exit",
            width=70,
            height=31,
            corner_radius=9,
            fg_color="#FFFFFF",
            hover_color=self.COLORS["red_bg"],
            border_width=1,
            border_color=self.COLORS["border"],
            text_color=self.COLORS["text"],
            font=self._font(10, "bold"),
            command=self.exit_app,
        ).pack(side="right")
        ctk.CTkButton(
            controls,
            text="Minimize",
            width=76,
            height=31,
            corner_radius=9,
            fg_color="#FFFFFF",
            hover_color=self.COLORS["primary_soft"],
            border_width=1,
            border_color=self.COLORS["border"],
            text_color=self.COLORS["text"],
            font=self._font(10, "bold"),
            command=self._minimize,
        ).pack(side="right", padx=(0, 6))
        ctk.CTkButton(
            controls,
            text="Restart services",
            width=104,
            height=31,
            corner_radius=9,
            fg_color="#FFFFFF",
            hover_color=self.COLORS["primary_soft"],
            border_width=1,
            border_color=self.COLORS["border"],
            text_color=self.COLORS["text"],
            font=self._font(10, "bold"),
            command=self.restart_server,
        ).pack(side="right", padx=(0, 6))
        ctk.CTkButton(
            controls,
            text="Open dashboard",
            width=118,
            height=31,
            corner_radius=9,
            fg_color=self.COLORS["primary"],
            hover_color=self.COLORS["primary_hover"],
            text_color="#FFFFFF",
            font=self._font(10, "bold"),
            command=lambda: self._open_url(f"https://127.0.0.1:{self.settings.port}"),
        ).pack(side="right", padx=(0, 6))

        # Footer ------------------------------------------------------------
        bottom = ctk.CTkFrame(outer, fg_color="transparent", height=22)
        bottom.pack(fill="x")
        bottom.pack_propagate(False)
        ctk.CTkLabel(
            bottom,
            text="●",
            width=12,
            text_color="#32B974",
            font=self._font(9, "bold"),
        ).pack(side="left")
        ctk.CTkLabel(
            bottom,
            textvariable=self.note_var,
            text_color=self.COLORS["muted"],
            font=self._font(9),
            anchor="w",
        ).pack(side="left", padx=(3, 0))

    def _render_addresses(self) -> None:
        ctk = self.ctk
        for child in self.address_frame.winfo_children():
            child.destroy()

        addresses = dashboard_urls(self.settings.port)
        for index, (label, url) in enumerate(addresses):
            row = ctk.CTkFrame(
                self.address_frame,
                fg_color=self.COLORS["row"],
                border_width=1,
                border_color=self.COLORS["border"],
                corner_radius=9,
                height=54,
            )
            row.pack(fill="x", pady=(0, 4 if index < len(addresses) - 1 else 0))
            row.pack_propagate(False)
            icon_text = "PC" if label == "This computer" else "Wi"
            ctk.CTkLabel(
                row,
                text=icon_text,
                width=29,
                height=29,
                corner_radius=8,
                fg_color=self.COLORS["primary_soft"],
                text_color=self.COLORS["primary"],
                font=self._font(9, "bold"),
            ).pack(side="left", padx=(7, 8))
            left = ctk.CTkFrame(row, fg_color="transparent")
            left.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(
                left,
                text=label,
                text_color=self.COLORS["text"],
                font=self._font(10, "bold"),
                anchor="w",
            ).pack(anchor="w")
            ctk.CTkLabel(
                left,
                text=url,
                text_color=self.COLORS["link"],
                font=self._font(9),
                anchor="w",
            ).pack(anchor="w", pady=(0, 0))
            ctk.CTkButton(
                row,
                text="Copy",
                width=62,
                height=30,
                corner_radius=9,
                fg_color="#FFFFFF",
                hover_color=self.COLORS["primary_soft"],
                border_width=1,
                border_color=self.COLORS["border"],
                text_color=self.COLORS["text"],
                font=self._font(9, "bold"),
                command=lambda value=url: self._copy(value),
            ).pack(side="right", padx=(4, 6))
            ctk.CTkButton(
                row,
                text="Open",
                width=62,
                height=30,
                corner_radius=9,
                fg_color="#FFFFFF",
                hover_color=self.COLORS["primary_soft"],
                border_width=1,
                border_color=self.COLORS["border"],
                text_color=self.COLORS["text"],
                font=self._font(9, "bold"),
                command=lambda value=url: self._open_url(value),
            ).pack(side="right")

    def _set_status(self, key: str, value: str) -> None:
        self.status_vars[key].set(value)
        badge = self.status_badges.get(key)
        if badge is None:
            return
        normalized = value.casefold()
        if normalized in {"ready", "running", "connected"}:
            colors = (self.COLORS["green_bg"], self.COLORS["green"], self.COLORS["green_border"])
        elif normalized in {"starting", "checking", "waiting"}:
            colors = (self.COLORS["amber_bg"], self.COLORS["amber"], self.COLORS["amber_border"])
        elif normalized in {"stopped", "unavailable", "not connected"}:
            colors = (self.COLORS["red_bg"], self.COLORS["red"], self.COLORS["red_border"])
        else:
            colors = (self.COLORS["gray_bg"], self.COLORS["gray"], self.COLORS["gray_border"])
        badge.configure(fg_color=colors[0], text_color=colors[1], border_width=1, border_color=colors[2])

    def _copy(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.note_var.set("Dashboard address copied to clipboard.")

    def _toggle_pin(self) -> None:
        self.pin_visible = not self.pin_visible
        if self.pin_visible:
            self.pin_var.set(str(self.settings.pin))
            self.pin_toggle_button.configure(text="Hide PIN")
        else:
            self.pin_var.set("•" * max(4, len(str(self.settings.pin))))
            self.pin_toggle_button.configure(text="Show PIN")

    def _copy_pin(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(str(self.settings.pin))
        self.note_var.set("Controller PIN copied to clipboard.")

    @staticmethod
    def _open_url(url: str) -> None:
        webbrowser.open(url)

    def _server_command(self) -> list[str]:
        if IS_FROZEN:
            return [sys.executable, "--server"]
        return [sys.executable, str(Path(__file__).resolve()), "--server"]

    def start_server(self) -> None:
        if self.server and self.server.poll() is None:
            return
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = LOG_DIR / "verbanode-server.log"
        self.log_handle = log_path.open("a", encoding="utf-8", buffering=1)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        env = os.environ.copy()
        env["VERBANODE_SSL_CERTFILE"] = str(CERT_FILE)
        env["VERBANODE_SSL_KEYFILE"] = str(KEY_FILE)
        env["VERBANODE_LAUNCHER_SHUTDOWN_TOKEN"] = self.shutdown_token
        env["VERBANODE_LAUNCHER_PID"] = str(os.getpid())
        self.server = subprocess.Popen(
            self._server_command(),
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            creationflags=creationflags,
        )
        self._set_status("core", "Starting")
        self._set_status("audio", "Waiting")
        self._set_status("ai", "Waiting")
        self.note_var.set(f"Starting HTTPS server. Log: {log_path}")

    def stop_server(self) -> None:
        process = self.server
        self.server = None
        if process and process.poll() is None:
            # Do not terminate the server process first. In a frozen build the
            # Audio/AI multiprocessing children are also VerbaNode.exe. A hard
            # TerminateProcess bypasses FastAPI shutdown and can orphan those
            # children, leaving dist\\VerbaNode locked after the launcher exits.
            graceful = _json_post(
                f"https://127.0.0.1:{self.settings.port}/internal/launcher/shutdown",
                token=self.shutdown_token,
                timeout=2.0,
            )
            if graceful:
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    pass

            if process.poll() is None:
                # Final recovery path only. Kill the complete server tree so a
                # failed shutdown can never leave frozen Audio/AI children behind.
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        pass
                if process.poll() is None:
                    process.kill()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass
        if self.log_handle:
            try:
                self.log_handle.close()
            except OSError:
                pass
            self.log_handle = None

    def restart_server(self) -> None:
        self.note_var.set("Restarting VerbaNode services…")
        self.stop_server()
        time.sleep(0.2)
        self.start_server()

    def _poll(self) -> None:
        if self.exiting:
            return
        if self.server and self.server.poll() is not None:
            self._set_status("core", "Stopped")
            self._set_status("audio", "Unavailable")
            self._set_status("ai", "Unavailable")
            self.note_var.set("VerbaNode stopped unexpectedly. Check the server log or restart services.")
        else:
            health = _json_get(f"https://127.0.0.1:{self.settings.port}/health/launcher")
            if health:
                self._set_status("core", "Ready")
                audio = health.get("audio_engine") or {}
                ai = health.get("ai_engine") or {}
                self._set_status("audio", "Ready" if audio.get("alive") else "Starting")
                self._set_status("ai", "Ready" if ai.get("alive") else "Starting")
                self.note_var.set("HTTPS dashboard is ready.")
                if not self.last_ready:
                    self._render_addresses()
                self.last_ready = True
                if self.auto_open_var.get() and not self.auto_opened:
                    self.auto_opened = True
                    self._open_url(f"https://127.0.0.1:{self.settings.port}")
            else:
                self._set_status("core", "Starting")
                self.last_ready = False
            self._set_status("ollama", "Connected" if _ollama_ready(self.settings.ollama_url) else "Not connected")
        self.root.after(1500, self._poll)

    def _minimize(self) -> None:
        self.root.iconify()

    def exit_app(self) -> None:
        if not self.messagebox.askyesno("Exit VerbaNode", "Stop VerbaNode services and exit?"):
            return
        self.exiting = True
        self.note_var.set("Stopping VerbaNode services…")
        self.root.update_idletasks()
        self.stop_server()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()

def main() -> None:
    setup_args = [arg for arg in sys.argv[1:] if arg.startswith("--setup-")]
    if setup_args:
        from app.setup_cli import run_from_argv
        raise SystemExit(run_from_argv(sys.argv[1:]))
    if "--server" in sys.argv:
        run_server()
        return
    if IS_FROZEN:
        WindowsLauncher().run()
        return
    run_source_mode()


if __name__ == "__main__":
    # PyInstaller specifically requires freeze_support before any application
    # multiprocessing work. In source mode this is a harmless no-op.
    multiprocessing.freeze_support()
    main()
