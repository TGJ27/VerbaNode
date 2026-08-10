from __future__ import annotations

import threading

# Process-local signal shared by the FastAPI app and the Uvicorn wrapper in
# launcher.py. It is intentionally not a multiprocessing.Event: only the server
# process needs to observe it.
shutdown_requested = threading.Event()


def request_shutdown() -> None:
    shutdown_requested.set()
