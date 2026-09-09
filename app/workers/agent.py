"""Restartable agent queue consumer with PostgreSQL row-lock ownership."""

import asyncio
import logging
from typing import Protocol

from sqlalchemy.exc import SQLAlchemyError

from app.agents.model import AgentModelError
from app.core.context import trace_id
from app.core.database import Database
from app.models.auth import utcnow
from app.repositories.agent import AgentRepository
from app.schemas.agent import GraphResult

logger = logging.getLogger(__name__)
WORKER_ACTOR = "system:agent-worker"


class AgentTurnRunner(Protocol):
    @property
    def configured(self) -> bool: ...

    async def run_turn(self, task_id: str, turn_id: str, message: str) -> GraphResult: ...


async def process_next(database: Database, runtime: AgentTurnRunner) -> bool:
    """Consume one turn; process cancellation rolls back queue acknowledgement."""
    if not runtime.configured:
        return False
    async with database.sessions() as session, session.begin():
        repository = AgentRepository(session)
        turn = await repository.claim_turn()
        if turn is None:
            return False
        task = await repository.task(turn.task_id)
        if task is None or task.revision != turn.revision or task.status != "queued":
            raise RuntimeError("Agent task and queue revision disagree")
        trace_token = trace_id.set(turn.trace_id)
        try:
            logger.info("agent turn started", extra={"task_id": task.task_id, "step": "analyze"})
            try:
                result = await runtime.run_turn(task.task_id, turn.turn_id, turn.message)
            except AgentModelError as exc:
                task.status = "failed"
                task.error = str(exc)
                turn.status = "failed"
                logger.warning(
                    "agent model failed", extra={"task_id": task.task_id, "step": "analyze"}
                )
            except Exception:
                # The configured formatter records exception type/positions, never its text.
                logger.exception(
                    "agent turn failed", extra={"task_id": task.task_id, "step": "analyze"}
                )
                task.status = "failed"
                task.error = "分析未完成，请稍后重试；重复失败时联系管理员"
                turn.status = "failed"
            else:
                task.status = result.status
                task.messages = [message.model_dump(mode="json") for message in result.messages]
                task.spec = result.spec.model_dump(mode="json") if result.spec else None
                task.questions = result.questions
                task.error = None
                turn.status = "done"
            now = utcnow()
            task.update_at = now
            turn.update_at = now
            task.update_by = WORKER_ACTOR
            turn.update_by = WORKER_ACTOR
            await session.flush()
            logger.info("agent turn finished", extra={"task_id": task.task_id, "step": task.status})
        finally:
            trace_id.reset(trace_token)
    return True


async def run_worker(database: Database, runtime: AgentTurnRunner, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            processed = await process_next(database, runtime)
        except SQLAlchemyError, OSError:
            # Connection/commit failure keeps the queued turn available for another attempt.
            logger.exception("agent queue unavailable")
            processed = False
        if processed:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=0.5)
        except TimeoutError:
            pass
