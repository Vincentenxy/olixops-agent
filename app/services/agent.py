"""Authorized, idempotent task submission and durable conversation snapshots."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException

from app.core.context import trace_id
from app.models.agent import AgentTask, AgentTurn
from app.models.auth import as_utc, utcnow
from app.repositories.agent import AgentRepository
from app.schemas.agent import (
    CreateTaskInput,
    MessageInput,
    RetryInput,
    TaskDetail,
    TaskList,
    TaskSummary,
)


@dataclass
class AgentBusinessError(Exception):
    code: int
    msg: str


def summary(task: AgentTask) -> TaskSummary:
    return TaskSummary.model_validate(
        {
            "task_id": task.task_id,
            "title": task.title,
            "status": task.status,
            "revision": task.revision,
            "create_at": as_utc(task.create_at),
            "update_at": as_utc(task.update_at),
        }
    )


def detail(task: AgentTask) -> TaskDetail:
    return TaskDetail.model_validate(
        {
            **summary(task).model_dump(),
            "messages": task.messages,
            "spec": task.spec,
            "questions": task.questions,
            "error": task.error,
        }
    )


class AgentService:
    def __init__(self, session: AsyncSession, *, configured: bool) -> None:
        self.session = session
        self.repository = AgentRepository(session)
        self.configured = configured

    def require_configured(self) -> None:
        if not self.configured:
            raise AgentBusinessError(11001, "尚未配置 Agent 模型，请先完成服务端模型配置")

    async def owned_task(self, task_id: str, user_id: str, *, lock: bool = False) -> AgentTask:
        task = await self.repository.task(task_id, lock=lock)
        if task is None:
            raise HTTPException(404)
        if task.user_id != user_id:
            raise HTTPException(403)
        return task

    async def lock_owner(self, user_id: str) -> None:
        # Serialize capacity checks across API instances before locking individual tasks.
        user = await self.repository.lock_user(user_id)
        if user is None or not user.is_active:
            raise HTTPException(403)

    async def require_capacity(self, user_id: str) -> None:
        if await self.repository.queued_count(user_id) >= 5:
            raise AgentBusinessError(11004, "最多同时分析 5 个任务，请等待已有任务完成")

    async def list(self, user_id: str) -> TaskList:
        async with self.session.begin():
            tasks = await self.repository.list_tasks(user_id)
            return TaskList(items=[summary(task) for task in tasks])

    async def get(self, user_id: str, task_id: str) -> TaskDetail:
        async with self.session.begin():
            return detail(await self.owned_task(task_id, user_id))

    async def create(self, user_id: str, payload: CreateTaskInput) -> TaskDetail:
        request_id = str(payload.request_id)
        async with self.session.begin():
            await self.lock_owner(user_id)
            existing = await self.repository.task(request_id)
            previous = await self.repository.turn(request_id)
            if existing is not None:
                if existing.user_id != user_id:
                    raise HTTPException(403)
                if previous is None or previous.message != payload.message:
                    raise AgentBusinessError(11005, "请求标识已用于不同的内容，请重新提交")
                return detail(existing)
            if previous is not None:
                raise AgentBusinessError(11005, "请求标识已用于其他任务，请重新提交")
            self.require_configured()
            await self.require_capacity(user_id)
            task = AgentTask(
                task_id=request_id,
                user_id=user_id,
                title=payload.message[:100],
                status="queued",
                revision=1,
                messages=[{"role": "user", "content": payload.message}],
                spec=None,
                questions=[],
                error=None,
                create_by=user_id,
                update_by=user_id,
            )
            self.session.add(task)
            # Insert the parent first; no ORM relationship is needed for queue access.
            await self.session.flush()
            self.add_turn(task, request_id, payload.message, user_id)
            await self.session.flush()
            return detail(task)

    def add_turn(self, task: AgentTask, request_id: str, message: str, user_id: str) -> None:
        self.session.add(
            AgentTurn(
                turn_id=request_id,
                task_id=task.task_id,
                revision=task.revision,
                message=message,
                status="queued",
                trace_id=trace_id.get(),
                create_by=user_id,
                update_by=user_id,
            )
        )

    async def message(self, user_id: str, payload: MessageInput) -> TaskDetail:
        async with self.session.begin():
            await self.lock_owner(user_id)
            task = await self.owned_task(str(payload.task_id), user_id, lock=True)
            previous = await self.repository.turn(str(payload.request_id))
            if previous is not None:
                if previous.task_id != task.task_id or previous.message != payload.message:
                    raise AgentBusinessError(11005, "请求标识已用于不同的内容，请重新提交")
                return detail(task)
            self.require_configured()
            if task.status == "queued":
                raise AgentBusinessError(11002, "任务正在分析，请等待本轮完成")
            if task.revision != payload.expected_revision:
                raise AgentBusinessError(11003, "任务已更新，请刷新后重试")
            if task.status == "failed":
                raise AgentBusinessError(11003, "请先重试失败的分析，再补充新的需求")
            if task.revision >= 20:
                raise AgentBusinessError(11004, "每个任务最多补充 20 轮需求，请创建新任务")
            await self.require_capacity(user_id)
            task.revision += 1
            task.status = "queued"
            task.messages = [*task.messages, {"role": "user", "content": payload.message}]
            task.spec = None
            task.questions = []
            task.error = None
            task.update_by = user_id
            task.update_at = utcnow()
            self.add_turn(task, str(payload.request_id), payload.message, user_id)
            await self.session.flush()
            return detail(task)

    async def retry(self, user_id: str, payload: RetryInput) -> TaskDetail:
        async with self.session.begin():
            await self.lock_owner(user_id)
            task = await self.owned_task(str(payload.task_id), user_id, lock=True)
            self.require_configured()
            if task.status == "queued":
                raise AgentBusinessError(11002, "任务正在分析，请等待本轮完成")
            if task.revision != payload.expected_revision:
                raise AgentBusinessError(11003, "任务已更新，请刷新后重试")
            if task.status != "failed":
                raise AgentBusinessError(11003, "当前任务没有失败的分析需要重试")
            await self.require_capacity(user_id)
            turn = await self.repository.latest_turn(task.task_id)
            if turn is None or turn.status != "failed" or turn.revision != task.revision:
                raise RuntimeError("Agent task and queue revision disagree")
            turn.status = "queued"
            turn.trace_id = trace_id.get()
            turn.update_by = user_id
            task.status = "queued"
            task.error = None
            task.update_by = user_id
            task.update_at = utcnow()
            await self.session.flush()
            return detail(task)
