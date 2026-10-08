"""Configuration save/read use cases backed by the local GitLab fixture."""

from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.integrations.gitlab.templates import LocalFixtureTemplateProvider, render_redis
from app.models.auth import as_utc, utcnow
from app.models.configuration import ConfigurationRevision, DeploymentConfig
from app.repositories.configuration import ConfigurationRepository
from app.schemas.configuration import (
    ConfigurationDetail,
    ConfigurationHistory,
    ConfigurationList,
    ConfigurationSaveInput,
    ConfigurationSummary,
    RedisParameters,
    TemplateSummary,
)


def summary(config: DeploymentConfig) -> ConfigurationSummary:
    return ConfigurationSummary(
        config_id=config.config_id,
        name=config.name,
        software_kind=config.software_kind,
        current_revision=config.current_revision,
        status=config.status,
        update_at=as_utc(config.update_at),
    )


def detail(revision: ConfigurationRevision, config: DeploymentConfig) -> ConfigurationDetail:
    return ConfigurationDetail(
        **summary(config).model_dump(),
        revision_id=revision.revision_id,
        template_id=revision.template_id,
        template_commit=revision.template_commit,
        parameters=RedisParameters.model_validate(revision.parameters),
        rendered_manifest=revision.rendered_manifest,
    )


class ConfigurationService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.repository = ConfigurationRepository(session)
        self.provider = LocalFixtureTemplateProvider(Path(settings.template_fixture_root))

    def templates(self) -> list[TemplateSummary]:
        return [
            TemplateSummary(
                template_id=item.template_id,
                software_kind=item.software_kind,
                version=item.version,
                commit_sha=item.commit_sha,
            )
            for item in self.provider.list_templates()
        ]

    async def list(self, user_id: str) -> ConfigurationList:
        async with self.session.begin():
            return ConfigurationList(
                items=[summary(item) for item in await self.repository.list_configs(user_id)]
            )

    async def get(self, user_id: str, config_id: str) -> ConfigurationDetail:
        async with self.session.begin():
            config = await self.repository.config(config_id, user_id)
            if config is None or config.current_revision == 0:
                raise HTTPException(404)
            revisions = await self.repository.revisions(config_id, user_id)
            if not revisions:
                raise HTTPException(404)
            return detail(revisions[0], config)

    async def history(self, user_id: str, config_id: str) -> ConfigurationHistory:
        async with self.session.begin():
            if await self.repository.config(config_id, user_id) is None:
                raise HTTPException(404)
            revisions = await self.repository.revisions(config_id, user_id)
            config = await self.repository.config(config_id, user_id)
            assert config is not None
            return ConfigurationHistory(items=[detail(item, config) for item in revisions])

    async def save(self, user_id: str, payload: ConfigurationSaveInput) -> ConfigurationDetail:
        package = self.provider.get_template(payload.template_id)
        if package.software_kind != "redis":
            raise HTTPException(422)
        parameters = payload.parameters.model_dump()
        manifest = render_redis(package, parameters)
        request_id = str(payload.request_id)
        async with self.session.begin():
            owner = await self.repository.lock_user(user_id)
            if owner is None or not owner.is_active:
                raise HTTPException(403)
            existing_request = await self.repository.request_revision(request_id, user_id)
            if existing_request is not None:
                config = await self.repository.config(existing_request.config_id, user_id)
                assert config is not None
                return detail(existing_request, config)
            config_id = str(payload.config_id) if payload.config_id else str(uuid4())
            config = await self.repository.config(config_id, user_id, lock=True)
            if config is None:
                if payload.expected_revision != 0:
                    raise HTTPException(409)
                config = DeploymentConfig(
                    config_id=config_id,
                    user_id=user_id,
                    name=payload.name,
                    software_kind="redis",
                    current_revision=0,
                    status="validated",
                    create_by=user_id,
                    update_by=user_id,
                )
                self.session.add(config)
                await self.session.flush()
            elif config.current_revision != payload.expected_revision:
                raise HTTPException(409)
            next_revision = config.current_revision + 1
            revision = ConfigurationRevision(
                revision_id=str(uuid4()),
                config_id=config.config_id,
                user_id=user_id,
                revision=next_revision,
                request_id=request_id,
                status="validated",
                template_id=package.template_id,
                template_commit=package.commit_sha,
                parameters=parameters,
                rendered_manifest=manifest,
                validation_errors=[],
                create_by=user_id,
                update_by=user_id,
            )
            config.name = payload.name
            config.current_revision = next_revision
            config.status = "validated"
            config.update_by = user_id
            config.update_at = utcnow()
            self.session.add(revision)
            await self.session.flush()
            return detail(revision, config)
