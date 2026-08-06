from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class ExternalPluginManifest:
    id: str
    name: str
    version: str
    author: str
    description: str
    entry: str
    sdk_version: str
    category: str = "External"
    permissions: tuple[str, ...] = ()
    priority: int = 200


@dataclass(slots=True)
class ExternalPluginFailure:
    key: str
    folder: Path
    manifest_path: Path | None
    name: str
    plugin_id: str | None
    error: str
    status: str = "load_error"
    category: str = "External"
    version: str = "unknown"
    author: str = "Unknown"
    permissions: tuple[str, ...] = ()
    sdk_version: str = "unknown"
    entry: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PluginRuntimeState:
    status: str = "healthy"
    active_executions: int = 0
    reloads: int = 0
    reload_errors: int = 0
    last_reload_error: str | None = None
    state_changed_at: float = 0.0
