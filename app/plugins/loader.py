from __future__ import annotations

import importlib.util
import json
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from app.plugins.base import Plugin
from app.plugins.exceptions import (
    PluginCompatibilityError,
    PluginLoadError,
    PluginManifestError,
)
from app.plugins.models import ExternalPluginManifest

SUPPORTED_SDK_MAJOR = "1"
PLUGIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")


@dataclass(slots=True)
class LoadedExternalPlugin:
    plugin: Plugin
    manifest: ExternalPluginManifest
    folder: Path
    manifest_path: Path
    entry_path: Path
    module_name: str
    module: ModuleType


class ExternalPluginLoader:
    """Validate and load one trusted local plugin folder."""

    def load(self, folder: Path) -> LoadedExternalPlugin:
        folder = folder.resolve()
        manifest_path = folder / "plugin.json"
        if not manifest_path.is_file():
            raise PluginManifestError("plugin.json is missing")

        raw = self._read_manifest(manifest_path)
        manifest = self._parse_manifest(raw)
        entry_path = self._resolve_entry(folder, manifest.entry)
        module_name = self._module_name(manifest.id, folder)
        module = self._import_module(module_name, entry_path)
        plugin = self._create_plugin(module)
        self._apply_manifest(plugin, manifest, folder, manifest_path)
        return LoadedExternalPlugin(
            plugin=plugin,
            manifest=manifest,
            folder=folder,
            manifest_path=manifest_path,
            entry_path=entry_path,
            module_name=module_name,
            module=module,
        )

    @staticmethod
    def unload_module(module_name: str) -> None:
        for loaded_name in list(sys.modules):
            if loaded_name == module_name or loaded_name.startswith(module_name + "."):
                sys.modules.pop(loaded_name, None)

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PluginManifestError(f"plugin.json is invalid JSON: {exc}") from exc
        except OSError as exc:
            raise PluginManifestError(f"plugin.json could not be read: {exc}") from exc
        if not isinstance(value, dict):
            raise PluginManifestError("plugin.json must contain a JSON object")
        return value

    @staticmethod
    def _parse_manifest(raw: dict[str, Any]) -> ExternalPluginManifest:
        required = ("id", "name", "version", "author", "description", "entry", "sdk_version")
        missing = [key for key in required if not str(raw.get(key, "")).strip()]
        if missing:
            raise PluginManifestError("Missing required manifest fields: " + ", ".join(missing))

        plugin_id = str(raw["id"]).strip()
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginManifestError(
                "Plugin id must start with a lowercase letter and contain only lowercase letters, numbers, and underscores"
            )

        sdk_version = str(raw["sdk_version"]).strip()
        sdk_major = sdk_version.split(".", 1)[0]
        if sdk_major != SUPPORTED_SDK_MAJOR:
            raise PluginCompatibilityError(
                f"Unsupported SDK version '{sdk_version}'; VerbaNode supports SDK major {SUPPORTED_SDK_MAJOR}"
            )

        permissions_raw = raw.get("permissions", [])
        if permissions_raw is None:
            permissions_raw = []
        if not isinstance(permissions_raw, list) or not all(
            isinstance(item, str) and item.strip() for item in permissions_raw
        ):
            raise PluginManifestError("permissions must be an array of non-empty strings")

        try:
            priority = int(raw.get("priority", 200))
        except (TypeError, ValueError) as exc:
            raise PluginManifestError("priority must be an integer") from exc
        if not 0 <= priority <= 10000:
            raise PluginManifestError("priority must be between 0 and 10000")

        return ExternalPluginManifest(
            id=plugin_id,
            name=str(raw["name"]).strip(),
            version=str(raw["version"]).strip(),
            author=str(raw["author"]).strip(),
            description=str(raw["description"]).strip(),
            entry=str(raw["entry"]).strip(),
            sdk_version=sdk_version,
            category=str(raw.get("category") or "External").strip(),
            permissions=tuple(dict.fromkeys(item.strip() for item in permissions_raw)),
            priority=priority,
        )

    @staticmethod
    def _resolve_entry(folder: Path, entry: str) -> Path:
        entry_path = (folder / entry).resolve()
        try:
            entry_path.relative_to(folder)
        except ValueError as exc:
            raise PluginManifestError("entry must stay inside the plugin folder") from exc
        if not entry_path.is_file() or entry_path.suffix.lower() != ".py":
            raise PluginManifestError(f"Plugin entry '{entry}' is not a Python file")
        return entry_path

    @staticmethod
    def _module_name(plugin_id: str, folder: Path) -> str:
        stamp = uuid.uuid4().hex
        return f"verbanode_external_{plugin_id}_{stamp}"

    @staticmethod
    def _import_module(module_name: str, entry_path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(
            module_name, entry_path, submodule_search_locations=[str(entry_path.parent)]
        )
        if spec is None or spec.loader is None:
            raise PluginLoadError(f"Could not create an import specification for {entry_path.name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception as exc:
            sys.modules.pop(module_name, None)
            raise PluginLoadError(f"Import failed: {exc}") from exc
        return module

    @staticmethod
    def _create_plugin(module: ModuleType) -> Plugin:
        factory = getattr(module, "create_plugin", None)
        if not callable(factory):
            raise PluginLoadError("plugin.py must export a callable create_plugin()")
        try:
            plugin = factory()
        except Exception as exc:
            raise PluginLoadError(f"create_plugin() failed: {exc}") from exc
        if not isinstance(plugin, Plugin):
            raise PluginLoadError("create_plugin() must return an app.plugins.Plugin instance")
        return plugin

    @staticmethod
    def _apply_manifest(
        plugin: Plugin,
        manifest: ExternalPluginManifest,
        folder: Path,
        manifest_path: Path,
    ) -> None:
        plugin.id = manifest.id
        plugin.name = manifest.name
        plugin.version = manifest.version
        plugin.author = manifest.author
        plugin.description = manifest.description
        plugin.category = manifest.category
        plugin.permissions = manifest.permissions
        plugin.priority = manifest.priority
        plugin.source = "external"
        plugin.plugin_path = folder
        plugin.manifest_path = manifest_path
        plugin.reloadable = True
        plugin.sdk_version = manifest.sdk_version

        if not isinstance(plugin.schema, dict):
            raise PluginLoadError("Plugin schema must be a dictionary")
        function = plugin.schema.get("function") if plugin.schema else None
        if not isinstance(function, dict) or function.get("name") != manifest.id:
            raise PluginLoadError(
                f"Plugin tool schema function.name must equal manifest id '{manifest.id}'"
            )
