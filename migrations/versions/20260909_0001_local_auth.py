"""Local users, revocable authentication sessions and persistent login throttles."""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260909_0001"
down_revision: str | Sequence[str] | None = None
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
        "local_users",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(512), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *audit_columns(),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("local_users.user_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refresh_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *audit_columns(),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "login_throttles",
        sa.Column("throttle_key", sa.String(64), primary_key=True),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        *audit_columns(),
    )


def downgrade() -> None:
    op.drop_table("login_throttles")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("local_users")
