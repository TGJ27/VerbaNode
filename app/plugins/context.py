from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.config import Settings


@dataclass(slots=True)
class PluginContext:
    """Runtime context shared with built-in capability plugins.

    Only stable, capability-level dependencies belong here.  Plugins should not
    import the conversation manager, database, audio engine, or web API.  More
    services can be added later without changing the plugin execution contract.
    """

    settings: Settings
    text: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
