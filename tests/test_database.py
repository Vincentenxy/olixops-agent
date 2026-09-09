"""Explicit migrations and PostgreSQL integration against an opt-in isolated database."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import delete, select

from app.cli import create_user, init_keys
from app.core.config import Settings
from app.core.database import Database
from app.core.event_loop import run_async
from app.core.security import Security
from app.models.auth import LocalUser
from app.services.auth import AuthService


def test_migrations_upgrade_and_downgrade(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'migrations.db'}"
    monkeypatch.setenv("OLIXOPS_DATABASE_URL", url)
    config = Config("alembic.ini")

    async def ready() -> bool:
        database = Database(Settings())
        try:
            return await database.check()
        finally:
            await database.close()

    assert not asyncio.run(ready())
    command.upgrade(config, "head")
    assert asyncio.run(ready())
    command.check(config)
    command.downgrade(config, "base")
    assert not asyncio.run(ready())


@pytest.mark.skipif(
    not os.environ.get("OLIXOPS_TEST_DATABASE_URL"), reason="Isolated PostgreSQL URL not configured"
)
def test_postgres_session_rotation_and_migrations(tmp_path: Path) -> None:
    settings = Settings(
        database_url=SecretStr(os.environ["OLIXOPS_TEST_DATABASE_URL"]),
        jwt_private_key_path=tmp_path / "private.pem",
        jwt_public_key_path=tmp_path / "public.pem",
    )
    init_keys(settings)
    assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")
    username = f"integration-{uuid4().hex}"

    async def exercise() -> None:
        database = Database(settings)
        security = Security(settings)
        security.load()
        try:
            assert await database.check(), "Run alembic upgrade head on the isolated test database"
            assert await create_user(
                settings, username, "Integration", "integration-password-42", admin=False
            )
            async with database.sessions() as session:
                _, refresh = await AuthService(session, security).login(
                    username, "integration-password-42", username
                )

            async def rotate() -> int:
                from starlette.exceptions import HTTPException

                async with database.sessions() as session:
                    try:
                        await AuthService(session, security).refresh(refresh)
                        return 200
                    except HTTPException as exc:
                        return exc.status_code

            assert sorted(await asyncio.gather(rotate(), rotate())) == [200, 401]
        finally:
            async with database.sessions() as session, session.begin():
                user = await session.scalar(select(LocalUser).where(LocalUser.username == username))
                if user:
                    await session.execute(
                        delete(LocalUser).where(LocalUser.user_id == user.user_id)
                    )
            await database.close()

    run_async(exercise())
