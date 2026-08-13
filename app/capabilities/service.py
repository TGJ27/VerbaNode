from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from app.capabilities.models import CapabilityRequest, CapabilityResult
from app.capabilities.permissions import CapabilityPermissionError, permission_for_capability
from app.capabilities.provider import CapabilityProvider
from app.capabilities.registry import CapabilityRegistry
from app.config import Settings

LOGGER = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _parse_expiry(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


@dataclass(slots=True)
class _ActiveOperation:
    request: CapabilityRequest
    provider: CapabilityProvider
    task: asyncio.Task[CapabilityResult]


class CapabilityService:
    """Bounded execution boundary for device/service capability providers."""

    def __init__(self, settings: Settings, registry: CapabilityRegistry | None = None) -> None:
        self.settings = settings
        self.registry = registry or CapabilityRegistry()
        self._global_semaphore = asyncio.Semaphore(
            int(settings.capability_max_concurrent_executions)
        )
        self._provider_semaphores: dict[str, asyncio.Semaphore] = {}
        self._active: dict[str, _ActiveOperation] = {}
        self._provider_cancel_requests: set[str] = set()
        self._lock = asyncio.Lock()

    def register(self, provider: CapabilityProvider) -> None:
        self.registry.register(provider)
        limit = min(
            max(1, int(provider.max_concurrency)),
            int(self.settings.capability_provider_max_concurrent_executions),
        )
        self._provider_semaphores[provider.id] = asyncio.Semaphore(limit)

    def describe(self) -> dict[str, Any]:
        return {
            "api_version": 1,
            "provider_count": len(self.registry.providers()),
            "providers": self.registry.describe(),
            "limits": {
                "global_concurrency": int(self.settings.capability_max_concurrent_executions),
                "provider_concurrency_ceiling": int(
                    self.settings.capability_provider_max_concurrent_executions
                ),
                "default_timeout_seconds": float(
                    self.settings.capability_execution_timeout_seconds
                ),
                "max_arguments_bytes": int(self.settings.capability_max_arguments_bytes),
                "default_ttl_seconds": float(self.settings.capability_default_ttl_seconds),
            },
        }

    def active_operations(self) -> list[dict[str, Any]]:
        return [
            {
                "operation_id": active.request.operation_id,
                "capability": active.request.capability,
                "provider_id": active.provider.id,
                "plugin_id": active.request.plugin_id,
                "parent_action_id": active.request.parent_action_id,
                "created_at": active.request.created_at,
                "expires_at": active.request.expires_at,
            }
            for active in list(self._active.values())
        ]

    async def invoke(
        self,
        *,
        plugin_id: str,
        permissions: frozenset[str],
        capability: str,
        arguments: dict[str, Any] | None = None,
        parent_action_id: str | None = None,
        timeout_seconds: float | None = None,
        expires_in_seconds: float | None = None,
        expires_at: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CapabilityResult:
        resolved = self.registry.resolve(capability)
        if resolved is None:
            normalized = str(capability).strip().lower()
            raise KeyError(f"No capability provider registered for '{normalized}'")

        required_permission = permission_for_capability(resolved.descriptor.name)
        if resolved.descriptor.permission != required_permission:
            raise RuntimeError(
                f"Capability '{resolved.descriptor.name}' provider permission does not match "
                f"namespace requirement '{required_permission}'"
            )
        if required_permission not in permissions:
            raise CapabilityPermissionError(
                f"Plugin '{plugin_id}' requires undeclared permission '{required_permission}' "
                f"for capability '{resolved.descriptor.name}'"
            )

        resolved_arguments = dict(arguments or {})
        encoded = json.dumps(
            resolved_arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        if len(encoded) > int(self.settings.capability_max_arguments_bytes):
            raise ValueError(
                f"Capability arguments exceed {self.settings.capability_max_arguments_bytes} bytes"
            )

        created = _utc_now()
        expiry = _parse_expiry(expires_at)
        if expires_in_seconds is not None:
            ttl = max(0.0, float(expires_in_seconds))
            ttl = min(ttl, float(self.settings.capability_max_ttl_seconds))
            candidate = created + timedelta(seconds=ttl)
            expiry = min(expiry, candidate) if expiry else candidate
        elif expiry is None:
            expiry = created + timedelta(
                seconds=float(self.settings.capability_default_ttl_seconds)
            )

        operation_id = str(uuid.uuid4())
        request = CapabilityRequest(
            operation_id=operation_id,
            capability=resolved.descriptor.name,
            plugin_id=str(plugin_id),
            arguments=resolved_arguments,
            parent_action_id=parent_action_id,
            created_at=_iso(created),
            expires_at=_iso(expiry) if expiry else None,
            metadata=dict(metadata or {}),
        )

        if expiry is not None and expiry <= _utc_now():
            return self._terminal(
                request,
                resolved.provider,
                status="expired",
                error="Capability request expired before execution",
                error_code="capability_expired",
            )

        task = asyncio.create_task(
            self._run(
                request,
                resolved.provider,
                timeout_seconds=timeout_seconds,
            ),
            name=f"capability:{request.capability}:{operation_id}",
        )
        async with self._lock:
            self._active[operation_id] = _ActiveOperation(request, resolved.provider, task)
        try:
            return await task
        finally:
            async with self._lock:
                self._active.pop(operation_id, None)
            self._provider_cancel_requests.discard(operation_id)

    async def _run(
        self,
        request: CapabilityRequest,
        provider: CapabilityProvider,
        *,
        timeout_seconds: float | None,
    ) -> CapabilityResult:
        provider_semaphore = self._provider_semaphores.get(provider.id)
        if provider_semaphore is None:
            limit = min(
                max(1, int(provider.max_concurrency)),
                int(self.settings.capability_provider_max_concurrent_executions),
            )
            provider_semaphore = self._provider_semaphores.setdefault(
                provider.id, asyncio.Semaphore(limit)
            )

        try:
            async with self._global_semaphore:
                async with provider_semaphore:
                    expiry = _parse_expiry(request.expires_at)
                    now = _utc_now()
                    if expiry is not None and expiry <= now:
                        return self._terminal(
                            request,
                            provider,
                            status="expired",
                            error="Capability request expired while waiting for execution",
                            error_code="capability_expired",
                        )

                    base_timeout = (
                        float(timeout_seconds)
                        if timeout_seconds is not None
                        else (
                            float(provider.default_timeout_seconds)
                            if provider.default_timeout_seconds is not None
                            else float(self.settings.capability_execution_timeout_seconds)
                        )
                    )
                    base_timeout = max(0.05, min(base_timeout, 120.0))
                    deadline_limited = False
                    if expiry is not None:
                        remaining = max(0.0, (expiry - now).total_seconds())
                        if remaining <= base_timeout:
                            deadline_limited = True
                        base_timeout = min(base_timeout, remaining)
                    if base_timeout <= 0:
                        return self._terminal(
                            request,
                            provider,
                            status="expired",
                            error="Capability request expired before provider execution",
                            error_code="capability_expired",
                        )

                    try:
                        result = await asyncio.wait_for(
                            provider.execute(request), timeout=base_timeout
                        )
                    except asyncio.TimeoutError:
                        await self._cancel_provider_once(provider, request.operation_id)
                        # A timeout caused by the request deadline is expiry.
                        # Avoid a second wall-clock comparison because Windows
                        # timers may wake just before the nominal deadline.
                        expired = bool(deadline_limited and expiry is not None)
                        return self._terminal(
                            request,
                            provider,
                            status="expired" if expired else "timed_out",
                            error=(
                                "Capability request expired during execution"
                                if expired
                                else f"Capability '{request.capability}' timed out"
                            ),
                            error_code=(
                                "capability_expired" if expired else "capability_timeout"
                            ),
                        )
                    except asyncio.CancelledError:
                        await self._cancel_provider_once(provider, request.operation_id)
                        raise
                    except Exception as exc:
                        LOGGER.exception(
                            "Capability provider '%s' failed operation '%s'",
                            provider.id,
                            request.operation_id,
                        )
                        return self._terminal(
                            request,
                            provider,
                            status="failed",
                            error=str(exc),
                            error_code="capability_failed",
                        )

                    if not isinstance(result, CapabilityResult):
                        return self._terminal(
                            request,
                            provider,
                            status="failed",
                            error="Capability provider returned an invalid result type",
                            error_code="invalid_provider_result",
                        )
                    result.operation_id = request.operation_id
                    result.capability = request.capability
                    result.provider_id = provider.id
                    return result
        except asyncio.CancelledError:
            raise

    async def cancel_operation(self, operation_id: str) -> bool:
        async with self._lock:
            active = self._active.get(str(operation_id))
        if active is None:
            return False
        if not active.task.done():
            active.task.cancel()
        # Notify the provider explicitly. A task can be cancelled before its
        # coroutine gets a first execution slice, in which case _run() never
        # gets a chance to catch CancelledError and call provider.cancel().
        await self._cancel_provider_once(active.provider, active.request.operation_id)
        if active.task is not asyncio.current_task():
            await asyncio.gather(active.task, return_exceptions=True)
        return True

    async def cancel_parent(self, parent_action_id: str) -> int:
        operation_ids = [
            item.request.operation_id
            for item in list(self._active.values())
            if item.request.parent_action_id == parent_action_id
        ]
        cancelled = 0
        for operation_id in operation_ids:
            cancelled += int(await self.cancel_operation(operation_id))
        return cancelled

    async def cancel_plugin(self, plugin_id: str) -> int:
        operation_ids = [
            item.request.operation_id
            for item in list(self._active.values())
            if item.request.plugin_id == plugin_id
        ]
        cancelled = 0
        for operation_id in operation_ids:
            cancelled += int(await self.cancel_operation(operation_id))
        return cancelled

    async def shutdown(self) -> None:
        for operation_id in [item["operation_id"] for item in self.active_operations()]:
            await self.cancel_operation(str(operation_id))
        for provider in self.registry.providers():
            try:
                await asyncio.wait_for(
                    provider.shutdown(),
                    timeout=float(self.settings.capability_provider_shutdown_timeout_seconds),
                )
            except asyncio.TimeoutError:
                LOGGER.warning("Capability provider '%s' shutdown timed out", provider.id)
            except Exception:
                LOGGER.exception("Capability provider '%s' shutdown failed", provider.id)

    async def _cancel_provider_once(
        self, provider: CapabilityProvider, operation_id: str
    ) -> None:
        # Mark before awaiting so concurrent cancellation paths on the same
        # event loop cannot notify a provider twice for one operation.
        resolved = str(operation_id)
        if resolved in self._provider_cancel_requests:
            return
        self._provider_cancel_requests.add(resolved)
        await self._cancel_provider(provider, resolved)

    async def _cancel_provider(self, provider: CapabilityProvider, operation_id: str) -> None:
        try:
            await asyncio.wait_for(
                provider.cancel(operation_id),
                timeout=float(self.settings.capability_cancel_timeout_seconds),
            )
        except asyncio.TimeoutError:
            LOGGER.warning(
                "Capability provider '%s' cancellation timed out for '%s'",
                provider.id,
                operation_id,
            )
        except Exception:
            LOGGER.exception(
                "Capability provider '%s' cancellation failed for '%s'",
                provider.id,
                operation_id,
            )

    @staticmethod
    def _terminal(
        request: CapabilityRequest,
        provider: CapabilityProvider,
        *,
        status: str,
        error: str,
        error_code: str,
    ) -> CapabilityResult:
        return CapabilityResult(
            operation_id=request.operation_id,
            capability=request.capability,
            provider_id=provider.id,
            success=False,
            status=status,
            verified=False,
            error=error,
            error_code=error_code,
        )


__all__ = ["CapabilityService"]
