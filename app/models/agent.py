"""Durable agent requests; LangGraph owns its separate checkpoint tables."""

from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.auth import AuditFields, Base


class AgentTask(AuditFields, Base):
    __tablename__ = "agent_tasks"
    __table_args__ = (Index("ix_agent_tasks_owner_status", "user_id", "status"),)

    task_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("local_users.user_id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    spec: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentTurn(AuditFields, Base):
    __tablename__ = "agent_turns"
    __table_args__ = (
        UniqueConstraint("task_id", "revision", name="uq_agent_turns_task_revision"),
        Index("ix_agent_turns_queue", "status", "create_at"),
    )

    turn_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        ForeignKey("agent_tasks.task_id", ondelete="CASCADE"), index=True
    )
    revision: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    trace_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
