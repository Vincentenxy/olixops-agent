"""Versioned, data-only contracts for deployment planning and persisted conversations."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Name = Annotated[
    str,
    StringConstraints(min_length=1, max_length=63, pattern=r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$"),
]
Version = Annotated[
    str,
    StringConstraints(
        min_length=1, max_length=64, pattern=r"^\d+(?:\.\d+){0,2}(?:-[a-zA-Z0-9][a-zA-Z0-9_.-]*)?$"
    ),
]
MessageText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)
]
TaskStatus = Literal["queued", "needs_input", "ready", "failed"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=8000)


class ServiceSpec(StrictModel):
    kind: Literal["redis", "postgresql"]
    name: Name
    version: Version
    storage_gi: int = Field(ge=1, le=1024, strict=True)
    replicas: Literal[1] = 1


class DeploymentSpec(StrictModel):
    target: Literal["kubernetes"] = "kubernetes"
    cluster: Name
    namespace: Name
    services: list[ServiceSpec] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def unique_names(self) -> DeploymentSpec:
        if len({service.name for service in self.services}) != len(self.services):
            raise ValueError("Service names must be unique")
        return self


class DraftService(StrictModel):
    kind: Literal["redis", "postgresql"]
    name: Name | None
    version: Version | None
    storage_gi: Annotated[int, Field(ge=1, le=1024, strict=True)] | None


class DeploymentDraft(StrictModel):
    """Null means the user has not supplied a value; the model must not invent it."""

    cluster: Name | None
    namespace: Name | None
    services: list[DraftService] = Field(max_length=8)
    unsupported_reason: str | None = Field(max_length=500)


class GraphResult(StrictModel):
    messages: list[ChatMessage]
    spec: DeploymentSpec | None
    questions: list[str]
    status: Literal["needs_input", "ready"]


class CreateTaskInput(StrictModel):
    request_id: UUID
    message: MessageText


class TaskInput(StrictModel):
    task_id: UUID


class RetryInput(TaskInput):
    expected_revision: int = Field(ge=1, le=20, strict=True)


class MessageInput(RetryInput):
    request_id: UUID
    message: MessageText


class TaskSummary(StrictModel):
    task_id: str
    title: str
    status: TaskStatus
    revision: int
    create_at: datetime
    update_at: datetime


class TaskDetail(TaskSummary):
    messages: list[ChatMessage]
    spec: DeploymentSpec | None
    questions: list[str]
    error: str | None


class TaskList(StrictModel):
    items: list[TaskSummary]


class AgentStatus(StrictModel):
    configured: bool
    message: str
