from __future__ import annotations

import secrets
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.config import Settings


@dataclass
class ControllerSession:
    token: str
    client_name: str
    created_at: float
    last_seen: float


@dataclass
class TakeoverRequest:
    request_id: str
    client_name: str
    created_at: float
    status: str = "pending"
    token: str | None = None


class ControllerManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self.active: ControllerSession | None = None
        self.pending: dict[str, TakeoverRequest] = {}

    def _new_token(self) -> str:
        return secrets.token_urlsafe(32)

    def _active_is_stale(self) -> bool:
        return bool(
            self.active
            and time.monotonic() - self.active.last_seen > self.settings.controller_timeout_seconds
        )

    def login(self, pin: str, client_name: str, force_takeover: bool = False) -> dict[str, Any]:
        if not secrets.compare_digest(pin, self.settings.pin):
            return {"status": "invalid_pin"}
        with self._lock:
            if self._active_is_stale():
                self.active = None
            if self.active is None:
                token = self._new_token()
                now = time.monotonic()
                self.active = ControllerSession(token, client_name, now, now)
                return {"status": "granted", "token": token, "takeover": False}

            previous_client = self.active.client_name
            if not force_takeover:
                return {
                    "status": "takeover_required",
                    "takeover_required": True,
                    "active_client": previous_client,
                }

            # The requester explicitly confirmed takeover after entering the
            # correct PIN. Ownership transfers immediately; the old browser is
            # revoked by the API layer without asking it for approval.
            old_token = self.active.token
            token = self._new_token()
            now = time.monotonic()
            self.active = ControllerSession(token, client_name, now, now)
            self.pending.clear()
            return {
                "status": "granted",
                "token": token,
                "takeover": True,
                "old_token": old_token,
                "previous_client": previous_client,
            }

    def validate(self, token: str | None, touch: bool = True) -> bool:
        if not token:
            return False
        with self._lock:
            if self._active_is_stale():
                self.active = None
                return False
            if self.active and secrets.compare_digest(self.active.token, token):
                if touch:
                    self.active.last_seen = time.monotonic()
                return True
            return False

    def active_token(self) -> str | None:
        with self._lock:
            return self.active.token if self.active else None

    def active_info(self) -> dict[str, Any] | None:
        with self._lock:
            if self._active_is_stale():
                self.active = None
            if not self.active:
                return None
            return {
                "client_name": self.active.client_name,
                "connected_seconds": int(time.monotonic() - self.active.created_at),
            }

    def pending_status(self, request_id: str) -> dict[str, Any]:
        with self._lock:
            req = self.pending.get(request_id)
            if not req:
                return {"status": "not_found"}
            if (
                req.status == "pending"
                and time.monotonic() - req.created_at > self.settings.takeover_timeout_seconds
            ):
                req.status = "rejected"
            result = {"status": req.status}
            if req.status == "approved":
                result["token"] = req.token
                self.pending.pop(request_id, None)
            return result

    def respond(self, current_token: str, request_id: str, approve: bool) -> dict[str, Any]:
        with self._lock:
            if not self.validate(current_token):
                return {"status": "unauthorized"}
            req = self.pending.get(request_id)
            if not req or req.status != "pending":
                return {"status": "not_found"}
            old_token = self.active.token if self.active else None
            if approve:
                new_token = self._new_token()
                now = time.monotonic()
                self.active = ControllerSession(new_token, req.client_name, now, now)
                req.status = "approved"
                req.token = new_token
                return {"status": "approved", "old_token": old_token}
            req.status = "rejected"
            return {"status": "rejected"}

    def logout(self, token: str) -> None:
        with self._lock:
            if self.active and secrets.compare_digest(self.active.token, token):
                self.active = None
