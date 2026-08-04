from __future__ import annotations

import inspect
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from app.config import Settings
from app.plugins.base import Plugin
from app.plugins.context import PluginContext
from app.plugins.loader import ExternalPluginLoader, LoadedExternalPlugin
from app.plugins.models import ExternalPluginFailure
from app.plugins.registry import PluginRegistry

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class PluginMetrics:
    executions: int = 0
    errors: int = 0
    total_latency_ms: float = 0.0
    last_latency_ms: float = 0.0
    last_error: str | None = None

    @property
    def average_latency_ms(self) -> float:
        if not self.executions:
            return 0.0
        return self.total_latency_ms / self.executions

    def reset(self) -> None:
        self.executions = 0
        self.errors = 0
        self.total_latency_ms = 0.0
        self.last_latency_ms = 0.0
        self.last_error = None


class PluginManager:
    """Coordinates built-in and trusted local external plugins."""

    def __init__(self, settings: Settings, registry: PluginRegistry | None = None) -> None:
        self.settings = settings
        self.registry = registry or PluginRegistry()
        self._metrics: dict[str, PluginMetrics] = {}
        self._disabled_ids: set[str] = set()
        self._external_dir: Path | None = None
        self._external_loaded: dict[str, LoadedExternalPlugin] = {}
        self._external_failures: dict[str, ExternalPluginFailure] = {}
        self._loader = ExternalPluginLoader()

    def register(self, plugin: Plugin) -> None:
        plugin.enabled = plugin.id not in self._disabled_ids
        self.registry.register(plugin)
        self._metrics.setdefault(plugin.id, PluginMetrics())

    def configure_disabled(self, plugin_ids: Iterable[str]) -> None:
        self._disabled_ids = {str(plugin_id) for plugin_id in plugin_ids}
        for plugin in self.registry.list():
            plugin.enabled = plugin.id not in self._disabled_ids

    def disabled_ids(self) -> list[str]:
        return sorted(
            plugin.id for plugin in self.registry.list() if not plugin.enabled
        )

    def set_enabled(self, plugin_id: str, enabled: bool) -> dict[str, Any]:
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            raise KeyError(plugin_id)
        plugin.enabled = bool(enabled)
        if plugin.enabled:
            self._disabled_ids.discard(plugin_id)
        else:
            self._disabled_ids.add(plugin_id)
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
        return self.registry.schemas(enabled)

    def match_core_intent(
        self,
        text: str,
        enabled: list[str],
    ) -> tuple[str, dict[str, Any]] | None:
        enabled_set = set(enabled or [])
        for plugin in self.registry.list():
            if not plugin.enabled or plugin.id not in enabled_set:
                continue
            try:
                arguments = plugin.match(
                    PluginContext(settings=self.settings, text=text)
                )
            except Exception as exc:
                metric = self._metrics.setdefault(plugin.id, PluginMetrics())
                metric.errors += 1
                metric.last_error = f"Intent matching failed: {exc}"
                LOGGER.exception("%s plugin '%s' intent matching failed", plugin.source.capitalize(), plugin.id)
                continue
            if arguments is not None:
                return plugin.id, arguments
        return None

    async def execute(
        self,
        plugin_id: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            return {"error": f"Unknown tool: {plugin_id}"}
        if not plugin.enabled:
            return {"error": f"Tool '{plugin_id}' is disabled"}

        metric = self._metrics.setdefault(plugin_id, PluginMetrics())
        started = time.perf_counter()
        try:
            result = await plugin.execute(
                PluginContext(
                    settings=self.settings,
                    arguments=dict(arguments or {}),
                )
            )
            metric.last_error = None
            return result.as_tool_result()
        except Exception as exc:
            metric.errors += 1
            metric.last_error = str(exc)
            LOGGER.exception("%s plugin '%s' failed", plugin.source.capitalize(), plugin_id)
            return {"error": f"Tool '{plugin_id}' failed: {exc}"}
        finally:
            latency_ms = (time.perf_counter() - started) * 1000.0
            metric.executions += 1
            metric.last_latency_ms = latency_ms
            metric.total_latency_ms += latency_ms

    def format_result(self, plugin_id: str, result: dict[str, Any]) -> str:
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            return str(result.get("error") or result.get("message") or result)
        try:
            return plugin.format_result(
                result,
                PluginContext(settings=self.settings),
            )
        except Exception as exc:
            metric = self._metrics.setdefault(plugin.id, PluginMetrics())
            metric.errors += 1
            metric.last_error = f"Result formatting failed: {exc}"
            LOGGER.exception("%s plugin '%s' result formatting failed", plugin.source.capitalize(), plugin.id)
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
                    raise ValueError(f"Plugin id '{record.plugin.id}' is already registered")
                record.plugin.enabled = record.plugin.id not in self._disabled_ids
                self.registry.register(record.plugin)
                self._external_loaded[record.plugin.id] = record
                self._metrics.setdefault(record.plugin.id, PluginMetrics())
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
        for plugin_id in list(self._external_loaded):
            await self._unload_external(plugin_id)

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
        healthy = metric.last_error is None
        status = "disabled" if not plugin.enabled else "healthy" if healthy else "error"
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
            "errors": metric.errors,
            "average_latency_ms": round(metric.average_latency_ms, 2),
            "last_latency_ms": round(metric.last_latency_ms, 2),
            "last_error": metric.last_error,
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
        loaded_items = [item for item in items if item.get("status") != "load_error"]
        return {
            "total": len(items),
            "loaded": len(loaded_items),
            "builtin": sum(1 for item in loaded_items if item.get("source") == "builtin"),
            "external": sum(1 for item in loaded_items if item.get("source") == "external"),
            "failed_loads": sum(1 for item in items if item.get("status") == "load_error"),
            "enabled": sum(1 for item in loaded_items if item["enabled"]),
            "disabled": sum(1 for item in loaded_items if not item["enabled"]),
            "healthy": sum(
                1 for item in loaded_items if item["enabled"] and item["healthy"]
            ),
            "errors": sum(int(item["errors"]) for item in loaded_items)
            + sum(1 for item in items if item.get("status") == "load_error"),
            "executions": sum(int(item["executions"]) for item in loaded_items),
        }

    async def _reload_all_external(self) -> None:
        folders = self._candidate_folders(self._external_dir or self.settings.external_plugins_dir)
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
        try:
            candidate = self._loader.load(folder)
            if expected_id is not None and candidate.plugin.id != expected_id:
                raise ValueError(
                    f"Reload changed plugin id from '{expected_id}' to '{candidate.plugin.id}'"
                )
            existing = self.registry.get(candidate.plugin.id)
            if existing is not None:
                old_record = self._external_loaded.get(candidate.plugin.id)
                if old_record is None or old_record.folder.resolve() != folder.resolve():
                    raise ValueError(f"Plugin id '{candidate.plugin.id}' is already registered")
                candidate.plugin.enabled = existing.enabled
                self.registry.replace(candidate.plugin)
                self._external_loaded[candidate.plugin.id] = candidate
                await self._shutdown_plugin(existing)
                self._loader.unload_module(old_record.module_name)
            else:
                candidate.plugin.enabled = candidate.plugin.id not in self._disabled_ids
                self.registry.register(candidate.plugin)
                self._external_loaded[candidate.plugin.id] = candidate
                self._metrics.setdefault(candidate.plugin.id, PluginMetrics())
            self._remove_failures_for_folder(folder)
            LOGGER.info("External plugin loaded: %s v%s", candidate.plugin.id, candidate.plugin.version)
        except Exception as exc:
            failure = self._failure_from_folder(folder, exc)
            self._external_failures[failure.key] = failure
            LOGGER.exception("External plugin in '%s' could not be reloaded", folder.name)

    async def _unload_external(self, plugin_id: str) -> None:
        record = self._external_loaded.pop(plugin_id, None)
        plugin = self.registry.unregister(plugin_id)
        if plugin is not None:
            await self._shutdown_plugin(plugin)
        if record is not None:
            self._loader.unload_module(record.module_name)
        self._metrics.pop(plugin_id, None)

    @staticmethod
    async def _shutdown_plugin(plugin: Plugin) -> None:
        try:
            value = plugin.shutdown()
            if inspect.isawaitable(value):
                await value
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
        return ExternalPluginFailure(
            key=key,
            folder=folder.resolve(),
            manifest_path=manifest_path if manifest_path.exists() else None,
            name=str(raw.get("name") or folder.name),
            plugin_id=declared_id,
            error=str(exc),
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
            "description": "External plugin failed during discovery or reload.",
            "category": failure.category,
            "permissions": list(failure.permissions),
            "priority": 10000,
            "enabled": False,
            "healthy": False,
            "status": "load_error",
            "source": "external",
            "external": True,
            "reloadable": True,
            "sdk_version": failure.sdk_version,
            "plugin_path": str(failure.folder),
            "manifest_path": str(failure.manifest_path) if failure.manifest_path else None,
            "tool_name": failure.plugin_id or failure.key,
            "tool_description": "Plugin is unavailable until its load error is fixed.",
            "executions": 0,
            "errors": 1,
            "average_latency_ms": 0.0,
            "last_latency_ms": 0.0,
            "last_error": failure.error,
        }

    def _remove_failures_for_folder(self, folder: Path) -> None:
        target = folder.resolve()
        for key, failure in list(self._external_failures.items()):
            if failure.folder.resolve() == target:
                self._external_failures.pop(key, None)
