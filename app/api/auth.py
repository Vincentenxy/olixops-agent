"""Public local authentication and authenticated account endpoints."""

from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, Request, Response
from starlette.exceptions import HTTPException

from app.api.dependencies import (
    bearer_token,
    get_auth_service,
    get_current_user,
    require_browser_write,
)
from app.core.response import ApiResponse, success
from app.schemas.auth import CurrentUser, EmptyInput, LoginInput, PasswordInput, TokenData, UserInfo
from app.services.auth import AuthService

COOKIE_NAME = "olixops_refresh"
COOKIE_PATH = "/api/v1/pub/auth"
public_router = APIRouter(
    prefix=COOKIE_PATH, tags=["authentication"], dependencies=[Depends(require_browser_write)]
)
router = APIRouter(prefix="/api/v1/auth", tags=["account"])
Auth = Annotated[AuthService, Depends(get_auth_service)]
Identity = Annotated[CurrentUser, Depends(get_current_user)]


def set_refresh_cookie(response: Response, token: str, service: AuthService) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=service.settings.refresh_token_seconds,
        httponly=True,
        secure=service.settings.refresh_cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )
    response.headers["Cache-Control"] = "no-store"


def clear_refresh_cookie(response: Response, service: AuthService) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path=COOKIE_PATH,
        httponly=True,
        secure=service.settings.refresh_cookie_secure,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"


@public_router.post("/login", response_model=ApiResponse[TokenData])
async def login(
    payload: LoginInput, request: Request, response: Response, service: Auth
) -> ApiResponse[TokenData]:
    token, refresh = await service.login(
        payload.username,
        payload.password.get_secret_value(),
        request.client.host if request.client else "unknown",
    )
    set_refresh_cookie(response, refresh, service)
    return success(token)


@public_router.post("/refresh", response_model=ApiResponse[TokenData])
async def refresh_session(
    payload: EmptyInput, request: Request, response: Response, service: Auth
) -> ApiResponse[TokenData]:
    token, refresh = await service.refresh(request.cookies.get(COOKIE_NAME, ""))
    set_refresh_cookie(response, refresh, service)
    return success(token)


@public_router.post("/logout", response_model=ApiResponse[None])
async def logout(
    payload: EmptyInput, request: Request, response: Response, service: Auth
) -> ApiResponse[None]:
    identity: tuple[str, str] | None = None
    if "Authorization" in request.headers:
        try:
            identity = service.security.decode(bearer_token(request))
        except jwt.InvalidTokenError, HTTPException:
            # Logout remains idempotent when an optional bearer is malformed or expired.
            pass
    await service.logout(request.cookies.get(COOKIE_NAME), identity)
    clear_refresh_cookie(response, service)
    return success(None)


@router.get("/me", response_model=ApiResponse[UserInfo])
async def me(current: Identity, response: Response) -> ApiResponse[UserInfo]:
    response.headers["Cache-Control"] = "no-store"
    return success(UserInfo(**current.model_dump()))


@router.post(
    "/password", response_model=ApiResponse[None], dependencies=[Depends(require_browser_write)]
)
async def change_password(
    payload: PasswordInput, current: Identity, response: Response, service: Auth
) -> ApiResponse[None]:
    await service.change_password(
        current,
        payload.current_password.get_secret_value(),
        payload.new_password.get_secret_value(),
    )
    clear_refresh_cookie(response, service)
    return success(None)
