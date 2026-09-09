"""Async database lifecycle. Schema changes are exclusively Alembic migrations."""

import asyncio
import math

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.timeout = settings.database_timeout_seconds
        url = settings.database_url.get_secret_value()
        self.engine = create_async_engine(
            url,
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"connect_timeout": math.ceil(self.timeout)}
            if url.startswith("postgresql+")
            else {},
        )
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def check(self) -> bool:
        """Verify both connectivity and the expected migrated authentication tables."""
        try:
            async with asyncio.timeout(self.timeout), self.engine.connect() as connection:
                await connection.execute(text("SELECT user_id FROM local_users LIMIT 0"))
                await connection.execute(text("SELECT session_id FROM auth_sessions LIMIT 0"))
                await connection.execute(text("SELECT throttle_key FROM login_throttles LIMIT 0"))
            return True
        except SQLAlchemyError, TimeoutError, OSError:
            return False

    async def close(self) -> None:
        await self.engine.dispose()
