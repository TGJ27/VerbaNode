from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from app.db import Database


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class PairingSession:
    pairing_id: str
    secret: str
    short_code: str
    created_monotonic: float
    expires_monotonic: float
    server_url: str
    certificate_fingerprint_sha256: str
    certificate_spki_sha256: str
    attempts: int = 0
    claimed_device_id: str | None = None
    claimed_at: str | None = None


class PairingError(RuntimeError):
    pass


class PairingRateLimited(PairingError):
    pass


class DeviceManager:
    """Trusted local-controller registry and short-lived pairing coordinator.

    Long-lived device credentials are random high-entropy bearer tokens. Only a
    SHA-256 digest is stored in SQLite. Pairing secrets remain in memory and
    expire quickly, so a database backup never contains a usable pairing secret.
    """

    def __init__(self, db: Database, *, pairing_ttl_seconds: int = 180):
        self.db = db
        self.pairing_ttl_seconds = max(60, int(pairing_ttl_seconds))
        self._lock = threading.RLock()
        self._pairings: dict[str, PairingSession] = {}
        self._claim_failures: dict[str, deque[float]] = {}

    def instance_id(self) -> str:
        existing = (self.db.get_setting("instance_id", "") or "").strip()
        if existing:
            return existing
        value = str(uuid.uuid4())
        self.db.set_setting("instance_id", value)
        return value

    def _prune_pairings(self) -> None:
        now = time.monotonic()
        for pairing_id, pairing in list(self._pairings.items()):
            # Keep a claimed pairing visible briefly for dashboard polling.
            grace = 60.0 if pairing.claimed_device_id else 0.0
            if pairing.expires_monotonic + grace <= now:
                self._pairings.pop(pairing_id, None)

    def _pairing_payload(self, pairing: PairingSession, *, include_secret: bool) -> dict[str, Any]:
        remaining = max(0, int(pairing.expires_monotonic - time.monotonic()))
        query = {
            "server": pairing.server_url,
            "pairing_id": pairing.pairing_id,
            "fingerprint": pairing.certificate_fingerprint_sha256,
            "spki": pairing.certificate_spki_sha256,
        }
        if include_secret:
            query["secret"] = pairing.secret
        return {
            "pairing_id": pairing.pairing_id,
            "short_code": pairing.short_code if include_secret else None,
            "server_url": pairing.server_url,
            "certificate_fingerprint_sha256": pairing.certificate_fingerprint_sha256,
            "certificate_spki_sha256": pairing.certificate_spki_sha256,
            "expires_in_seconds": remaining,
            "claimed": bool(pairing.claimed_device_id),
            "claimed_device_id": pairing.claimed_device_id,
            "claimed_at": pairing.claimed_at,
            "pairing_uri": f"verbanode://pair?{urlencode(query)}" if include_secret else None,
        }

    def create_pairing(self, *, server_url: str, certificate_fingerprint_sha256: str, certificate_spki_sha256: str) -> dict[str, Any]:
        with self._lock:
            self._prune_pairings()
            now = time.monotonic()
            pairing = PairingSession(
                pairing_id=secrets.token_urlsafe(12),
                secret=secrets.token_urlsafe(32),
                short_code=f"{secrets.randbelow(100_000_000):08d}",
                created_monotonic=now,
                expires_monotonic=now + float(self.pairing_ttl_seconds),
                server_url=server_url.rstrip("/"),
                certificate_fingerprint_sha256=certificate_fingerprint_sha256.lower(),
                certificate_spki_sha256=certificate_spki_sha256.lower(),
            )
            self._pairings[pairing.pairing_id] = pairing
            return self._pairing_payload(pairing, include_secret=True)

    def pairing_status(self, pairing_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._prune_pairings()
            pairing = self._pairings.get(pairing_id)
            return self._pairing_payload(pairing, include_secret=False) if pairing else None

    def cancel_pairing(self, pairing_id: str) -> bool:
        with self._lock:
            return self._pairings.pop(pairing_id, None) is not None

    def pairing_uri(self, pairing_id: str) -> str | None:
        with self._lock:
            self._prune_pairings()
            pairing = self._pairings.get(pairing_id)
            if not pairing or pairing.claimed_device_id:
                return None
            return str(self._pairing_payload(pairing, include_secret=True)["pairing_uri"])

    def _rate_limit_claim(self, client_key: str) -> None:
        now = time.monotonic()
        bucket = self._claim_failures.setdefault(client_key, deque())
        while bucket and now - bucket[0] > 60.0:
            bucket.popleft()
        if len(bucket) >= 20:
            raise PairingRateLimited("Too many pairing attempts")

    def _record_claim_failure(self, client_key: str) -> None:
        self._claim_failures.setdefault(client_key, deque()).append(time.monotonic())

    def claim_pairing(
        self,
        *,
        client_key: str,
        pairing_id: str | None,
        secret: str | None,
        short_code: str | None,
        device_name: str,
        device_type: str,
        device_version: str | None,
        platform: str | None,
    ) -> dict[str, Any]:
        with self._lock:
            self._rate_limit_claim(client_key)
            self._prune_pairings()
            pairing: PairingSession | None = None
            if pairing_id:
                pairing = self._pairings.get(pairing_id)
            elif short_code:
                matches = [p for p in self._pairings.values() if secrets.compare_digest(p.short_code, short_code)]
                pairing = matches[0] if len(matches) == 1 else None
            if not pairing or pairing.expires_monotonic <= time.monotonic() or pairing.claimed_device_id:
                self._record_claim_failure(client_key)
                raise PairingError("Pairing request is invalid or expired")

            valid = False
            if secret:
                valid = secrets.compare_digest(pairing.secret, secret)
            elif short_code:
                valid = secrets.compare_digest(pairing.short_code, short_code)
            if not valid:
                pairing.attempts += 1
                self._record_claim_failure(client_key)
                if pairing.attempts >= 10:
                    self._pairings.pop(pairing.pairing_id, None)
                raise PairingError("Pairing code is invalid")

            device_id = str(uuid.uuid4())
            device_token = secrets.token_urlsafe(40)
            now = _utc_now()
            metadata = {
                "device_version": device_version,
                "platform": platform,
            }
            with self.db.connect() as conn:
                conn.execute(
                    """
                    INSERT INTO trusted_devices(
                        device_id,name,device_type,credential_hash,created_at,last_seen_at,revoked_at,metadata_json
                    ) VALUES(?,?,?,?,?,?,NULL,?)
                    """,
                    (
                        device_id,
                        device_name.strip()[:120] or "Android device",
                        device_type.strip()[:32] or "mobile",
                        _token_hash(device_token),
                        now,
                        now,
                        json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
                    ),
                )
                conn.commit()
            pairing.claimed_device_id = device_id
            pairing.claimed_at = now
            pairing.secret = ""
            self._claim_failures.pop(client_key, None)
            return {
                "status": "paired",
                "device_id": device_id,
                "device_token": device_token,
                "device_name": device_name.strip()[:120] or "Android device",
                "server_url": pairing.server_url,
                "certificate_fingerprint_sha256": pairing.certificate_fingerprint_sha256,
                "certificate_spki_sha256": pairing.certificate_spki_sha256,
            }

    def verify_device(self, device_id: str, device_token: str) -> dict[str, Any] | None:
        if not device_id or not device_token:
            return None
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM trusted_devices WHERE device_id=? AND revoked_at IS NULL",
                (device_id,),
            ).fetchone()
            if not row or not secrets.compare_digest(str(row["credential_hash"]), _token_hash(device_token)):
                return None
            now = _utc_now()
            conn.execute("UPDATE trusted_devices SET last_seen_at=? WHERE device_id=?", (now, device_id))
            conn.commit()
            payload = dict(row)
            payload["last_seen_at"] = now
            payload.pop("credential_hash", None)
            return payload

    def list_devices(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT device_id,name,device_type,created_at,last_seen_at,revoked_at,metadata_json "
                "FROM trusted_devices ORDER BY created_at DESC"
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
            except json.JSONDecodeError:
                item["metadata"] = {}
            item["trusted"] = item.get("revoked_at") is None
            result.append(item)
        return result

    def rename_device(self, device_id: str, name: str) -> dict[str, Any] | None:
        clean = name.strip()[:120]
        if not clean:
            return None
        with self.db.connect() as conn:
            changed = conn.execute(
                "UPDATE trusted_devices SET name=? WHERE device_id=?",
                (clean, device_id),
            ).rowcount
            conn.commit()
        if not changed:
            return None
        return next((item for item in self.list_devices() if item["device_id"] == device_id), None)

    def revoke_device(self, device_id: str) -> bool:
        with self.db.connect() as conn:
            changed = conn.execute(
                "UPDATE trusted_devices SET revoked_at=?, credential_hash='' WHERE device_id=? AND revoked_at IS NULL",
                (_utc_now(), device_id),
            ).rowcount
            conn.commit()
            return bool(changed)

    def delete_device(self, device_id: str) -> bool:
        with self.db.connect() as conn:
            changed = conn.execute("DELETE FROM trusted_devices WHERE device_id=?", (device_id,)).rowcount
            conn.commit()
            return bool(changed)
