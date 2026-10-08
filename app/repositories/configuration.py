"""Queries for user-owned deployment configurations."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth import LocalUser
from app.models.configuration import ConfigurationRevision, DeploymentConfig


class ConfigurationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_user(self, user_id: str) -> LocalUser | None:
        return (
            await self.session.scalars(
                select(LocalUser).where(LocalUser.user_id == user_id).with_for_update()
            )
        ).one_or_none()

    async def config(
        self, config_id: str, user_id: str, *, lock: bool = False
    ) -> DeploymentConfig | None:
        query = select(DeploymentConfig).where(
            DeploymentConfig.config_id == config_id, DeploymentConfig.user_id == user_id
        )
        if lock:
            query = query.with_for_update()
        return (await self.session.scalars(query)).one_or_none()

    async def list_configs(self, user_id: str) -> list[DeploymentConfig]:
        return list(
            await self.session.scalars(
                select(DeploymentConfig)
                .where(DeploymentConfig.user_id == user_id)
                .order_by(DeploymentConfig.update_at.desc(), DeploymentConfig.config_id)
            )
        )

    async def revision(self, revision_id: str, user_id: str) -> ConfigurationRevision | None:
        return (
            await self.session.scalars(
                select(ConfigurationRevision).where(
                    ConfigurationRevision.revision_id == revision_id,
                    ConfigurationRevision.user_id == user_id,
                )
            )
        ).one_or_none()

    async def revisions(self, config_id: str, user_id: str) -> list[ConfigurationRevision]:
        return list(
            await self.session.scalars(
                select(ConfigurationRevision)
                .where(
                    ConfigurationRevision.config_id == config_id,
                    ConfigurationRevision.user_id == user_id,
                )
                .order_by(ConfigurationRevision.revision.desc())
            )
        )

    async def request_revision(self, request_id: str, user_id: str) -> ConfigurationRevision | None:
        return (
            await self.session.scalars(
                select(ConfigurationRevision).where(
                    ConfigurationRevision.request_id == request_id,
                    ConfigurationRevision.user_id == user_id,
                )
            )
        ).one_or_none()
