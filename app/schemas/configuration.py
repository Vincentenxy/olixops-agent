"""Configuration management contracts for the first Redis fixture slice."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[
    str,
    StringConstraints(min_length=1, max_length=63, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RedisParameters(StrictModel):
    name: Name
    namespace: Name
    image: Annotated[str, StringConstraints(min_length=1, max_length=256)] = "redis:7.2-alpine"
    replicas: Annotated[int, Field(strict=True)] = 1
    port: Annotated[int, Field(strict=True, ge=1, le=65535)] = 6379


class TemplateSummary(StrictModel):
    template_id: str
    software_kind: str
    version: str
    commit_sha: str


class ConfigurationSaveInput(StrictModel):
    request_id: UUID
    config_id: UUID | None = None
    expected_revision: int = Field(default=0, ge=0, le=10000, strict=True)
    name: Name
    template_id: str = "redis/standalone/v1"
    parameters: RedisParameters


class ConfigurationSummary(StrictModel):
    config_id: str
    name: str
    software_kind: str
    current_revision: int
    status: str
    update_at: datetime


class ConfigurationDetail(ConfigurationSummary):
    revision_id: str
    template_id: str
    template_commit: str
    parameters: RedisParameters
    rendered_manifest: str


class ConfigurationList(StrictModel):
    items: list[ConfigurationSummary]


class ConfigurationHistory(StrictModel):
    items: list[ConfigurationDetail]
