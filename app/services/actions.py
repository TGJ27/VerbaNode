from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TERMINAL_ACTION_STATES = frozenset(
    {"completed", "failed", "timed_out", "cancelled", "interrupted", "expired"}
)
ACTIVE_ACTION_STATES = frozenset({"pending", "running"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical_arguments(arguments: dict[str, Any]) -> tuple[str, str]:
    encoded = json.dumps(
        arguments,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return encoded, digest


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ActionClaim:
    state: str
    action: dict[str, Any] | None = None
    detail: str | None = None


class ActionLedger:
    """Crash-safe idempotency and audit ledger for plugin/capability actions.

    ``action_id`` is globally unique inside one VerbaNode installation. A repeated
    action ID with the same plugin and arguments replays the stored terminal
    result. Reusing an action ID for a different command is rejected. v0.8.2 also
    persists optional action expiry so stale physical commands are never retried.
    """

    def __init__(self, db_path: Path, *, stale_after_seconds: float = 30.0) -> None:
        self.db_path = Path(db_path)
        self.stale_after_seconds = max(1.0, float(stale_after_seconds))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=10000")
        return conn

    def ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS action_ledger (
                    action_id TEXT PRIMARY KEY,
                    plugin_id TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    arguments_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT,
                    error TEXT,
                    latency_ms REAL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_action_ledger_created_at
                    ON action_ledger(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_action_ledger_plugin_created
                    ON action_ledger(plugin_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_action_ledger_status
                    ON action_ledger(status);
                """
            )
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(action_ledger)").fetchall()
            }
            if "expires_at" not in columns:
                conn.execute("ALTER TABLE action_ledger ADD COLUMN expires_at TEXT")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_action_ledger_expires_at "
                "ON action_ledger(expires_at)"
            )

    def recover_stale(self, older_than_seconds: float) -> int:
        """Mark abandoned active rows as interrupted without re-executing them."""
        cutoff = datetime.now(timezone.utc).timestamp() - max(1.0, float(older_than_seconds))
        changed = 0
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT action_id, updated_at, expires_at FROM action_ledger "
                "WHERE status IN ('pending','running')"
            ).fetchall()
            for row in rows:
                now_dt = datetime.now(timezone.utc)
                expiry = _parse_time(row["expires_at"])
                if expiry is not None and expiry <= now_dt:
                    now = _utc_now()
                    cursor = conn.execute(
                        "UPDATE action_ledger SET status='expired', error=?, completed_at=?, updated_at=? "
                        "WHERE action_id=? AND status IN ('pending','running')",
                        (
                            "Action expired before the previous process completed it",
                            now,
                            now,
                            str(row["action_id"]),
                        ),
                    )
                    changed += int(cursor.rowcount or 0)
                    continue
                try:
                    updated = datetime.fromisoformat(str(row["updated_at"])).timestamp()
                except (TypeError, ValueError):
                    updated = 0.0
                if updated > cutoff:
                    continue
                now = _utc_now()
                cursor = conn.execute(
                    "UPDATE action_ledger SET status='interrupted', error=?, completed_at=?, updated_at=? "
                    "WHERE action_id=? AND status IN ('pending','running')",
                    (
                        "Previous VerbaNode process ended before this action completed",
                        now,
                        now,
                        str(row["action_id"]),
                    ),
                )
                changed += int(cursor.rowcount or 0)
        return changed

    def claim(
        self,
        action_id: str,
        plugin_id: str,
        arguments: dict[str, Any],
        *,
        expires_at: str | None = None,
    ) -> ActionClaim:
        arguments_json, arguments_hash = _canonical_arguments(arguments)
        now = _utc_now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM action_ledger WHERE action_id=?", (action_id,)
            ).fetchone()
            if row is None:
                expiry = _parse_time(expires_at)
                if expiry is not None and expiry <= datetime.now(timezone.utc):
                    conn.execute(
                        "INSERT INTO action_ledger("
                        "action_id,plugin_id,arguments_json,arguments_hash,status,verified,error,"
                        "created_at,completed_at,updated_at,expires_at"
                        ") VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            action_id,
                            plugin_id,
                            arguments_json,
                            arguments_hash,
                            "expired",
                            0,
                            "Action expired before execution",
                            now,
                            now,
                            now,
                            expires_at,
                        ),
                    )
                    conn.commit()
                    return ActionClaim("replay", self.get(action_id))
                conn.execute(
                    "INSERT INTO action_ledger("
                    "action_id,plugin_id,arguments_json,arguments_hash,status,verified,created_at,updated_at,expires_at"
                    ") VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        action_id,
                        plugin_id,
                        arguments_json,
                        arguments_hash,
                        "pending",
                        0,
                        now,
                        now,
                        expires_at,
                    ),
                )
                conn.commit()
                return ActionClaim("claimed")

            action = self._row_to_dict(row)
            if str(row["plugin_id"]) != plugin_id or str(row["arguments_hash"]) != arguments_hash:
                conn.commit()
                return ActionClaim(
                    "conflict",
                    action,
                    "action_id is already bound to a different plugin or argument payload",
                )

            status = str(row["status"])
            expiry = _parse_time(row["expires_at"])
            if status in ACTIVE_ACTION_STATES and expiry is not None and expiry <= datetime.now(timezone.utc):
                expired_at = _utc_now()
                error = "Action expired before execution completed"
                conn.execute(
                    "UPDATE action_ledger SET status='expired', error=?, completed_at=?, updated_at=? "
                    "WHERE action_id=? AND status IN ('pending','running')",
                    (error, expired_at, expired_at, action_id),
                )
                conn.commit()
                return ActionClaim("replay", self.get(action_id))

            if status in ACTIVE_ACTION_STATES and self._is_stale(row["updated_at"]):
                interrupted_at = _utc_now()
                error = "Previous VerbaNode process ended before this action completed"
                conn.execute(
                    "UPDATE action_ledger SET status='interrupted', error=?, completed_at=?, updated_at=? "
                    "WHERE action_id=? AND status IN ('pending','running')",
                    (error, interrupted_at, interrupted_at, action_id),
                )
                conn.commit()
                return ActionClaim("replay", self.get(action_id))

            conn.commit()
            if status in TERMINAL_ACTION_STATES:
                return ActionClaim("replay", action)
            return ActionClaim("in_progress", action)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _is_stale(self, updated_at: Any) -> bool:
        try:
            updated = datetime.fromisoformat(str(updated_at)).timestamp()
        except (TypeError, ValueError):
            return True
        return updated <= datetime.now(timezone.utc).timestamp() - self.stale_after_seconds

    def mark_running(self, action_id: str) -> bool:
        now = _utc_now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT expires_at FROM action_ledger WHERE action_id=?", (action_id,)
            ).fetchone()
            if row is not None:
                expiry = _parse_time(row["expires_at"])
                if expiry is not None and expiry <= datetime.now(timezone.utc):
                    cursor = conn.execute(
                        "UPDATE action_ledger SET status='expired', error=?, completed_at=?, updated_at=? "
                        "WHERE action_id=? AND status='pending'",
                        ("Action expired before execution", now, now, action_id),
                    )
                    return False
            cursor = conn.execute(
                "UPDATE action_ledger SET status='running', started_at=COALESCE(started_at,?), updated_at=? "
                "WHERE action_id=? AND status='pending'",
                (now, now, action_id),
            )
            return bool(cursor.rowcount)

    def complete(
        self,
        action_id: str,
        *,
        status: str,
        verified: bool,
        result: dict[str, Any] | None,
        error: str | None,
        latency_ms: float | None,
    ) -> None:
        now = _utc_now()
        result_json = (
            json.dumps(result, ensure_ascii=False, default=str, separators=(",", ":"))
            if result is not None
            else None
        )
        with self._connect() as conn:
            conn.execute(
                "UPDATE action_ledger SET status=?, verified=?, result_json=?, error=?, latency_ms=?, "
                "completed_at=?, updated_at=? WHERE action_id=? AND status IN ('pending','running')",
                (
                    str(status),
                    1 if verified else 0,
                    result_json,
                    error,
                    None if latency_ms is None else float(latency_ms),
                    now,
                    now,
                    action_id,
                ),
            )

    def get(self, action_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM action_ledger WHERE action_id=?", (action_id,)
            ).fetchone()
        return self._row_to_dict(row) if row is not None else None

    def list_recent(self, limit: int = 100) -> list[dict[str, Any]]:
        resolved_limit = max(1, min(int(limit), 500))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM action_ledger ORDER BY created_at DESC LIMIT ?",
                (resolved_limit,),
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    @staticmethod
    def replay_payload(action: dict[str, Any]) -> dict[str, Any]:
        result = action.get("result")
        if isinstance(result, dict):
            return dict(result)
        message = str(action.get("error") or f"Action is {action.get('status', 'unknown')}")
        return {
            "error": message,
            "_action": {
                "id": action.get("action_id"),
                "success": False,
                "status": action.get("status", "failed"),
                "verified": bool(action.get("verified")),
            },
        }

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        try:
            arguments = json.loads(str(row["arguments_json"]))
        except (TypeError, ValueError, json.JSONDecodeError):
            arguments = {}
        result: dict[str, Any] | None = None
        if row["result_json"]:
            try:
                decoded = json.loads(str(row["result_json"]))
                if isinstance(decoded, dict):
                    result = decoded
            except (TypeError, ValueError, json.JSONDecodeError):
                result = None
        keys = set(row.keys())
        return {
            "action_id": str(row["action_id"]),
            "plugin_id": str(row["plugin_id"]),
            "arguments": arguments,
            "arguments_hash": str(row["arguments_hash"]),
            "status": str(row["status"]),
            "verified": bool(row["verified"]),
            "result": result,
            "error": row["error"],
            "latency_ms": row["latency_ms"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
            "expires_at": row["expires_at"] if "expires_at" in keys else None,
        }


__all__ = [
    "ACTIVE_ACTION_STATES",
    "TERMINAL_ACTION_STATES",
    "ActionClaim",
    "ActionLedger",
]
