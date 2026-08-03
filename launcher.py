from __future__ import annotations

import os
import socket
import threading
import time
import webbrowser

import uvicorn

from app.config import get_settings
from app.version import APP_VERSION


def local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def open_browser_later(url: str) -> None:
    time.sleep(1.25)
    webbrowser.open(url)


def main() -> None:
    settings = get_settings()
    ssl_enabled = bool(
        settings.ssl_certfile
        and settings.ssl_keyfile
        and settings.ssl_certfile.exists()
        and settings.ssl_keyfile.exists()
    )
    scheme = "https" if ssl_enabled else "http"
    desktop_url = f"{scheme}://127.0.0.1:{settings.port}"
    network_url = f"{scheme}://{local_ip()}:{settings.port}"
    print("=" * 68)
    print(f"VerbaNode Standalone v{APP_VERSION}")
    print(f"Desktop:      {desktop_url}")
    print(f"Local network:{network_url}")
    print("TTS playback happens on this PC. Voice input can use the host mic or the dashboard device mic.")
    if ssl_enabled:
        print("HTTPS is enabled for browser-device microphone access.")
    print("=" * 68)

    if settings.open_browser and os.environ.get("PYTEST_CURRENT_TEST") is None:
        threading.Thread(target=open_browser_later, args=(desktop_url,), daemon=True).start()

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
        ssl_certfile=str(settings.ssl_certfile) if ssl_enabled else None,
        ssl_keyfile=str(settings.ssl_keyfile) if ssl_enabled else None,
    )


if __name__ == "__main__":
    main()
