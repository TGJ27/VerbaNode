from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.capabilities.provider import CapabilityProvider
from app.capabilities.service import CapabilityService
from app.config import Settings
from app.plugins.base import Plugin
from app.plugins.capabilities import CapabilityGateway
from app.plugins.context import PluginContext
from app.plugins.exceptions import (
    PluginCompatibilityError,
    PluginManifestError,
    PluginSchemaError,
)
from app.plugins.loader import (
    ExternalPluginLoader,
    LoadedExternalPlugin,
    validate_tool_schema,
)
from app.plugins.models import ExternalPluginFailure, PluginRuntimeState
from app.plugins.registry import PluginRegistry
from app.services.actions import ActionLedger

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PluginMetrics:
    executions: int = 0
    successes: int = 0
    errors: int = 0
    timeouts: int = 0
    cancellations: int = 0
    consecutive_failures: int = 0
    total_latency_ms: float = 0.0
    last_latency_ms: float = 0.0
    last_error: str | None = None
    last_success_at: float | None = None
    last_failure_at: float | None = None

    @property
    def average_latency_ms(self) -> float:
        if not self.executions:
            return 0.0
        return self.total_latency_ms / self.executions

    def reset(self) -> None:
        self.executions = 0
        self.successes = 0
        self.errors = 0
        self.timeouts = 0
        self.cancellations = 0
        self.consecutive_failures = 0
        self.total_latency_ms = 0.0
        self.last_latency_ms = 0.0
        self.last_error = None
        self.last_success_at = None
        self.last_failure_at = None


class PluginManager:
    """Coordinates built-in and trusted local external plugins.

    The manager provides lifecycle isolation, bounded execution, timeouts,
    health transitions, safe reload, and metrics. External plugins remain
    trusted local Python code; this is reliability hardening, not a security
    sandbox.
    """

    def __init__(
        self,
        settings: Settings,
        registry: PluginRegistry | None = None,
        capability_service: CapabilityService | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry or PluginRegistry()
        self.capability_service = capability_service or CapabilityService(settings)
        self._metrics: dict[str, PluginMetrics] = {}
        self._runtime: dict[str, PluginRuntimeState] = {}
        self._disabled_ids: set[str] = set()
        self._external_dir: Path | None = None
        self._external_loaded: dict[str, LoadedExternalPlugin] = {}
        self._external_failures: dict[str, ExternalPluginFailure] = {}
        self._active_tasks: dict[str, set[asyncio.Task[Any]]] = {}
        self._action_tasks: dict[str, asyncio.Task[Any]] = {}
        self._reload_locks: dict[str, asyncio.Lock] = {}
        self._action_audit: deque[dict[str, Any]] = deque(maxlen=250)
        action_stale_seconds = max(30.0, float(self.settings.plugin_execution_timeout_seconds) * 2.0)
        self.action_ledger = ActionLedger(
            self.settings.db_path, stale_after_seconds=action_stale_seconds
        )
        self.action_ledger.recover_stale(action_stale_seconds)
        self._inflight_actions: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._action_audit_lock = threading.RLock()
        self._execution_semaphore = asyncio.Semaphore(
            int(self.settings.plugin_max_concurrent_executions)
        )
        self._loader = ExternalPluginLoader(
            manifest_max_bytes=self.settings.plugin_manifest_max_bytes,
            entry_max_bytes=self.settings.plugin_entry_max_bytes,
        )

    def register(self, plugin: Plugin) -> None:
        validate_tool_schema(plugin.schema, plugin.id)
        plugin.enabled = plugin.id not in self._disabled_ids
        self.registry.register(plugin)
        self._metrics.setdefault(plugin.id, PluginMetrics())
        self._runtime[plugin.id] = PluginRuntimeState(
            status="healthy" if plugin.enabled else "disabled",
            state_changed_at=time.time(),
        )

    def configure_disabled(self, plugin_ids: Iterable[str]) -> None:
        self._disabled_ids = {str(plugin_id) for plugin_id in plugin_ids}
        for plugin in self.registry.list():
            plugin.enabled = plugin.id not in self._disabled_ids
            runtime = self._runtime_for(plugin.id)
            runtime.status = "healthy" if plugin.enabled else "disabled"
            runtime.state_changed_at = time.time()

    def disabled_ids(self) -> list[str]:
        return sorted(plugin.id for plugin in self.registry.list() if not plugin.enabled)

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            raise KeyError(plugin_id)
        plugin.enabled = bool(enabled)
        runtime = self._runtime_for(plugin_id)
        metric = self._metrics.setdefault(plugin_id, PluginMetrics())
        if plugin.enabled:
            self._disabled_ids.discard(plugin_id)
            metric.consecutive_failures = 0
            runtime.status = "healthy"
        else:
            self._disabled_ids.add(plugin_id)
            runtime.status = "disabled"
        runtime.state_changed_at = time.time()
        LOGGER.info(
            "%s plugin %s is now %s",
            plugin.source.capitalize(),
            plugin_id,
            "enabled" if plugin.enabled else "disabled",
        )
        return self.plugin_health(plugin_id)

    def reset_metrics(self, plugin_id: str | None = None) -> None:
        if plugin_id is not None:
            if self.registry.get(plugin_id) is None:
                raise KeyError(plugin_id)
            self._metrics.setdefault(plugin_id, PluginMetrics()).reset()
            return
        for plugin in self.registry.list():
            self._metrics.setdefault(plugin.id, PluginMetrics()).reset()

    def schemas(self, enabled: list[str]) -> list[dict[str, Any]]:
        enabled_set = set(enabled or [])
        return [
            plugin.schema
            for plugin in self.registry.list()
            if plugin.id in enabled_set and self._is_available(plugin.id)
        ]

    def match_core_intent(
        self,
        text: str,
        enabled: list[str],
    ) -> tuple[str, dict[str, Any]] | None:
        enabled_set = set(enabled or [])
        for plugin in self.registry.list():
            if plugin.id not in enabled_set or not self._is_available(plugin.id):
                continue
            try:
                arguments = plugin.match(PluginContext(settings=self.settings, text=text))
            except Exception as exc:
                self._record_failure(
                    plugin.id,
                    f"Intent matching failed: {exc}",
                    count_execution=False,
                )
                LOGGER.exception(
                    "%s plugin '%s' intent matching failed",
                    plugin.source.capitalize(),
                    plugin.id,
                )
                continue
            if arguments is not None:
                return plugin.id, arguments
        return None

    async def execute(
        self,
        plugin_id: str,
        arguments: dict[str, Any] | None = None,
        *,
        action_id: str | None = None,
        expires_in_seconds: float | None = None,
    ) -> dict[str, Any]:
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            return {"error": f"Unknown tool: {plugin_id}"}
        if not plugin.enabled:
            return {"error": f"Tool '{plugin_id}' is disabled"}

        runtime = self._runtime_for(plugin_id)
        if runtime.status == "unhealthy":
            return {
                "error": (
                    f"Tool '{plugin_id}' is unhealthy after repeated failures. "
                    "Reload it or disable and re-enable it from Plugin Manager."
                )
            }
        if runtime.status in {"loading", "reloading"}:
            return {"error": f"Tool '{plugin_id}' is currently {runtime.status}"}

        resolved_action_id = str(action_id or uuid.uuid4())
        resolved_arguments = dict(arguments or {})
        expires_at: str | None = None
        expiry_dt: datetime | None = None
        if expires_in_seconds is not None:
            ttl = max(0.0, float(expires_in_seconds))
            ttl = min(ttl, float(self.settings.capability_max_ttl_seconds))
            expiry_dt = datetime.now(timezone.utc) + timedelta(seconds=ttl)
            expires_at = expiry_dt.isoformat(timespec="milliseconds")

        # Reserve the in-process completion future *before* touching SQLite.
        # There is no await between the lookup and assignment, so two callers on
        # the same event loop cannot both become the leader for one action ID.
        # SQLite remains the cross-process/restart authority.
        existing = self._inflight_actions.get(resolved_action_id)
        if existing is not None:
            return dict(await asyncio.shield(existing))

        loop = asyncio.get_running_loop()
        completion: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._inflight_actions[resolved_action_id] = completion
        try:
            claim = self.action_ledger.claim(
                resolved_action_id,
                plugin_id,
                resolved_arguments,
                expires_at=expires_at,
            )
            if claim.state == "conflict":
                response = {
                    "error": claim.detail or "action_id conflict",
                    "_action": {
                        "id": resolved_action_id,
                        "success": False,
                        "status": "conflict",
                        "verified": False,
                    },
                }
                completion.set_result(dict(response))
                self._inflight_actions.pop(resolved_action_id, None)
                return response
            if claim.state == "replay" and claim.action is not None:
                response = self.action_ledger.replay_payload(claim.action)
                completion.set_result(dict(response))
                self._inflight_actions.pop(resolved_action_id, None)
                return response
            if claim.state == "in_progress":
                current = self.action_ledger.get(resolved_action_id)
                if current is not None and current.get("status") not in {"pending", "running"}:
                    response = self.action_ledger.replay_payload(current)
                else:
                    response = {
                        "error": "Action is already in progress in another VerbaNode process",
                        "_action": {
                            "id": resolved_action_id,
                            "success": False,
                            "status": "running",
                            "verified": False,
                        },
                    }
                completion.set_result(dict(response))
                self._inflight_actions.pop(resolved_action_id, None)
                return response
        except Exception as exc:
            if not completion.done():
                completion.set_exception(exc)
                try:
                    completion.exception()
                except Exception:
                    pass
            self._inflight_actions.pop(resolved_action_id, None)
            raise

        if not self.action_ledger.mark_running(resolved_action_id):
            current = self.action_ledger.get(resolved_action_id)
            response = self.action_ledger.replay_payload(
                current
                or {
                    "action_id": resolved_action_id,
                    "status": "expired",
                    "verified": False,
                    "error": "Action expired before execution",
                }
            )
            completion.set_result(dict(response))
            self._inflight_actions.pop(resolved_action_id, None)
            return response

        metric = self._metrics.setdefault(plugin_id, PluginMetrics())
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        task = asyncio.current_task()
        if task is not None:
            self._active_tasks.setdefault(plugin_id, set()).add(task)
            self._action_tasks[resolved_action_id] = task
        runtime.active_executions += 1

        execution_timeout = float(self.settings.plugin_execution_timeout_seconds)
        deadline_limited = False
        if expiry_dt is not None:
            remaining = max(
                0.0,
                (expiry_dt - datetime.now(timezone.utc)).total_seconds(),
            )
            if remaining <= execution_timeout:
                deadline_limited = True
            execution_timeout = min(execution_timeout, remaining)

        audit_status = "failed"
        audit_error: str | None = None
        verified = False
        response_payload: dict[str, Any] | None = None
        try:
            if execution_timeout <= 0:
                audit_status = "expired"
                audit_error = "Action expired before execution"
                response_payload = {
                    "error": audit_error,
                    "_action": {
                        "id": resolved_action_id,
                        "success": False,
                        "status": "expired",
                        "verified": False,
                    },
                }
                return response_payload
            result = await asyncio.wait_for(
                self._execute_bounded(plugin, resolved_arguments, resolved_action_id),
                timeout=execution_timeout,
            )
            metric.successes += 1
            metric.consecutive_failures = 0
            metric.last_error = None
            metric.last_success_at = time.time()
            if plugin.enabled:
                runtime.status = "healthy"
            payload = result.as_tool_result()
            success = bool(result.success) and not bool(payload.get("error"))
            raw_status = str(result.status or "").strip()
            status = (
                "failed"
                if not success and raw_status in {"", "completed"}
                else (raw_status or "completed")
            )
            action_meta = {
                "id": result.action_id or resolved_action_id,
                "success": success,
                "status": status,
                "verified": bool(result.verified),
            }
            if result.error_code:
                action_meta["error_code"] = result.error_code
            payload.setdefault("_action", action_meta)
            audit_status = status
            audit_error = str(payload.get("error")) if payload.get("error") else None
            verified = bool(result.verified)
            response_payload = payload
            return payload
        except asyncio.TimeoutError:
            expired = bool(
                deadline_limited
                and expiry_dt is not None
                and expiry_dt <= datetime.now(timezone.utc)
            )
            if expired:
                message = f"Tool '{plugin_id}' action expired before completion"
                audit_status = "expired"
            else:
                message = (
                    f"Tool '{plugin_id}' timed out after "
                    f"{self.settings.plugin_execution_timeout_seconds:g} seconds"
                )
                audit_status = "timed_out"
                metric.timeouts += 1
                self._record_failure(plugin_id, message, increment_error=True)
                LOGGER.error(message)
            audit_error = message
            response_payload = {
                "error": message,
                "_action": {
                    "id": resolved_action_id,
                    "success": False,
                    "status": audit_status,
                    "verified": False,
                },
            }
            return response_payload
        except asyncio.CancelledError:
            metric.cancellations += 1
            audit_status = "cancelled"
            audit_error = "Execution cancelled"
            response_payload = {
                "error": audit_error,
                "_action": {
                    "id": resolved_action_id,
                    "success": False,
                    "status": "cancelled",
                    "verified": False,
                },
            }
            raise
        except Exception as exc:
            message = f"Tool '{plugin_id}' failed: {exc}"
            self._record_failure(plugin_id, str(exc), increment_error=True)
            LOGGER.exception("%s plugin '%s' failed", plugin.source.capitalize(), plugin_id)
            audit_status = "failed"
            audit_error = str(exc)
            response_payload = {
                "error": message,
                "_action": {
                    "id": resolved_action_id,
                    "success": False,
                    "status": "failed",
                    "verified": False,
                },
            }
            return response_payload
        finally:
            latency_ms = (time.perf_counter() - started) * 1000.0
            metric.executions += 1
            metric.last_latency_ms = latency_ms
            metric.total_latency_ms += latency_ms
            runtime.active_executions = max(0, runtime.active_executions - 1)
            if task is not None:
                tasks = self._active_tasks.get(plugin_id)
                if tasks is not None:
                    tasks.discard(task)
                    if not tasks:
                        self._active_tasks.pop(plugin_id, None)
                if self._action_tasks.get(resolved_action_id) is task:
                    self._action_tasks.pop(resolved_action_id, None)
            self.action_ledger.complete(
                resolved_action_id,
                status=audit_status,
                verified=verified,
                result=response_payload,
                error=audit_error,
                latency_ms=latency_ms,
            )
            self._record_action_audit(
                plugin_id=plugin_id,
                action_id=resolved_action_id,
                arguments=resolved_arguments,
                status=audit_status,
                verified=verified,
                latency_ms=latency_ms,
                started_at=started_at,
                error=audit_error,
            )
            if not completion.done():
                completion.set_result(
                    dict(
                        response_payload
                        or self.action_ledger.replay_payload(
                            self.action_ledger.get(resolved_action_id)
                            or {
                                "action_id": resolved_action_id,
                                "status": audit_status,
                                "verified": verified,
                                "error": audit_error,
                            }
                        )
                    )
                )
            self._inflight_actions.pop(resolved_action_id, None)

    def _record_action_audit(
        self,
        *,
        plugin_id: str,
        action_id: str,
        arguments: dict[str, Any],
        status: str,
        verified: bool,
        latency_ms: float,
        started_at: str,
        error: str | None,
    ) -> None:
        entry = {
            "action_id": action_id,
            "plugin_id": plugin_id,
            "status": status,
            "verified": bool(verified),
            "latency_ms": round(float(latency_ms), 2),
            "started_at": started_at,
            "completed_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "arguments": dict(arguments),
            "error": error,
        }
        with self._action_audit_lock:
            self._action_audit.append(entry)
        try:
            audit_path = self.settings.capability_audit_path
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            with audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        except OSError:
            LOGGER.debug("Could not append capability action audit log", exc_info=True)

    def action_audit(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.action_ledger.list_recent(max(1, min(int(limit), 500)))

    def action_status(self, action_id: str) -> dict[str, Any] | None:
        return self.action_ledger.get(action_id)

    async def _execute_bounded(
        self,
        plugin: Plugin,
        arguments: dict[str, Any] | None,
        action_id: str,
    ):
        async with self._execution_semaphore:
            return await plugin.execute(
                PluginContext(
                    settings=self.settings,
                    arguments=dict(arguments or {}),
                    metadata={"plugin_id": plugin.id, "action_id": action_id},
                    action_id=action_id,
                    gateway=CapabilityGateway(
                        plugin.id,
                        frozenset(plugin.permissions),
                        service=self.capability_service,
                        action_id=action_id,
                    ),
                )
            )

    async def cancel_action(self, action_id: str) -> dict[str, Any] | None:
        resolved = str(action_id)
        current = asyncio.current_task()
        await self.capability_service.cancel_parent(resolved)
        task = self._action_tasks.get(resolved)
        if task is not None and task is not current and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return self.action_ledger.get(resolved)

    async def cancel_capability_operation(self, operation_id: str) -> bool:
        return await self.capability_service.cancel_operation(operation_id)

    def capability_status(self) -> dict[str, Any]:
        payload = self.capability_service.describe()
        payload["active_operations"] = self.capability_service.active_operations()
        return payload

    def register_capability_provider(self, provider: CapabilityProvider) -> None:
        self.capability_service.register(provider)

    async def cancel_active(self, plugin_id: str | None = None) -> int:
        current = asyncio.current_task()
        selected: list[asyncio.Task[Any]] = []
        plugin_ids = [plugin_id] if plugin_id else list(self._active_tasks)
        for selected_id in plugin_ids:
            await self.capability_service.cancel_plugin(selected_id)
            for task in list(self._active_tasks.get(selected_id, set())):
                if task is not current and not task.done():
                    task.cancel()
                    selected.append(task)
        if selected:
            await asyncio.gather(*selected, return_exceptions=True)
        return len(selected)

    async def recover(self, plugin_id: str) -> dict[str, Any]:
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            if plugin_id in self._external_failures:
                await self.reload_external(plugin_id)
                return self.plugin_health(plugin_id)
            raise KeyError(plugin_id)
        if plugin.source == "external" and plugin.reloadable:
            await self.reload_external(plugin_id)
            return self.plugin_health(plugin_id)
        metric = self._metrics.setdefault(plugin_id, PluginMetrics())
        metric.consecutive_failures = 0
        metric.last_error = None
        runtime = self._runtime_for(plugin_id)
        runtime.status = "healthy" if plugin.enabled else "disabled"
        runtime.state_changed_at = time.time()
        return self.plugin_health(plugin_id)

    def format_result(
        self,
        plugin_id: str,
        result: dict[str, Any],
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            return str(result.get("error") or result.get("message") or result)
        try:
            return plugin.format_result(
                result,
                PluginContext(settings=self.settings, metadata=dict(metadata or {})),
            )
        except Exception as exc:
            self._record_failure(
                plugin.id,
                f"Result formatting failed: {exc}",
                count_execution=False,
            )
            LOGGER.exception(
                "%s plugin '%s' result formatting failed",
                plugin.source.capitalize(),
                plugin.id,
            )
            return str(result.get("error") or result.get("message") or result)

    def discover_external(self, directory: Path) -> dict[str, Any]:
        """Load external plugins during startup without touching built-ins."""
        self._external_dir = directory.resolve()
        self._external_dir.mkdir(parents=True, exist_ok=True)
        self._external_failures.clear()
        loaded = 0
        for folder in self._candidate_folders(self._external_dir):
            try:
                record = self._loader.load(folder)
                if self.registry.get(record.plugin.id) is not None:
                    raise PluginManifestError(
                        f"Plugin id '{record.plugin.id}' is reserved or already registered"
                    )
                record.plugin.enabled = record.plugin.id not in self._disabled_ids
                self.registry.register(record.plugin)
                self._external_loaded[record.plugin.id] = record
                self._metrics.setdefault(record.plugin.id, PluginMetrics())
                self._runtime[record.plugin.id] = PluginRuntimeState(
                    status="healthy" if record.plugin.enabled else "disabled",
                    state_changed_at=time.time(),
                )
                loaded += 1
            except Exception as exc:
                failure = self._failure_from_folder(folder, exc)
                self._external_failures[failure.key] = failure
                LOGGER.exception("External plugin in '%s' could not be loaded", folder.name)
        return {
            "loaded": loaded,
            "failed": len(self._external_failures),
            "directory": str(self._external_dir),
        }

    async def reload_external(self, plugin_id: str | None = None) -> dict[str, Any]:
        if self._external_dir is None:
            self._external_dir = self.settings.external_plugins_dir.resolve()
        self._external_dir.mkdir(parents=True, exist_ok=True)

        if plugin_id is None:
            await self._reload_all_external()
        else:
            await self._reload_one_external(plugin_id)
        return self.summary()

    async def shutdown(self) -> None:
        await self.cancel_active()
        for plugin_id in list(self._external_loaded):
            await self._unload_external(plugin_id)
        await self.capability_service.shutdown()

    def external_directory(self) -> Path:
        return (self._external_dir or self.settings.external_plugins_dir).resolve()

    def plugin_health(self, plugin_id: str) -> dict[str, Any]:
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            failure = self._external_failures.get(plugin_id)
            if failure is not None:
                return self._failure_health(failure)
            raise KeyError(plugin_id)
        metric = self._metrics.setdefault(plugin.id, PluginMetrics())
        runtime = self._runtime_for(plugin.id)
        status = "disabled" if not plugin.enabled else runtime.status
        healthy = status == "healthy"
        function = plugin.schema.get("function", {}) if plugin.schema else {}
        return {
            "id": plugin.id,
            "name": plugin.name,
            "version": plugin.version,
            "author": plugin.author,
            "description": plugin.description,
            "category": plugin.category,
            "permissions": list(plugin.permissions),
            "priority": plugin.priority,
            "enabled": plugin.enabled,
            "healthy": healthy,
            "status": status,
            "source": plugin.source,
            "external": plugin.source == "external",
            "reloadable": bool(plugin.reloadable),
            "sdk_version": plugin.sdk_version,
            "plugin_path": str(plugin.plugin_path) if plugin.plugin_path else None,
            "manifest_path": str(plugin.manifest_path) if plugin.manifest_path else None,
            "tool_name": function.get("name") or plugin.id,
            "tool_description": function.get("description") or plugin.description,
            "executions": metric.executions,
            "successes": metric.successes,
            "errors": metric.errors,
            "timeouts": metric.timeouts,
            "cancellations": metric.cancellations,
            "consecutive_failures": metric.consecutive_failures,
            "failure_threshold": int(self.settings.plugin_failure_threshold),
            "active_executions": runtime.active_executions,
            "average_latency_ms": round(metric.average_latency_ms, 2),
            "last_latency_ms": round(metric.last_latency_ms, 2),
            "last_error": metric.last_error,
            "last_success_at": metric.last_success_at,
            "last_failure_at": metric.last_failure_at,
            "reloads": runtime.reloads,
            "reload_errors": runtime.reload_errors,
            "last_reload_error": runtime.last_reload_error,
            "state_changed_at": runtime.state_changed_at,
        }

    def health(self) -> list[dict[str, Any]]:
        loaded = [self.plugin_health(plugin.id) for plugin in self.registry.list()]
        failed = [self._failure_health(item) for item in self._external_failures.values()]
        return sorted(
            [*loaded, *failed],
            key=lambda item: (
                0 if item.get("source") == "builtin" else 1,
                int(item.get("priority", 10000)),
                str(item.get("id")),
            ),
        )

    def summary(self) -> dict[str, Any]:
        items = self.health()
        loaded_items = [
            item
            for item in items
            if item.get("status") not in {"load_error", "incompatible", "invalid"}
        ]
        return {
            "total": len(items),
            "loaded": len(loaded_items),
            "builtin": sum(1 for item in loaded_items if item.get("source") == "builtin"),
            "external": sum(1 for item in loaded_items if item.get("source") == "external"),
            "failed_loads": sum(
                1
                for item in items
                if item.get("status") in {"load_error", "incompatible", "invalid"}
            ),
            "incompatible": sum(1 for item in items if item.get("status") == "incompatible"),
            "unhealthy": sum(1 for item in loaded_items if item.get("status") == "unhealthy"),
            "enabled": sum(1 for item in loaded_items if item["enabled"]),
            "disabled": sum(1 for item in loaded_items if not item["enabled"]),
            "healthy": sum(
                1 for item in loaded_items if item["enabled"] and item["healthy"]
            ),
            "errors": sum(int(item["errors"]) for item in loaded_items)
            + sum(
                1
                for item in items
                if item.get("status") in {"load_error", "incompatible", "invalid"}
            ),
            "timeouts": sum(int(item.get("timeouts", 0)) for item in loaded_items),
            "executions": sum(int(item["executions"]) for item in loaded_items),
            "active_executions": sum(
                int(item.get("active_executions", 0)) for item in loaded_items
            ),
            "reloads": sum(int(item.get("reloads", 0)) for item in loaded_items),
            "reload_errors": sum(
                int(item.get("reload_errors", 0)) for item in loaded_items
            ),
            "registry_generation": self.registry.generation,
            "execution_timeout_seconds": float(
                self.settings.plugin_execution_timeout_seconds
            ),
            "failure_threshold": int(self.settings.plugin_failure_threshold),
            "max_concurrent_executions": int(
                self.settings.plugin_max_concurrent_executions
            ),
        }

    async def _reload_all_external(self) -> None:
        directory = self._external_dir or self.settings.external_plugins_dir
        folders = self._candidate_folders(directory)
        folder_set = {folder.resolve() for folder in folders}

        for plugin_id, record in list(self._external_loaded.items()):
            if record.folder.resolve() not in folder_set:
                await self._unload_external(plugin_id)
                LOGGER.info("External plugin folder removed; unloaded %s", plugin_id)

        self._external_failures.clear()
        for folder in folders:
            await self._load_or_replace_folder(folder)

    async def _reload_one_external(self, plugin_id: str) -> None:
        record = self._external_loaded.get(plugin_id)
        failure = self._external_failures.get(plugin_id)
        if record is not None:
            await self._load_or_replace_folder(record.folder, expected_id=plugin_id)
            return
        if failure is not None:
            self._external_failures.pop(plugin_id, None)
            await self._load_or_replace_folder(failure.folder)
            return
        raise KeyError(plugin_id)

    async def _load_or_replace_folder(
        self,
        folder: Path,
        expected_id: str | None = None,
    ) -> None:
        if expected_id is None:
            for loaded_id, loaded_record in self._external_loaded.items():
                if loaded_record.folder.resolve() == folder.resolve():
                    expected_id = loaded_id
                    break

        lock_key = expected_id or f"folder:{folder.resolve()}"
        lock = self._reload_locks.setdefault(lock_key, asyncio.Lock())
        async with lock:
            existing = self.registry.get(expected_id) if expected_id else None
            existing_runtime = self._runtime.get(expected_id) if expected_id else None
            if existing_runtime is not None:
                existing_runtime.status = "reloading"
                existing_runtime.state_changed_at = time.time()
            try:
                candidate = self._loader.load(folder)
                if expected_id is not None and candidate.plugin.id != expected_id:
                    raise PluginManifestError(
                        f"Reload changed plugin id from '{expected_id}' to '{candidate.plugin.id}'"
                    )
                registered = self.registry.get(candidate.plugin.id)
                if registered is not None:
                    old_record = self._external_loaded.get(candidate.plugin.id)
                    if old_record is None or old_record.folder.resolve() != folder.resolve():
                        raise PluginManifestError(
                            f"Plugin id '{candidate.plugin.id}' is reserved or already registered"
                        )
                    await self.cancel_active(candidate.plugin.id)
                    candidate.plugin.enabled = registered.enabled
                    self.registry.replace(candidate.plugin)
                    self._external_loaded[candidate.plugin.id] = candidate
                    await self._shutdown_plugin(registered)
                    self._loader.unload_module(old_record.module_name)
                    runtime = self._runtime_for(candidate.plugin.id)
                    runtime.reloads += 1
                    runtime.last_reload_error = None
                    runtime.status = "healthy" if candidate.plugin.enabled else "disabled"
                    runtime.state_changed_at = time.time()
                    metric = self._metrics.setdefault(candidate.plugin.id, PluginMetrics())
                    metric.consecutive_failures = 0
                else:
                    candidate.plugin.enabled = candidate.plugin.id not in self._disabled_ids
                    self.registry.register(candidate.plugin)
                    self._external_loaded[candidate.plugin.id] = candidate
                    self._metrics.setdefault(candidate.plugin.id, PluginMetrics())
                    self._runtime[candidate.plugin.id] = PluginRuntimeState(
                        status="healthy" if candidate.plugin.enabled else "disabled",
                        reloads=1,
                        state_changed_at=time.time(),
                    )
                self._remove_failures_for_folder(folder)
                LOGGER.info(
                    "External plugin loaded: %s v%s",
                    candidate.plugin.id,
                    candidate.plugin.version,
                )
            except Exception as exc:
                if existing is not None and existing_runtime is not None:
                    existing_runtime.reload_errors += 1
                    existing_runtime.last_reload_error = str(exc)
                    existing_runtime.status = "healthy" if existing.enabled else "disabled"
                    existing_runtime.state_changed_at = time.time()
                else:
                    failure = self._failure_from_folder(folder, exc)
                    self._external_failures[failure.key] = failure
                LOGGER.exception("External plugin in '%s' could not be reloaded", folder.name)

    async def _unload_external(self, plugin_id: str) -> None:
        await self.cancel_active(plugin_id)
        record = self._external_loaded.pop(plugin_id, None)
        plugin = self.registry.unregister(plugin_id)
        if plugin is not None:
            await self._shutdown_plugin(plugin)
        if record is not None:
            self._loader.unload_module(record.module_name)
        self._metrics.pop(plugin_id, None)
        self._runtime.pop(plugin_id, None)
        self._active_tasks.pop(plugin_id, None)

    async def _shutdown_plugin(self, plugin: Plugin) -> None:
        try:
            value = plugin.shutdown()
            if inspect.isawaitable(value):
                await asyncio.wait_for(
                    value,
                    timeout=float(self.settings.plugin_shutdown_timeout_seconds),
                )
        except asyncio.TimeoutError:
            LOGGER.error(
                "Plugin '%s' shutdown hook timed out after %s seconds",
                plugin.id,
                self.settings.plugin_shutdown_timeout_seconds,
            )
        except Exception:
            LOGGER.exception("Plugin '%s' shutdown hook failed", plugin.id)

    @staticmethod
    def _candidate_folders(directory: Path) -> list[Path]:
        if not directory.exists():
            return []
        return sorted(
            (
                item
                for item in directory.iterdir()
                if item.is_dir() and not item.name.startswith((".", "_"))
            ),
            key=lambda item: item.name.lower(),
        )

    def _failure_from_folder(self, folder: Path, exc: Exception) -> ExternalPluginFailure:
        raw: dict[str, Any] = {}
        manifest_path = folder / "plugin.json"
        if manifest_path.is_file():
            try:
                if manifest_path.stat().st_size <= self.settings.plugin_manifest_max_bytes:
                    parsed = json.loads(manifest_path.read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        raw = parsed
            except Exception:
                raw = {}
        declared_id = str(raw.get("id") or "").strip() or None
        key = declared_id or f"external_failed__{folder.name}"
        if self.registry.get(key) is not None:
            key = f"external_failed__{folder.name}"
        permissions = raw.get("permissions") if isinstance(raw.get("permissions"), list) else []
        status = "load_error"
        if isinstance(exc, PluginCompatibilityError):
            status = "incompatible"
        elif isinstance(exc, (PluginManifestError, PluginSchemaError)):
            status = "invalid"
        return ExternalPluginFailure(
            key=key,
            folder=folder.resolve(),
            manifest_path=manifest_path if manifest_path.exists() else None,
            name=str(raw.get("name") or folder.name),
            plugin_id=declared_id,
            error=str(exc),
            status=status,
            category=str(raw.get("category") or "External"),
            version=str(raw.get("version") or "unknown"),
            author=str(raw.get("author") or "Unknown"),
            permissions=tuple(str(item) for item in permissions),
            sdk_version=str(raw.get("sdk_version") or "unknown"),
            entry=str(raw.get("entry") or "") or None,
        )

    @staticmethod
    def _failure_health(failure: ExternalPluginFailure) -> dict[str, Any]:
        return {
            "id": failure.key,
            "declared_id": failure.plugin_id,
            "name": failure.name,
            "version": failure.version,
            "author": failure.author,
            "description": "External plugin failed validation, compatibility checks, or loading.",
            "category": failure.category,
            "permissions": list(failure.permissions),
            "priority": 10000,
            "enabled": False,
            "healthy": False,
            "status": failure.status,
            "source": "external",
            "external": True,
            "reloadable": True,
            "sdk_version": failure.sdk_version,
            "plugin_path": str(failure.folder),
            "manifest_path": str(failure.manifest_path) if failure.manifest_path else None,
            "tool_name": failure.plugin_id or failure.key,
            "tool_description": "Plugin is unavailable until the package error is fixed.",
            "executions": 0,
            "successes": 0,
            "errors": 1,
            "timeouts": 0,
            "cancellations": 0,
            "consecutive_failures": 0,
            "failure_threshold": 0,
            "active_executions": 0,
            "average_latency_ms": 0.0,
            "last_latency_ms": 0.0,
            "last_error": failure.error,
            "last_success_at": None,
            "last_failure_at": None,
            "reloads": 0,
            "reload_errors": 0,
            "last_reload_error": None,
            "state_changed_at": None,
        }

    def _remove_failures_for_folder(self, folder: Path) -> None:
        target = folder.resolve()
        for key, failure in list(self._external_failures.items()):
            if failure.folder.resolve() == target:
                self._external_failures.pop(key, None)

    def _runtime_for(self, plugin_id: str) -> PluginRuntimeState:
        runtime = self._runtime.get(plugin_id)
        if runtime is None:
            runtime = PluginRuntimeState(status="healthy", state_changed_at=time.time())
            self._runtime[plugin_id] = runtime
        return runtime

    def _is_available(self, plugin_id: str) -> bool:
        plugin = self.registry.get(plugin_id)
        if plugin is None or not plugin.enabled:
            return False
        return self._runtime_for(plugin_id).status == "healthy"

    def _record_failure(
        self,
        plugin_id: str,
        message: str,
        *,
        increment_error: bool = True,
        count_execution: bool = True,
    ) -> None:
        metric = self._metrics.setdefault(plugin_id, PluginMetrics())
        if increment_error:
            metric.errors += 1
        metric.consecutive_failures += 1
        metric.last_error = message
        metric.last_failure_at = time.time()
        plugin = self.registry.get(plugin_id)
        runtime = self._runtime_for(plugin_id)
        if (
            plugin is not None
            and plugin.enabled
            and metric.consecutive_failures >= int(self.settings.plugin_failure_threshold)
        ):
            runtime.status = "unhealthy"
            runtime.state_changed_at = time.time()
            LOGGER.error(
                "Plugin '%s' marked unhealthy after %s consecutive failures",
                plugin_id,
                metric.consecutive_failures,
            )
