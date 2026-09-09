"""Queries for identities, sessions and durable throttling."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import AuthSession, LocalUser, LoginThrottle, utcnow


class AuthRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def user_by_name(self, username: str, *, lock: bool = False) -> LocalUser | None:
        query = select(LocalUser).where(LocalUser.username == username)
        if lock:
            query = query.with_for_update()
        return (await self.session.scalars(query)).one_or_none()

    async def user_by_id(self, user_id: str, *, lock: bool = False) -> LocalUser | None:
        query = select(LocalUser).where(LocalUser.user_id == user_id)
        if lock:
            query = query.with_for_update()
        return (await self.session.scalars(query)).one_or_none()

    async def throttle(self, key: str) -> LoginThrottle:
        insert = (
            pg_insert
            if self.session.bind and self.session.bind.dialect.name == "postgresql"
            else sqlite_insert
        )
        await self.session.execute(
            insert(LoginThrottle)
            .values(throttle_key=key, failed_count=0)
            .on_conflict_do_nothing(index_elements=["throttle_key"])
        )
        result = await self.session.scalar(
            select(LoginThrottle).where(LoginThrottle.throttle_key == key).with_for_update()
        )
        assert result is not None
        return result

    async def session_by_hash(self, hashed: str) -> AuthSession | None:
        return (
            await self.session.scalars(
                select(AuthSession).where(AuthSession.refresh_hash == hashed)
            )
        ).one_or_none()

    async def active_session(self, session_id: str, user_id: str) -> AuthSession | None:
        return (
            await self.session.scalars(
                select(AuthSession).where(
                    AuthSession.session_id == session_id,
                    AuthSession.user_id == user_id,
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > utcnow(),
                )
            )
        ).one_or_none()

    async def rotate(self, session_id: str, old_hash: str, new_hash: str, user_id: str) -> bool:
        # Compare-and-swap remains safe even on dialects without row locks.
        result = await self.session.scalar(
            update(AuthSession)
            .where(
                AuthSession.session_id == session_id,
                AuthSession.refresh_hash == old_hash,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
            .values(refresh_hash=new_hash, update_by=user_id, update_at=utcnow())
            .execution_options(synchronize_session=False)
            .returning(AuthSession.session_id)
        )
        return result is not None

    async def revoke_session(self, session_id: str, user_id: str) -> None:
        await self.session.execute(
            update(AuthSession)
            .where(
                AuthSession.session_id == session_id,
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=utcnow(), update_by=user_id, update_at=utcnow())
        )

    async def revoke_user_sessions(self, user_id: str, now: datetime) -> None:
        await self.session.execute(
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=now, update_by=user_id, update_at=now)
        )
