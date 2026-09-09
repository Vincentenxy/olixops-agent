"""Request-scoped database access and fixed-algorithm bearer authentication."""

from collections.abc import AsyncIterator
from typing import Annotated, cast

import jwt
from fastapi import Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException

from app.core.database import Database
from app.core.security import Security
from app.schemas.auth import CurrentUser
from app.services.auth import AuthService, unauthorized


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def get_security(request: Request) -> Security:
    security = cast(Security, request.app.state.security)
    if not security.ready:
        raise HTTPException(503)
    return security


async def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    try:
        async with database.sessions() as session:
            yield session
    except SQLAlchemyError as exc:
        raise HTTPException(503) from exc


def get_auth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    security: Annotated[Security, Depends(get_security)],
) -> AuthService:
    return AuthService(session, security)


def bearer_token(request: Request) -> str:
    parts = request.headers.get("Authorization", "").split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or len(parts[1]) > 8192:
        raise unauthorized()
    return parts[1]


async def get_current_user(
    request: Request,
    database: Annotated[Database, Depends(get_database)],
    security: Annotated[Security, Depends(get_security)],
) -> CurrentUser:
    token = bearer_token(request)
    try:
        identity = security.decode(token)
    except jwt.InvalidTokenError as exc:
        raise unauthorized() from exc
    try:
        async with database.sessions() as session:
            user = await AuthService(session, security).current(
                identity, token, request.headers.get("Cookie", "")
            )
    except SQLAlchemyError as exc:
        raise HTTPException(503) from exc
    request.state.user_id = user.user_id
    return user


def require_browser_write(request: Request) -> None:
    """Non-simple header + exact Origin check; no cross-origin CORS is enabled."""
    settings = cast(Security, request.app.state.security).settings
    origin = request.headers.get("Origin")
    if request.headers.get("X-Olixops-Client") != "web" or (
        origin is not None and origin not in settings.browser_origins
    ):
        raise HTTPException(403)
    if (
        request.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(415)
