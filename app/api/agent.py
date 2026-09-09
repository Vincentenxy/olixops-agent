"""Authenticated agent planning requests and durable task queries."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_session
from app.core.response import ApiResponse, fail, success
from app.schemas.agent import (
    AgentStatus,
    CreateTaskInput,
    MessageInput,
    RetryInput,
    TaskDetail,
    TaskInput,
    TaskList,
)
from app.schemas.auth import CurrentUser
from app.services.agent import AgentBusinessError, AgentService
from app.workers.agent import AgentTurnRunner

router = APIRouter(prefix="/api/v1/agent", tags=["agent"])
Identity = Annotated[CurrentUser, Depends(get_current_user)]


def get_agent_service(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> AgentService:
    runtime = cast(AgentTurnRunner, request.app.state.agent_runtime)
    return AgentService(session, configured=runtime.configured)


Agent = Annotated[AgentService, Depends(get_agent_service)]


@router.get("/status", response_model=ApiResponse[AgentStatus])
async def status(
    request: Request, current: Identity, response: Response
) -> ApiResponse[AgentStatus]:
    runtime = cast(AgentTurnRunner, request.app.state.agent_runtime)
    response.headers["Cache-Control"] = "no-store"
    return success(
        AgentStatus(
            configured=runtime.configured,
            message="Agent 已配置，可提交需求分析"
            if runtime.configured
            else "尚未配置 Agent 模型，请先完成服务端模型配置",
        )
    )


@router.get("/tasks", response_model=ApiResponse[TaskList])
async def tasks(current: Identity, response: Response, service: Agent) -> ApiResponse[TaskList]:
    response.headers["Cache-Control"] = "no-store"
    return success(await service.list(current.user_id))


@router.post("/tasks/detail", response_model=ApiResponse[TaskDetail])
async def task_detail(
    payload: TaskInput, current: Identity, response: Response, service: Agent
) -> ApiResponse[TaskDetail]:
    response.headers["Cache-Control"] = "no-store"
    return success(await service.get(current.user_id, str(payload.task_id)))


@router.post("/tasks/create", response_model=ApiResponse[TaskDetail | None])
async def create_task(
    payload: CreateTaskInput, current: Identity, response: Response, service: Agent
) -> ApiResponse[TaskDetail] | ApiResponse[None]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return success(await service.create(current.user_id, payload))
    except AgentBusinessError as exc:
        return fail(code=exc.code, msg=exc.msg)


@router.post("/tasks/message", response_model=ApiResponse[TaskDetail | None])
async def task_message(
    payload: MessageInput, current: Identity, response: Response, service: Agent
) -> ApiResponse[TaskDetail] | ApiResponse[None]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return success(await service.message(current.user_id, payload))
    except AgentBusinessError as exc:
        return fail(code=exc.code, msg=exc.msg)


@router.post("/tasks/retry", response_model=ApiResponse[TaskDetail | None])
async def retry_task(
    payload: RetryInput, current: Identity, response: Response, service: Agent
) -> ApiResponse[TaskDetail] | ApiResponse[None]:
    response.headers["Cache-Control"] = "no-store"
    try:
        return success(await service.retry(current.user_id, payload))
    except AgentBusinessError as exc:
        return fail(code=exc.code, msg=exc.msg)
