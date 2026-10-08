"""Store user configuration objects and immutable rendered revisions."""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20261008_0003"
down_revision: str | Sequence[str] | None = "20260910_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def audit_columns() -> list[sa.Column[datetime] | sa.Column[str]]:
    return [
        sa.Column("create_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("update_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("create_by", sa.String(64), nullable=False),
        sa.Column("update_by", sa.String(64), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "deployment_configs",
        sa.Column("config_id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("local_users.user_id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(63), nullable=False),
        sa.Column("software_kind", sa.String(32), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        *audit_columns(),
    )
    op.create_index("ix_deployment_configs_owner", "deployment_configs", ["user_id", "status"])
    op.create_table(
        "configuration_revisions",
        sa.Column("revision_id", sa.String(36), primary_key=True),
        sa.Column(
            "config_id",
            sa.String(36),
            sa.ForeignKey("deployment_configs.config_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("local_users.user_id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("template_id", sa.String(128), nullable=False),
        sa.Column("template_commit", sa.String(64), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("rendered_manifest", sa.Text(), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        *audit_columns(),
        sa.UniqueConstraint("config_id", "revision", name="uq_configuration_revisions_config_revision"),
        sa.UniqueConstraint("user_id", "request_id", name="uq_configuration_revisions_user_request"),
    )
    op.create_index("ix_configuration_revisions_config", "configuration_revisions", ["config_id", "revision"])


def downgrade() -> None:
    op.drop_table("configuration_revisions")
    op.drop_table("deployment_configs")
