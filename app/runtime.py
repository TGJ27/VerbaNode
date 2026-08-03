from __future__ import annotations

import asyncio
import logging
from typing import Any

LOGGER = logging.getLogger(__name__)


def is_expected_windows_proactor_reset(context: dict[str, Any]) -> bool:
    """Identify only the harmless Windows HTTPS disconnect cleanup error."""
    exc = context.get("exception")
    if not isinstance(exc, ConnectionResetError):
        return False
    error_code = getattr(exc, "winerror", None) or getattr(exc, "errno", None)
    if error_code != 10054:
        return False
    callback_text = f"{context.get('handle', '')} {context.get('message', '')}"
    return "_ProactorBasePipeTransport._call_connection_lost" in callback_text


def install_asyncio_exception_filter(loop: asyncio.AbstractEventLoop | None = None) -> None:
    """Suppress expected WinError 10054 cleanup noise and preserve all real errors."""
    loop = loop or asyncio.get_running_loop()
    previous_handler = loop.get_exception_handler()

    def exception_handler(
        current_loop: asyncio.AbstractEventLoop,
        context: dict[str, Any],
    ) -> None:
        if is_expected_windows_proactor_reset(context):
            LOGGER.debug(
                "Ignored expected Windows client connection reset during HTTPS cleanup"
            )
            return
        if previous_handler is not None:
            previous_handler(current_loop, context)
        else:
            current_loop.default_exception_handler(context)

    loop.set_exception_handler(exception_handler)
