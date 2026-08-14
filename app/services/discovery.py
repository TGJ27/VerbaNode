from __future__ import annotations

import logging
import socket
import threading
from typing import Any

from app.config import Settings
from app.services.https_cert import certificate_spki_sha256, discover_ipv4_addresses

LOGGER = logging.getLogger(__name__)
SERVICE_TYPE = "_verbanode._tcp.local."


class LanDiscoveryAdvertiser:
    """Best-effort mDNS/DNS-SD advertisement for local VerbaNode clients."""

    def __init__(self, settings: Settings, *, instance_id: str, version: str, api_version: int, ws_version: int):
        self.settings = settings
        self.instance_id = instance_id
        self.version = version
        self.api_version = api_version
        self.ws_version = ws_version
        self._lock = threading.RLock()
        self._zeroconf: Any = None
        self._service_info: Any = None
        self.registered_name: str | None = None

    def start(self) -> bool:
        with self._lock:
            if self._zeroconf is not None:
                return True
            try:
                from zeroconf import ServiceInfo, Zeroconf
            except ImportError:
                LOGGER.warning("zeroconf is not installed; LAN discovery advertisement is disabled")
                return False
            addresses = [address for _interface, address in discover_ipv4_addresses()]
            if not addresses:
                LOGGER.warning("No LAN IPv4 address is available for mDNS advertisement")
                return False
            hostname = socket.gethostname().strip() or "VerbaNode"
            service_name = f"VerbaNode {hostname}.{SERVICE_TYPE}"
            properties = {
                b"product": b"VerbaNode",
                b"version": self.version.encode(),
                b"api": str(self.api_version).encode(),
                b"ws": str(self.ws_version).encode(),
                b"tls": b"1",
                b"instance_id": self.instance_id.encode(),
                b"spki": certificate_spki_sha256().encode(),
            }
            try:
                info = ServiceInfo(
                    SERVICE_TYPE,
                    service_name,
                    addresses=[socket.inet_aton(value) for value in addresses],
                    port=int(self.settings.port),
                    properties=properties,
                    server=f"{hostname}.local.",
                )
                zc = Zeroconf()
                zc.register_service(info, allow_name_change=True)
            except Exception:
                LOGGER.exception("Failed to register VerbaNode mDNS service")
                try:
                    zc.close()  # type: ignore[name-defined]
                except Exception:
                    pass
                return False
            self._zeroconf = zc
            self._service_info = info
            self.registered_name = str(info.name)
            LOGGER.info("LAN discovery active as %s on port %s", self.registered_name, self.settings.port)
            return True

    def stop(self) -> None:
        with self._lock:
            zc = self._zeroconf
            info = self._service_info
            self._zeroconf = None
            self._service_info = None
            self.registered_name = None
        if zc is None:
            return
        try:
            if info is not None:
                zc.unregister_service(info)
        except Exception:
            LOGGER.debug("mDNS unregister failed", exc_info=True)
        finally:
            try:
                zc.close()
            except Exception:
                LOGGER.debug("mDNS close failed", exc_info=True)

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self._zeroconf is not None,
            "service_type": SERVICE_TYPE,
            "service_name": self.registered_name,
            "port": int(self.settings.port),
            "certificate_spki_sha256": certificate_spki_sha256(),
        }
