from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PluginResult:
    """Normalized capability result.

    ``data``/``response`` preserve the existing tool contract. The additional
    action fields establish the verified execution contract used by future
    robot/device capabilities.
    """

    data: dict[str, Any] = field(default_factory=dict)
    response: str | None = None
    stop_conversation: bool = False
    success: bool = True
    status: str = "completed"
    action_id: str | None = None
    error_code: str | None = None
    verified: bool = True

    def as_tool_result(self) -> dict[str, Any]:
        payload = dict(self.data)
        if self.stop_conversation:
            payload.setdefault("conversation_should_stop", True)
        if self.response:
            payload.setdefault("message", self.response)
        return payload
