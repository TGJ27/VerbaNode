from __future__ import annotations

import math
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

from app.config import Settings


@dataclass
class ControllerSession:
    token: str
    client_name: str
    created_at: float
    last_seen: float



class ControllerManager:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.RLock()
        self.active: ControllerSession | None = None
        self._login_failures: dict[str, deque[float]] = {}
        self._login_lock_until: dict[str, float] = {}
        self._ws_tickets: dict[str, tuple[str, float]] = {}

    def _new_token(self) -> str:
        return secrets.token_urlsafe(32)

    def _active_is_stale(self) -> bool:
        return bool(
            self.active
            and time.monotonic() - self.active.last_seen > self.settings.controller_timeout_seconds
        )

    def _prune_login_failures(self, client_key: str, now: float) -> deque[float]:
        failures = self._login_failures.setdefault(client_key, deque())
        window = float(self.settings.login_attempt_window_seconds)
        while failures and now - failures[0] > window:
            failures.popleft()
        if not failures:
            self._login_failures.pop(client_key, None)
            failures = self._login_failures.setdefault(client_key, deque())
        return failures

    def _rate_limit_status(self, client_key: str, now: float) -> dict[str, Any] | None:
        locked_until = self._login_lock_until.get(client_key, 0.0)
        if locked_until <= now:
            self._login_lock_until.pop(client_key, None)
            return None
        return {
            "status": "rate_limited",
            "retry_after_seconds": max(1, int(math.ceil(locked_until - now))),
        }

    def _record_invalid_pin(self, client_key: str, now: float) -> dict[str, Any]:
        failures = self._prune_login_failures(client_key, now)
        failures.append(now)
        max_attempts = int(self.settings.login_max_attempts)
        if len(failures) < max_attempts:
            return {"status": "invalid_pin"}

        exponent = max(0, len(failures) - max_attempts)
        delay = min(
            float(self.settings.login_lockout_base_seconds) * (2**exponent),
            float(self.settings.login_lockout_max_seconds),
        )
        self._login_lock_until[client_key] = now + delay
        return {
            "status": "invalid_pin",
            "retry_after_seconds": max(1, int(math.ceil(delay))),
        }

    def _clear_login_failures(self, client_key: str) -> None:
        self._login_failures.pop(client_key, None)
        self._login_lock_until.pop(client_key, None)

    def login(
        self,
        pin: str,
        client_name: str,
        *,
        client_key: str = "local",
    ) -> dict[str, Any]:
        client_key = str(client_key or "unknown")
        with self._lock:
            now = time.monotonic()
            limited = self._rate_limit_status(client_key, now)
            if limited is not None:
                return limited
            if not secrets.compare_digest(pin, self.settings.pin):
                return self._record_invalid_pin(client_key, now)
            self._clear_login_failures(client_key)

            if self._active_is_stale():
                self.active = None
            if self.active is None:
                token = self._new_token()
                self.active = ControllerSession(token, client_name, now, now)
                return {"status": "granted", "token": token, "takeover": False}

            previous_client = self.active.client_name
            old_token = self.active.token
            token = self._new_token()
            self.active = ControllerSession(token, client_name, now, now)
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

    def create_ws_ticket(self, token: str) -> str | None:
        with self._lock:
            if not self.validate(token, touch=False):
                return None
            now = time.monotonic()
            self._prune_ws_tickets(now)
            ticket = secrets.token_urlsafe(24)
            self._ws_tickets[ticket] = (
                token,
                now + float(self.settings.websocket_ticket_ttl_seconds),
            )
            return ticket

    def _prune_ws_tickets(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        for ticket, (_token, expires_at) in list(self._ws_tickets.items()):
            if expires_at <= now:
                self._ws_tickets.pop(ticket, None)

    def consume_ws_ticket(self, ticket: str | None) -> str | None:
        if not ticket:
            return None
        with self._lock:
            now = time.monotonic()
            self._prune_ws_tickets(now)
            item = self._ws_tickets.pop(str(ticket), None)
            if item is None:
                return None
            token, expires_at = item
            if expires_at <= now or not self.validate(token):
                return None
            return token

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

    def logout(self, token: str) -> None:
        with self._lock:
            if self.active and secrets.compare_digest(self.active.token, token):
                self.active = None
            for ticket, (ticket_token, _expires_at) in list(self._ws_tickets.items()):
                if secrets.compare_digest(ticket_token, token):
                    self._ws_tickets.pop(ticket, None)
