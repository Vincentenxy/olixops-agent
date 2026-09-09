"""Persist agent task snapshots and restartable queued conversation turns."""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260910_0002"
down_revision: str | Sequence[str] | None = "20260909_0001"
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
        "agent_tasks",
        sa.Column("task_id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("local_users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("messages", sa.JSON(), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=True),
        sa.Column("questions", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        *audit_columns(),
    )
    op.create_index("ix_agent_tasks_owner_status", "agent_tasks", ["user_id", "status"])
    op.create_table(
        "agent_turns",
        sa.Column("turn_id", sa.String(36), primary_key=True),
        sa.Column(
            "task_id",
            sa.String(36),
            sa.ForeignKey("agent_tasks.task_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("trace_id", sa.String(128), nullable=True),
        *audit_columns(),
        sa.UniqueConstraint("task_id", "revision", name="uq_agent_turns_task_revision"),
    )
    op.create_index("ix_agent_turns_task_id", "agent_turns", ["task_id"])
    op.create_index("ix_agent_turns_queue", "agent_turns", ["status", "create_at"])


def downgrade() -> None:
    op.drop_table("agent_turns")
    op.drop_table("agent_tasks")
