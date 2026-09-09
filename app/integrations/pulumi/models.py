"""The platform's deliberately small, credential-free Pulumi result contract."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EXPECTED_VERSION = "3.261.0"


class PulumiRuntimeStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sdk_version: str | None
    cli_version: str | None
    status: Literal["ready", "unavailable", "incompatible"]
    message: str


class Operation(StrEnum):
    PREVIEW = "preview"
    UP = "up"
    REFRESH = "refresh"
    DESTROY = "destroy"


class Change(StrEnum):
    SAME = "same"
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    REPLACE = "replace"
    CREATE_REPLACEMENT = "create-replacement"
    DELETE_REPLACED = "delete-replaced"
    READ = "read"
    READ_REPLACEMENT = "read-replacement"
    REFRESH = "refresh"
    DISCARD = "discard"
    DISCARD_REPLACED = "discard-replaced"
    REMOVE_PENDING_REPLACE = "remove-pending-replace"
    IMPORT = "import"
    IMPORT_REPLACEMENT = "import-replacement"


class Severity(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    INFO_ERROR = "info#err"
    WARNING = "warning"
    ERROR = "error"


class EngineEventSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int = Field(ge=0)
    operation: Operation
    kind: Literal["summary", "resource", "diagnostic", "stream_end"]
    change: Change | None = None
    severity: Severity | None = None
    changes: dict[Change, int] = Field(default_factory=dict)


class OutputSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    secret: bool
    # Values are never part of the platform result, even for unmarked outputs.
    value: Literal["[REDACTED]"] = "[REDACTED]"


class OperationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Operation
    status: Literal["succeeded"] = "succeeded"
    changes: dict[Change, int] = Field(default_factory=dict)
    outputs: list[OutputSummary] = Field(default_factory=list)


class SelfTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["succeeded", "failed", "timed_out", "interrupted", "unavailable"]
    message: str
    runtime: PulumiRuntimeStatus
    operations: list[OperationSummary] = Field(default_factory=list)
    events: list[EngineEventSummary] = Field(default_factory=list)
    events_truncated: bool = False
    outputs_verified: bool = False
    no_changes_verified: bool = False
    stack_removed: bool = False
    # Interruption/timeout is explicitly not reported as engine rollback.
    cleanup: Literal["temporary_files_removed", "not_started"] = "not_started"
