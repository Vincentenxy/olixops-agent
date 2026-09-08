"""Normalize framework and unexpected failures without exposing exception details."""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from app.core.response import http_error

logger = logging.getLogger(__name__)


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    return http_error(status_code=exc.status_code, headers=exc.headers)


async def handle_validation_exception(request: Request, exc: Exception) -> JSONResponse:
    return http_error(status_code=422)


async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
    # ServerErrorMiddleware handles this after request middleware unwinds its context.
    request_id = getattr(request.state, "trace_id", None)
    logger.error(
        "unhandled request error",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"trace_id": request_id},
    )
    headers = {"X-Request-Id": request_id} if request_id else None
    return http_error(status_code=500, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_exception)
    app.add_exception_handler(Exception, handle_unexpected_exception)
