from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket

from app.api.protocol import event_envelope


class EventHub:
    """Fan-out hub for versioned WebSocket events.

    Protocol v1 keeps the legacy ``event`` field so the v0.7 dashboard and new
    clients can coexist while mobile/native clients consume ``protocol`` and
    ``type`` explicitly.
    """

    def __init__(self) -> None:
        self._clients: dict[str, WebSocket] = {}
        self._lock = asyncio.Lock()

    async def connect(self, token: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            old = self._clients.get(token)
            self._clients[token] = websocket
        if old is not None and old is not websocket:
            try:
                await old.close(code=4001)
            except Exception:
                pass

    async def disconnect(self, token: str, websocket: WebSocket | None = None) -> None:
        async with self._lock:
            current = self._clients.get(token)
            if websocket is None or current is websocket:
                self._clients.pop(token, None)

    async def send(
        self,
        token: str,
        event: str,
        data: Any = None,
        *,
        request_id: str | None = None,
    ) -> bool:
        async with self._lock:
            ws = self._clients.get(token)
        if ws is None:
            return False
        try:
            await ws.send_text(
                json.dumps(
                    event_envelope(event, data, request_id=request_id),
                    ensure_ascii=False,
                )
            )
            return True
        except Exception:
            await self.disconnect(token, ws)
            return False

    async def broadcast(self, event: str, data: Any = None) -> None:
        async with self._lock:
            items = list(self._clients.items())
        payload = json.dumps(event_envelope(event, data), ensure_ascii=False)
        stale: list[tuple[str, WebSocket]] = []
        for token, ws in items:
            try:
                await ws.send_text(payload)
            except Exception:
                stale.append((token, ws))
        for token, ws in stale:
            await self.disconnect(token, ws)

    async def is_connected(self, token: str) -> bool:
        """Return whether ``token`` currently owns a live WebSocket slot.

        The lookup is lock-protected so reconnect/disconnect cleanup can make a
        reliable decision without racing a replacement socket for the same
        controller token.
        """
        async with self._lock:
            return token in self._clients

    def connected_tokens(self) -> set[str]:
        return set(self._clients)
