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
_DEFAULT_MAX_JSON_BODY_BYTES = 2 * 1024 * 1024
LOGGER = logging.getLogger(__name__)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(self)",
    "Content-Security-Policy": (
        "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; "
        "form-action 'self'; img-src 'self' data: blob:; font-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self'; "
        "connect-src 'self' ws: wss:; media-src 'self' blob:; worker-src 'self' blob:"
    ),
}


def current_request_id() -> str:
    return _REQUEST_ID.get()


def _resolve_request_id(request: Request) -> str:
    supplied = (request.headers.get("X-Request-ID") or "").strip()
    if supplied and _REQUEST_ID_RE.fullmatch(supplied):
        return supplied
    return uuid.uuid4().hex


def _apply_standard_headers(response: Response, request: Request, request_id: str) -> Response:
    response.headers["X-Request-ID"] = request_id
    for name, value in _SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.url.path.startswith("/api/"):
        response.headers["X-VerbaNode-Version"] = APP_VERSION
        response.headers["X-VerbaNode-API-Version"] = str(API_VERSION)
        response.headers["X-VerbaNode-WebSocket-Protocol"] = str(PROTOCOL_VERSION)
        response.headers.setdefault("Cache-Control", "no-store")
    return response


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
        response: Response
        max_json_body_bytes = int(
            getattr(
                request.app.state,
                "verbanode_max_json_body_bytes",
                _DEFAULT_MAX_JSON_BODY_BYTES,
            )
        )
        content_type = (request.headers.get("content-type") or "").lower()
        content_length = request.headers.get("content-length")
        too_large = False
        if content_type.startswith("application/json") and content_length:
            try:
                too_large = int(content_length) > max_json_body_bytes
            except ValueError:
                too_large = False

        if too_large:
            response = JSONResponse(
                _error_payload(
                    code="request_too_large",
                    message="JSON request body is too large",
                    request_id=request_id,
                    details={"max_bytes": max_json_body_bytes},
                ),
                status_code=413,
            )
        else:
            response = await call_next(request)

        return _apply_standard_headers(response, request, request_id)
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


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a stable 500 envelope while keeping the real exception in logs."""
    request_id = getattr(request.state, "request_id", None) or _resolve_request_id(request)
    log_token = _REQUEST_ID.set(request_id)
    try:
        LOGGER.error(
            "Unhandled HTTP request failure",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
    finally:
        _REQUEST_ID.reset(log_token)
    response = JSONResponse(
        _error_payload(
            code="internal_server_error",
            message="Internal server error",
            request_id=request_id,
        ),
        status_code=500,
    )
    return _apply_standard_headers(response, request, request_id)


def install_http_hardening(
    app: FastAPI,
    *,
    max_json_body_bytes: int = _DEFAULT_MAX_JSON_BODY_BYTES,
) -> None:
    app.state.verbanode_max_json_body_bytes = max(65536, int(max_json_body_bytes))
    install_request_id_logging()
    app.middleware("http")(request_context_middleware)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)


__all__ = [
    "api_error_response",
    "current_request_id",
    "install_http_hardening",
    "install_request_id_logging",
    "request_context_middleware",
    "unhandled_exception_handler",
]
