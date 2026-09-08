"""Typed API envelopes shared by routes and exception handlers."""

from collections.abc import Mapping
from http import HTTPStatus

from pydantic import BaseModel
from starlette.responses import JSONResponse


class ApiResponse[T](BaseModel):
    code: int = 0
    msg: str = ""
    data: T


def success[T](data: T) -> ApiResponse[T]:
    return ApiResponse(data=data)


def fail(*, code: int, msg: str) -> ApiResponse[None]:
    if code != -1 and code < 10000:
        raise ValueError("Business failure codes must be -1 or >= 10000")
    return ApiResponse(code=code, msg=msg, data=None)


def error(*, msg: str) -> ApiResponse[None]:
    return fail(code=-1, msg=msg)


def http_error(*, status_code: int, headers: Mapping[str, str] | None = None) -> JSONResponse:
    payload = ApiResponse[None](code=status_code, msg=HTTPStatus(status_code).phrase, data=None)
    return JSONResponse(
        status_code=status_code, content=payload.model_dump(mode="json"), headers=headers
    )
