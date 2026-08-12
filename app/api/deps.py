from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from app.state import state


def require_token(
    x_session_token: Annotated[str | None, Header()] = None,
) -> str:
    if not state.controller.validate(x_session_token):
        raise HTTPException(status_code=401, detail="Controller session is not active")
    return str(x_session_token)


Token = Annotated[str, Depends(require_token)]

__all__ = ["Token", "require_token"]
