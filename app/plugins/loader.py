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

from app.capabilities.permissions import ALLOWED_PERMISSIONS
from app.plugins.base import Plugin
from app.plugins.exceptions import (
    PluginCompatibilityError,
    PluginLoadError,
    PluginManifestError,
    PluginSchemaError,
)
from app.plugins.models import ExternalPluginManifest

SUPPORTED_SDK_MAJOR = "1"
PLUGIN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
FOLDER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)
ALLOWED_MANIFEST_FIELDS = frozenset(
    {
        "id",
        "name",
        "version",
        "author",
        "description",
        "entry",
        "sdk_version",
        "category",
        "permissions",
        "priority",
        "homepage",
        "license",
    }
)
ALLOWED_SCHEMA_TYPES = frozenset(
    {"string", "number", "integer", "boolean", "object", "array", "null"}
)


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
    """Validate and load one trusted local plugin folder.

    This protects VerbaNode from malformed plugin packages and accidental path
    traversal. External Python code is still trusted code and is not a security
    sandbox.
    """

    def __init__(
        self,
        *,
        manifest_max_bytes: int = 64 * 1024,
        entry_max_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.manifest_max_bytes = int(manifest_max_bytes)
        self.entry_max_bytes = int(entry_max_bytes)

    def load(self, folder: Path) -> LoadedExternalPlugin:
        if folder.is_symlink():
            raise PluginManifestError("Plugin folders may not be symbolic links")
        folder = folder.resolve()
        self._validate_folder(folder)
        manifest_path = folder / "plugin.json"
        if not manifest_path.is_file():
            raise PluginManifestError("plugin.json is missing")
        if manifest_path.is_symlink():
            raise PluginManifestError("plugin.json may not be a symbolic link")

        raw = self._read_manifest(manifest_path)
        manifest = self._parse_manifest(raw)
        entry_path = self._resolve_entry(folder, manifest.entry)
        module_name = self._module_name(manifest.id)
        module = self._import_module(module_name, entry_path)
        try:
            plugin = self._create_plugin(module)
            self._apply_manifest(plugin, manifest, folder, manifest_path)
            validate_tool_schema(plugin.schema, manifest.id)
        except Exception:
            self.unload_module(module_name)
            raise
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
    def _validate_folder(folder: Path) -> None:
        if not folder.exists() or not folder.is_dir():
            raise PluginManifestError("Plugin folder does not exist")
        if folder.is_symlink():
            raise PluginManifestError("Plugin folders may not be symbolic links")
        if not FOLDER_PATTERN.fullmatch(folder.name):
            raise PluginManifestError(
                "Plugin folder names may contain only letters, numbers, dots, underscores, and hyphens"
            )

    def _read_manifest(self, path: Path) -> dict[str, Any]:
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise PluginManifestError(f"plugin.json could not be inspected: {exc}") from exc
        if size > self.manifest_max_bytes:
            raise PluginManifestError(
                f"plugin.json exceeds the {self.manifest_max_bytes}-byte size limit"
            )
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError as exc:
            raise PluginManifestError("plugin.json must be UTF-8") from exc
        except json.JSONDecodeError as exc:
            raise PluginManifestError(f"plugin.json is invalid JSON: {exc}") from exc
        except OSError as exc:
            raise PluginManifestError(f"plugin.json could not be read: {exc}") from exc
        if not isinstance(value, dict):
            raise PluginManifestError("plugin.json must contain a JSON object")
        unsupported = sorted(
            key
            for key in value
            if key not in ALLOWED_MANIFEST_FIELDS and not str(key).startswith("x_")
        )
        if unsupported:
            raise PluginManifestError(
                "Unsupported manifest fields: " + ", ".join(unsupported)
            )
        return value

    @staticmethod
    def _bounded_text(raw: dict[str, Any], key: str, maximum: int) -> str:
        value = str(raw.get(key, "")).strip()
        if not value:
            raise PluginManifestError(f"Manifest field '{key}' is required")
        if len(value) > maximum:
            raise PluginManifestError(
                f"Manifest field '{key}' exceeds {maximum} characters"
            )
        return value

    @classmethod
    def _parse_manifest(cls, raw: dict[str, Any]) -> ExternalPluginManifest:
        plugin_id = cls._bounded_text(raw, "id", 64)
        if not PLUGIN_ID_PATTERN.fullmatch(plugin_id):
            raise PluginManifestError(
                "Plugin id must start with a lowercase letter and contain only lowercase letters, numbers, and underscores"
            )

        name = cls._bounded_text(raw, "name", 100)
        version = cls._bounded_text(raw, "version", 64)
        if not SEMVER_PATTERN.fullmatch(version):
            raise PluginManifestError("version must use semantic versioning, for example 1.0.0")
        author = cls._bounded_text(raw, "author", 120)
        description = cls._bounded_text(raw, "description", 1000)
        entry = cls._bounded_text(raw, "entry", 160)
        sdk_version = cls._bounded_text(raw, "sdk_version", 32)
        sdk_major = sdk_version.split(".", 1)[0]
        if sdk_major != SUPPORTED_SDK_MAJOR:
            raise PluginCompatibilityError(
                f"Unsupported SDK version '{sdk_version}'; VerbaNode supports SDK major {SUPPORTED_SDK_MAJOR}"
            )

        category = str(raw.get("category") or "External").strip()
        if not category or len(category) > 80:
            raise PluginManifestError("category must contain 1 to 80 characters")

        permissions_raw = raw.get("permissions", [])
        if permissions_raw is None:
            permissions_raw = []
        if not isinstance(permissions_raw, list) or not all(
            isinstance(item, str) and item.strip() for item in permissions_raw
        ):
            raise PluginManifestError("permissions must be an array of non-empty strings")
        permissions = tuple(dict.fromkeys(item.strip() for item in permissions_raw))
        unknown_permissions = sorted(set(permissions) - ALLOWED_PERMISSIONS)
        if unknown_permissions:
            raise PluginManifestError(
                "Unsupported permissions: " + ", ".join(unknown_permissions)
            )

        try:
            priority = int(raw.get("priority", 200))
        except (TypeError, ValueError) as exc:
            raise PluginManifestError("priority must be an integer") from exc
        if not 0 <= priority <= 10000:
            raise PluginManifestError("priority must be between 0 and 10000")

        return ExternalPluginManifest(
            id=plugin_id,
            name=name,
            version=version,
            author=author,
            description=description,
            entry=entry,
            sdk_version=sdk_version,
            category=category,
            permissions=permissions,
            priority=priority,
        )

    def _resolve_entry(self, folder: Path, entry: str) -> Path:
        candidate = folder / entry
        if candidate.is_symlink():
            raise PluginManifestError("Plugin entry files may not be symbolic links")
        entry_path = candidate.resolve()
        try:
            entry_path.relative_to(folder)
        except ValueError as exc:
            raise PluginManifestError("entry must stay inside the plugin folder") from exc
        if not entry_path.is_file() or entry_path.suffix.lower() != ".py":
            raise PluginManifestError(f"Plugin entry '{entry}' is not a Python file")
        try:
            size = entry_path.stat().st_size
        except OSError as exc:
            raise PluginManifestError(f"Plugin entry could not be inspected: {exc}") from exc
        if size > self.entry_max_bytes:
            raise PluginManifestError(
                f"Plugin entry exceeds the {self.entry_max_bytes}-byte size limit"
            )
        return entry_path

    @staticmethod
    def _module_name(plugin_id: str) -> str:
        return f"verbanode_external_{plugin_id}_{uuid.uuid4().hex}"

    @staticmethod
    def _import_module(module_name: str, entry_path: Path) -> ModuleType:
        spec = importlib.util.spec_from_file_location(
            module_name,
            entry_path,
            submodule_search_locations=[str(entry_path.parent)],
        )
        if spec is None or spec.loader is None:
            raise PluginLoadError(
                f"Could not create an import specification for {entry_path.name}"
            )
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
            raise PluginLoadError(
                "create_plugin() must return an app.plugins.Plugin instance"
            )
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


def validate_tool_schema(schema: Any, expected_name: str) -> None:
    if not isinstance(schema, dict):
        raise PluginSchemaError("Plugin schema must be a dictionary")
    if schema.get("type") != "function":
        raise PluginSchemaError("Plugin schema type must be 'function'")
    function = schema.get("function")
    if not isinstance(function, dict):
        raise PluginSchemaError("Plugin schema must contain a function object")
    if function.get("name") != expected_name:
        raise PluginSchemaError(
            f"Plugin tool schema function.name must equal plugin id '{expected_name}'"
        )
    description = function.get("description")
    if not isinstance(description, str) or not description.strip():
        raise PluginSchemaError("Plugin tool schema requires a non-empty description")
    if len(description) > 2000:
        raise PluginSchemaError("Plugin tool description exceeds 2000 characters")
    parameters = function.get("parameters", {"type": "object", "properties": {}})
    _validate_json_schema(parameters, path="function.parameters", depth=0)
    if parameters.get("type") != "object":
        raise PluginSchemaError("function.parameters must have type 'object'")


def _validate_json_schema(value: Any, *, path: str, depth: int) -> None:
    if depth > 8:
        raise PluginSchemaError(f"{path} exceeds the maximum schema depth")
    if not isinstance(value, dict):
        raise PluginSchemaError(f"{path} must be an object")
    schema_type = value.get("type")
    if schema_type is not None and schema_type not in ALLOWED_SCHEMA_TYPES:
        raise PluginSchemaError(f"{path}.type '{schema_type}' is unsupported")
    description = value.get("description")
    if description is not None and not isinstance(description, str):
        raise PluginSchemaError(f"{path}.description must be a string")
    enum = value.get("enum")
    if enum is not None and (not isinstance(enum, list) or len(enum) > 100):
        raise PluginSchemaError(f"{path}.enum must be an array with at most 100 values")

    properties = value.get("properties", {})
    if properties is not None:
        if not isinstance(properties, dict):
            raise PluginSchemaError(f"{path}.properties must be an object")
        if len(properties) > 64:
            raise PluginSchemaError(f"{path}.properties exceeds 64 fields")
        for name, child in properties.items():
            if not isinstance(name, str) or not PLUGIN_ID_PATTERN.fullmatch(name):
                raise PluginSchemaError(
                    f"{path}.properties contains invalid field name '{name}'"
                )
            _validate_json_schema(child, path=f"{path}.properties.{name}", depth=depth + 1)

    required = value.get("required", [])
    if required is not None:
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise PluginSchemaError(f"{path}.required must be an array of strings")
        missing = sorted(set(required) - set(properties or {}))
        if missing:
            raise PluginSchemaError(
                f"{path}.required references unknown properties: {', '.join(missing)}"
            )

    items = value.get("items")
    if items is not None:
        _validate_json_schema(items, path=f"{path}.items", depth=depth + 1)
