from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PluginResult:
    """Normalized result returned by an internal capability plugin.

    Phase 1 keeps the public tool API dictionary-based for backwards
    compatibility.  This model gives each plugin a consistent internal return
    type and leaves room for future UI, permission, and lifecycle metadata.
    """

    data: dict[str, Any] = field(default_factory=dict)
    response: str | None = None
    stop_conversation: bool = False

    def as_tool_result(self) -> dict[str, Any]:
        payload = dict(self.data)
        if self.stop_conversation:
            payload.setdefault("conversation_should_stop", True)
        if self.response:
            payload.setdefault("message", self.response)
        return payload
