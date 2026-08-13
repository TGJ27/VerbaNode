from __future__ import annotations

import contextvars
import logging
import re
import uuid
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response

from app.api.protocol import API_VERSION, PROTOCOL_VERSION
from app.version import APP_VERSION

_REQUEST_ID = contextvars.ContextVar("verbanode_request_id", default="-")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")
_LOG_RECORD_FACTORY_INSTALLED = False


def current_request_id() -> str:
    return _REQUEST_ID.get()


def _resolve_request_id(request: Request) -> str:
    supplied = (request.headers.get("X-Request-ID") or "").strip()
    if supplied and _REQUEST_ID_RE.fullmatch(supplied):
        return supplied
    return uuid.uuid4().hex


def install_request_id_logging() -> None:
    """Add ``request_id`` to every log record without requiring adapter objects."""
    global _LOG_RECORD_FACTORY_INSTALLED
    if _LOG_RECORD_FACTORY_INSTALLED:
        return
    previous_factory = logging.getLogRecordFactory()

    def record_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = previous_factory(*args, **kwargs)
        record.request_id = current_request_id()
        return record

    logging.setLogRecordFactory(record_factory)
    _LOG_RECORD_FACTORY_INSTALLED = True


async def request_context_middleware(request: Request, call_next) -> Response:
    request_id = _resolve_request_id(request)
    request.state.request_id = request_id
    token = _REQUEST_ID.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        if request.url.path.startswith("/api/"):
            response.headers["X-VerbaNode-Version"] = APP_VERSION
            response.headers["X-VerbaNode-API-Version"] = str(API_VERSION)
            response.headers["X-VerbaNode-WebSocket-Protocol"] = str(PROTOCOL_VERSION)
            response.headers.setdefault("Cache-Control", "no-store")
        return response
    finally:
        _REQUEST_ID.reset(token)


def _error_payload(*, code: str, message: str, request_id: str, details: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        # ``detail`` stays for compatibility with the existing web client and
        # third-party clients written against the pre-v0.8.1 API.
        "detail": message,
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        },
    }
    if details is not None:
        payload["error"]["details"] = jsonable_encoder(details)
    return payload


def api_error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", current_request_id())
    payload = _error_payload(
        code=code,
        message=message,
        request_id=request_id,
    )
    if extra:
        payload.update(extra)
    return JSONResponse(payload, status_code=status_code)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", current_request_id())
    if isinstance(exc.detail, str):
        message = exc.detail
        details = None
    else:
        message = "Request failed"
        details = exc.detail
    return JSONResponse(
        _error_payload(
            code=f"http_{exc.status_code}",
            message=message,
            request_id=request_id,
            details=details,
        ),
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", current_request_id())
    return JSONResponse(
        _error_payload(
            code="validation_error",
            message="Request validation failed",
            request_id=request_id,
            details=exc.errors(),
        ),
        status_code=422,
    )


def install_http_hardening(app: FastAPI) -> None:
    install_request_id_logging()
    app.middleware("http")(request_context_middleware)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)


__all__ = [
    "api_error_response",
    "current_request_id",
    "install_http_hardening",
    "install_request_id_logging",
    "request_context_middleware",
]
