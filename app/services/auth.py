"""Local login and atomic refresh rotation with database-backed revocation."""

import asyncio
import logging
import secrets
from datetime import timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException

from app.core.security import (
    Security,
    dummy_password_hash,
    password_hasher,
    token_hash,
    verify_password,
)
from app.models.auth import AuthSession, LocalUser, as_utc, utcnow
from app.repositories.auth import AuthRepository
from app.schemas.auth import CurrentUser, TokenData, UserInfo

logger = logging.getLogger(__name__)


def unauthorized() -> HTTPException:
    return HTTPException(401, headers={"WWW-Authenticate": "Bearer"})


def user_info(user: LocalUser) -> UserInfo:
    return UserInfo(
        user_id=user.user_id, username=user.username, name=user.name, is_admin=user.is_admin
    )


class AuthService:
    def __init__(self, session: AsyncSession, security: Security) -> None:
        self.session = session
        self.security = security
        self.settings = security.settings
        self.repository = AuthRepository(session)

    def token_data(self, user: LocalUser, session_id: str) -> TokenData:
        info = user_info(user)
        return TokenData(
            access_token=self.security.issue(info, session_id),
            expires_in=self.settings.access_token_seconds,
            user=info,
        )

    async def login(self, username: str, password: str, client_ip: str) -> tuple[TokenData, str]:
        username = username.lower()
        now = utcnow()
        rejected = False
        result: tuple[TokenData, str] | None = None
        async with self.session.begin():
            guards = [
                await self.repository.throttle(key)
                for key in sorted(
                    {
                        token_hash(f"user:{username}"),
                        token_hash(f"ip:{client_ip}"),
                    }
                )
            ]
            if any(g.locked_until and as_utc(g.locked_until) > now for g in guards):
                rejected = True
            else:
                user = await self.repository.user_by_name(username, lock=True)
                encoded = user.password_hash if user else dummy_password_hash()
                valid = await asyncio.to_thread(verify_password, encoded, password)
                if user is None or not valid or not user.is_active:
                    for guard in guards:
                        guard.failed_count += 1
                        if guard.failed_count >= self.settings.login_failure_limit:
                            backoff = min(
                                600,
                                self.settings.login_lock_seconds
                                * (
                                    2
                                    ** min(
                                        5, guard.failed_count - self.settings.login_failure_limit
                                    )
                                ),
                            )
                            guard.locked_until = now + timedelta(seconds=backoff)
                    rejected = True
                else:
                    for guard in guards:
                        guard.failed_count, guard.locked_until = 0, None
                    refresh = secrets.token_urlsafe(48)
                    session_id = str(uuid4())
                    self.session.add(
                        AuthSession(
                            session_id=session_id,
                            user_id=user.user_id,
                            refresh_hash=token_hash(refresh),
                            expires_at=now + timedelta(seconds=self.settings.refresh_token_seconds),
                            create_by=user.user_id,
                            update_by=user.user_id,
                        )
                    )
                    if password_hasher.check_needs_rehash(user.password_hash):
                        user.password_hash = await asyncio.to_thread(password_hasher.hash, password)
                        user.update_by = user.user_id
                    result = self.token_data(user, session_id), refresh
        if rejected or result is None:
            logger.warning("local login rejected")
            raise unauthorized()
        logger.info("local login succeeded", extra={"user_id": result[0].user.user_id})
        return result

    async def refresh(self, refresh: str) -> tuple[TokenData, str]:
        async with self.session.begin():
            old_hash = token_hash(refresh)
            stored = await self.repository.session_by_hash(old_hash)
            if stored is None:
                raise unauthorized()
            # Serialize password changes, login, logout and refresh for this user.
            user = await self.repository.user_by_id(stored.user_id, lock=True)
            if user is None or not user.is_active:
                raise unauthorized()
            replacement = secrets.token_urlsafe(48)
            if not await self.repository.rotate(
                stored.session_id, old_hash, token_hash(replacement), user.user_id
            ):
                raise unauthorized()
            result = self.token_data(user, stored.session_id)
        return result, replacement

    async def logout(self, refresh: str | None, identity: tuple[str, str] | None) -> None:
        async with self.session.begin():
            target = identity
            if target is None and refresh:
                stored = await self.repository.session_by_hash(token_hash(refresh))
                if stored is not None:
                    target = stored.user_id, stored.session_id
            if target is not None:
                # Another tab may have replaced the shared cookie with a different session.
                user_id, session_id = target
                await self.repository.user_by_id(user_id, lock=True)
                await self.repository.revoke_session(session_id, user_id)

    async def current(self, identity: tuple[str, str], token: str, cookie: str) -> CurrentUser:
        user_id, session_id = identity
        user = await self.repository.user_by_id(user_id)
        stored = await self.repository.active_session(session_id, user_id)
        if user is None or not user.is_active or stored is None:
            raise unauthorized()
        return CurrentUser(
            **user_info(user).model_dump(), session_id=session_id, jwt=token, cookie=cookie
        )

    async def change_password(self, current: CurrentUser, old: str, new: str) -> None:
        # Authentication used its own read session; this transaction rechecks under user lock.
        async with self.session.begin():
            user = await self.repository.user_by_id(current.user_id, lock=True)
            active = await self.repository.active_session(current.session_id, current.user_id)
            if user is None or not user.is_active or active is None:
                raise unauthorized()
            if old == new or not await asyncio.to_thread(verify_password, user.password_hash, old):
                raise HTTPException(400)
            user.password_hash = await asyncio.to_thread(password_hasher.hash, new)
            user.update_by = user.user_id
            await self.repository.revoke_user_sessions(user.user_id, utcnow())
        logger.info("local password changed; sessions revoked", extra={"user_id": current.user_id})
