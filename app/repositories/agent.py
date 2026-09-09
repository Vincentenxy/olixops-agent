"""Agent task ownership, idempotency records and transactional queue queries."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentTask, AgentTurn
from app.models.auth import LocalUser


class AgentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def lock_user(self, user_id: str) -> LocalUser | None:
        return (
            await self.session.scalars(
                select(LocalUser).where(LocalUser.user_id == user_id).with_for_update()
            )
        ).one_or_none()

    async def task(self, task_id: str, *, lock: bool = False) -> AgentTask | None:
        query = select(AgentTask).where(AgentTask.task_id == task_id)
        if lock:
            query = query.with_for_update()
        return (await self.session.scalars(query)).one_or_none()

    async def turn(self, turn_id: str) -> AgentTurn | None:
        return (
            await self.session.scalars(select(AgentTurn).where(AgentTurn.turn_id == turn_id))
        ).one_or_none()

    async def latest_turn(self, task_id: str) -> AgentTurn | None:
        return (
            await self.session.scalars(
                select(AgentTurn)
                .where(AgentTurn.task_id == task_id)
                .order_by(AgentTurn.revision.desc())
                .limit(1)
            )
        ).one_or_none()

    async def list_tasks(self, user_id: str) -> list[AgentTask]:
        return list(
            await self.session.scalars(
                select(AgentTask)
                .where(AgentTask.user_id == user_id)
                .order_by(AgentTask.update_at.desc(), AgentTask.task_id)
                .limit(50)
            )
        )

    async def queued_count(self, user_id: str) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(AgentTask)
                .where(AgentTask.user_id == user_id, AgentTask.status == "queued")
            )
        ) or 0

    async def claim_turn(self) -> AgentTurn | None:
        # The caller retains this transaction until the graph result is committed.
        # A terminated process releases the lock and leaves the committed queue intact.
        return (
            await self.session.scalars(
                select(AgentTurn)
                .where(AgentTurn.status == "queued")
                .order_by(AgentTurn.create_at, AgentTurn.turn_id)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
        ).one_or_none()
