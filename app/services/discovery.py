from __future__ import annotations

import json
import logging
import socket
import threading
from typing import Any

from app.config import Settings
from app.services.https_cert import certificate_spki_sha256, discover_ipv4_addresses

LOGGER = logging.getLogger(__name__)
SERVICE_TYPE = "_verbanode._tcp.local."
ACTIVE_DISCOVERY_PROTOCOL_VERSION = 1
ACTIVE_DISCOVERY_MAGIC = f"VERBANODE_DISCOVER/{ACTIVE_DISCOVERY_PROTOCOL_VERSION}".encode("ascii")


def is_active_discovery_request(payload: bytes) -> bool:
    return payload == ACTIVE_DISCOVERY_MAGIC


def build_active_discovery_response(
    *,
    instance_id: str,
    instance_name: str,
    version: str,
    https_port: int,
    api_version: int,
    ws_version: int,
    spki_sha256: str,
) -> dict[str, Any]:
    return {
        "product": "VerbaNode",
        "discovery_protocol": ACTIVE_DISCOVERY_PROTOCOL_VERSION,
        "instance_id": str(instance_id),
        "instance_name": str(instance_name),
        "version": str(version),
        "https_port": int(https_port),
        "api_version": int(api_version),
        "websocket_protocol_version": int(ws_version),
        "spki_sha256": str(spki_sha256).lower(),
    }


class LanDiscoveryAdvertiser:
    """Advertise VerbaNode over mDNS and answer credential-free UDP probes."""

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
        self._udp_socket: socket.socket | None = None
        self._udp_thread: threading.Thread | None = None
        self._udp_stop = threading.Event()
        self._udp_port: int | None = None

    def _public_discovery_payload(self) -> dict[str, Any]:
        hostname = socket.gethostname().strip() or "VerbaNode"
        return build_active_discovery_response(
            instance_id=self.instance_id,
            instance_name=hostname,
            version=self.version,
            https_port=int(self.settings.port),
            api_version=self.api_version,
            ws_version=self.ws_version,
            spki_sha256=certificate_spki_sha256(),
        )

    def start_active_udp(self) -> bool:
        with self._lock:
            if self._udp_socket is not None:
                return True
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                udp.bind(("0.0.0.0", int(self.settings.lan_discovery_udp_port)))
                udp.settimeout(0.5)
            except Exception:
                udp.close()
                LOGGER.exception(
                    "Failed to bind VerbaNode active discovery UDP port %s",
                    self.settings.lan_discovery_udp_port,
                )
                return False
            self._udp_socket = udp
            self._udp_port = int(udp.getsockname()[1])
            self._udp_stop.clear()
            thread = threading.Thread(
                target=self._active_udp_loop,
                name="VerbaNodeDiscoveryUDP",
                daemon=True,
            )
            self._udp_thread = thread
            thread.start()
            LOGGER.info("Active LAN discovery listening on UDP %s", self._udp_port)
            return True

    def _active_udp_loop(self) -> None:
        while not self._udp_stop.is_set():
            with self._lock:
                udp = self._udp_socket
            if udp is None:
                return
            try:
                payload, sender = udp.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                if self._udp_stop.is_set():
                    return
                LOGGER.debug("Active discovery UDP receive failed", exc_info=True)
                continue
            if not is_active_discovery_request(payload):
                continue
            try:
                body = json.dumps(
                    self._public_discovery_payload(),
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode("utf-8")
                udp.sendto(body, sender)
            except Exception:
                LOGGER.debug("Active discovery response failed for %s", sender, exc_info=True)

    def start(self) -> bool:
        # UDP and mDNS are intentionally independent. One can keep discovery
        # working when a router, OS service, or optional dependency breaks the other.
        udp_started = self.start_active_udp()
        with self._lock:
            if self._zeroconf is not None:
                return True
            try:
                from zeroconf import ServiceInfo, Zeroconf
            except ImportError:
                LOGGER.warning("zeroconf is not installed; mDNS advertisement is disabled")
                return udp_started
            addresses = [address for _interface, address in discover_ipv4_addresses()]
            if not addresses:
                LOGGER.warning("No LAN IPv4 address is available for mDNS advertisement")
                return udp_started
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
                b"udp": str(self._udp_port or self.settings.lan_discovery_udp_port).encode(),
                b"discovery": str(ACTIVE_DISCOVERY_PROTOCOL_VERSION).encode(),
            }
            zc: Any = None
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
                    if zc is not None:
                        zc.close()
                except Exception:
                    pass
                return udp_started
            self._zeroconf = zc
            self._service_info = info
            self.registered_name = str(info.name)
            LOGGER.info("LAN discovery active as %s on TCP %s", self.registered_name, self.settings.port)
            return True

    def stop(self) -> None:
        with self._lock:
            zc = self._zeroconf
            info = self._service_info
            self._zeroconf = None
            self._service_info = None
            self.registered_name = None
            udp = self._udp_socket
            udp_thread = self._udp_thread
            self._udp_socket = None
            self._udp_thread = None
            self._udp_stop.set()
            self._udp_port = None
        if udp is not None:
            try:
                udp.close()
            except Exception:
                LOGGER.debug("Active discovery UDP close failed", exc_info=True)
        if udp_thread is not None and udp_thread is not threading.current_thread():
            udp_thread.join(timeout=1.0)
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
        with self._lock:
            mdns_enabled = self._zeroconf is not None
            udp_enabled = self._udp_socket is not None
            udp_port = self._udp_port
        return {
            # `enabled` is preserved for existing clients and now means at least
            # one LAN discovery transport is active.
            "enabled": mdns_enabled or udp_enabled,
            "mdns_enabled": mdns_enabled,
            "service_type": SERVICE_TYPE,
            "service_name": self.registered_name,
            "port": int(self.settings.port),
            "active_udp_enabled": udp_enabled,
            "active_udp_port": udp_port,
            "active_udp_protocol_version": ACTIVE_DISCOVERY_PROTOCOL_VERSION,
            "certificate_spki_sha256": certificate_spki_sha256(),
        }
