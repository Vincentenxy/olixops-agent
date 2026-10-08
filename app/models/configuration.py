"""User-owned configuration objects and immutable revisions."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.auth import AuditFields, Base


class DeploymentConfig(AuditFields, Base):
    __tablename__ = "deployment_configs"
    __table_args__ = (Index("ix_deployment_configs_owner", "user_id", "status"),)

    config_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("local_users.user_id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(63))
    software_kind: Mapped[str] = mapped_column(String(32))
    current_revision: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="draft")


class ConfigurationRevision(AuditFields, Base):
    __tablename__ = "configuration_revisions"
    __table_args__ = (
        UniqueConstraint(
            "config_id", "revision", name="uq_configuration_revisions_config_revision"
        ),
        UniqueConstraint("user_id", "request_id", name="uq_configuration_revisions_user_request"),
        Index("ix_configuration_revisions_config", "config_id", "revision"),
    )

    revision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    config_id: Mapped[str] = mapped_column(
        ForeignKey("deployment_configs.config_id", ondelete="CASCADE")
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("local_users.user_id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    request_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16), default="validated")
    template_id: Mapped[str] = mapped_column(String(128))
    template_commit: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON)
    rendered_manifest: Mapped[str] = mapped_column(Text)
    validation_errors: Mapped[list[str]] = mapped_column(JSON, default=list)
