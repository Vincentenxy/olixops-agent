"""Durable agent submission, authorization, retries and queue crash recovery."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import UUID, uuid4

import aiosqlite
import pytest
from fastapi import FastAPI
from httpx2 import ASGITransport, AsyncClient
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from starlette.exceptions import HTTPException

from app.agents.model import AgentModelError
from app.agents.runtime import AgentRuntime, checkpoint_serializer
from app.api.agent import router
from app.api.dependencies import get_current_user
from app.core.config import Settings
from app.core.context import trace_id
from app.core.database import Database
from app.core.event_loop import run_async
from app.core.exceptions import register_exception_handlers
from app.models.agent import AgentTask, AgentTurn
from app.models.auth import Base, LocalUser
from app.schemas.agent import (
    ChatMessage,
    CreateTaskInput,
    DeploymentDraft,
    GraphResult,
    MessageInput,
    RetryInput,
)
from app.schemas.auth import CurrentUser
from app.services.agent import AgentBusinessError, AgentService
from app.workers.agent import process_next, run_worker


@asynccontextmanager
async def prepared_database(path: Path) -> AsyncIterator[Database]:
    database = Database(
        Settings(_env_file=None, database_url=SecretStr(f"sqlite+aiosqlite:///{path}"))
    )
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with database.sessions() as session, session.begin():
            session.add_all(
                [
                    LocalUser(
                        user_id=user_id,
                        username=user_id,
                        name=user_id,
                        password_hash="unused-test-hash",
                    )
                    for user_id in ["owner", "other"]
                ]
            )
        yield database
    finally:
        await database.close()


class Runner:
    configured = True

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.saved: dict[str, GraphResult] = {}
        self.conversations: dict[str, list[ChatMessage]] = {}
        self.failure: Exception | None = None
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.crash_after_checkpoint = False

    async def run_turn(self, task_id: str, turn_id: str, message: str) -> GraphResult:
        self.calls.append((task_id, turn_id, message))
        self.started.set()
        await self.release.wait()
        if self.failure:
            raise self.failure
        if turn_id not in self.saved:
            messages = [
                *self.conversations.get(task_id, []),
                ChatMessage(role="user", content=message),
                ChatMessage(role="assistant", content="请补充命名空间"),
            ]
            self.conversations[task_id] = messages
            self.saved[turn_id] = GraphResult(
                messages=messages, spec=None, questions=["请补充命名空间"], status="needs_input"
            )
        if self.crash_after_checkpoint:
            self.crash_after_checkpoint = False
            raise asyncio.CancelledError
        return self.saved[turn_id]


def test_submission_idempotency_ownership_and_model_configuration(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with prepared_database(tmp_path / "agent.db") as database:
            request = CreateTaskInput(request_id=uuid4(), message="部署 Redis")
            async with database.sessions() as session:
                service = AgentService(session, configured=False)
                with pytest.raises(AgentBusinessError) as missing:
                    await service.create("owner", request)
                assert missing.value.code == 11001
                service.configured = True
                created = await service.create("owner", request)
                assert created.status == "queued" and created.revision == 1
                assert created.messages == [ChatMessage(role="user", content="部署 Redis")]
                assert await service.create("owner", request) == created
                with pytest.raises(AgentBusinessError) as conflict:
                    await service.create("owner", request.model_copy(update={"message": "pgsql"}))
                assert conflict.value.code == 11005
                with pytest.raises(HTTPException) as forbidden:
                    await service.get("other", created.task_id)
                assert forbidden.value.status_code == 403
                with pytest.raises(HTTPException) as replay_forbidden:
                    await service.create("other", request)
                assert replay_forbidden.value.status_code == 403
                with pytest.raises(HTTPException) as missing_task:
                    await service.get("owner", str(uuid4()))
                assert missing_task.value.status_code == 404
                assert (await service.list("other")).items == []
                assert [item.task_id for item in (await service.list("owner")).items] == [
                    created.task_id
                ]
            async with database.sessions() as session:
                assert await session.scalar(select(func.count()).select_from(AgentTask)) == 1
                assert await session.scalar(select(func.count()).select_from(AgentTurn)) == 1

    run_async(exercise())


def test_worker_completion_and_message_replay_are_persistent(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with prepared_database(tmp_path / "agent.db") as database:
            runtime = Runner()
            async with database.sessions() as session:
                service = AgentService(session, configured=True)
                created = await service.create(
                    "owner", CreateTaskInput(request_id=uuid4(), message="部署 Redis")
                )
            assert await process_next(database, runtime)
            assert not await process_next(database, runtime)
            async with database.sessions() as session:
                service = AgentService(session, configured=True)
                ready = await service.get("owner", created.task_id)
                assert ready.status == "needs_input" and ready.questions == ["请补充命名空间"]
                follow_up = MessageInput(
                    task_id=UUID(created.task_id),
                    request_id=uuid4(),
                    expected_revision=1,
                    message="命名空间 poc",
                )
                queued = await service.message("owner", follow_up)
                assert queued.revision == 2 and queued.status == "queued"
                assert await service.message("owner", follow_up) == queued
                with pytest.raises(AgentBusinessError) as busy:
                    await service.message(
                        "owner", follow_up.model_copy(update={"request_id": uuid4()})
                    )
                assert busy.value.code == 11002
            assert await process_next(database, runtime)
            async with database.sessions() as session:
                service = AgentService(session, configured=True)
                completed = await service.message("owner", follow_up)
                assert completed.status == "needs_input" and len(completed.messages) == 4
                with pytest.raises(AgentBusinessError) as stale:
                    await service.message(
                        "owner", follow_up.model_copy(update={"request_id": uuid4()})
                    )
                assert stale.value.code == 11003
                with pytest.raises(AgentBusinessError) as changed:
                    await service.message(
                        "owner", follow_up.model_copy(update={"message": "other"})
                    )
                assert changed.value.code == 11005
            assert len(runtime.calls) == 2

    run_async(exercise())


def test_request_ids_cannot_be_reused_between_tasks(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with prepared_database(tmp_path / "agent.db") as database:
            runtime = Runner()
            async with database.sessions() as session:
                service = AgentService(session, configured=True)
                first = await service.create(
                    "owner", CreateTaskInput(request_id=uuid4(), message="one")
                )
                second = await service.create(
                    "owner", CreateTaskInput(request_id=uuid4(), message="two")
                )
            assert await process_next(database, runtime)
            assert await process_next(database, runtime)
            async with database.sessions() as session:
                service = AgentService(session, configured=True)
                with pytest.raises(AgentBusinessError) as reused:
                    await service.message(
                        "owner",
                        MessageInput(
                            task_id=UUID(second.task_id),
                            request_id=UUID(first.task_id),
                            expected_revision=1,
                            message="one",
                        ),
                    )
                assert reused.value.code == 11005

    run_async(exercise())


@pytest.mark.parametrize("unexpected", [False, True])
def test_failure_and_retry_reuse_turn_without_duplicating_messages(
    tmp_path: Path, unexpected: bool
) -> None:
    async def exercise() -> None:
        async with prepared_database(tmp_path / "agent.db") as database:
            runtime = Runner()
            runtime.failure = (
                RuntimeError("private provider response")
                if unexpected
                else AgentModelError("模型输出不符合要求，请重试")
            )
            async with database.sessions() as session:
                created = await AgentService(session, configured=True).create(
                    "owner", CreateTaskInput(request_id=uuid4(), message="Redis")
                )
            assert await process_next(database, runtime)
            async with database.sessions() as session:
                service = AgentService(session, configured=True)
                failed = await service.get("owner", created.task_id)
                assert failed.status == "failed" and failed.error
                assert "private" not in failed.error
                assert len(failed.messages) == 1
                retried = await service.retry(
                    "owner", RetryInput(task_id=UUID(created.task_id), expected_revision=1)
                )
                assert retried.status == "queued" and retried.revision == 1
            runtime.failure = None
            assert await process_next(database, runtime)
            assert runtime.calls[0] == runtime.calls[1]
            async with database.sessions() as session:
                finished = await AgentService(session, configured=True).get(
                    "owner", created.task_id
                )
                assert finished.error is None and len(finished.messages) == 2
                assert await session.scalar(select(func.count()).select_from(AgentTurn)) == 1

    run_async(exercise())


def test_cancellation_releases_unacknowledged_turn_for_checkpoint_replay(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with prepared_database(tmp_path / "agent.db") as database:
            runtime = Runner()
            runtime.crash_after_checkpoint = True
            trace_token = trace_id.set("queue-test-trace")
            try:
                async with database.sessions() as session:
                    created = await AgentService(session, configured=True).create(
                        "owner", CreateTaskInput(request_id=uuid4(), message="Redis")
                    )
            finally:
                trace_id.reset(trace_token)
            with pytest.raises(asyncio.CancelledError):
                await process_next(database, runtime)
            assert trace_id.get() is None
            async with database.sessions() as session:
                pending = await AgentService(session, configured=True).get("owner", created.task_id)
                assert pending.status == "queued"
            assert await process_next(database, runtime)
            assert len(runtime.saved) == 1 and runtime.calls[0] == runtime.calls[1]
            async with database.sessions() as session:
                done = await AgentService(session, configured=True).get("owner", created.task_id)
                assert done.status == "needs_input" and len(done.messages) == 2

    run_async(exercise())


def test_queue_limits_and_maximum_conversation_turns(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with prepared_database(tmp_path / "agent.db") as database:
            runtime = Runner()
            async with database.sessions() as session:
                service = AgentService(session, configured=True)
                initial = [
                    await service.create(
                        "owner", CreateTaskInput(request_id=uuid4(), message="Redis")
                    )
                    for _ in range(5)
                ]
                with pytest.raises(AgentBusinessError) as capacity:
                    await service.create(
                        "owner", CreateTaskInput(request_id=uuid4(), message="sixth")
                    )
                assert capacity.value.code == 11004
            while await process_next(database, runtime):
                pass
            for revision in range(1, 20):
                async with database.sessions() as session:
                    await AgentService(session, configured=True).message(
                        "owner",
                        MessageInput(
                            task_id=UUID(initial[0].task_id),
                            request_id=uuid4(),
                            expected_revision=revision,
                            message=f"namespace {revision}",
                        ),
                    )
                assert await process_next(database, runtime)
            async with database.sessions() as session:
                with pytest.raises(AgentBusinessError) as turns:
                    await AgentService(session, configured=True).message(
                        "owner",
                        MessageInput(
                            task_id=UUID(initial[0].task_id),
                            request_id=uuid4(),
                            expected_revision=20,
                            message="next",
                        ),
                    )
                assert turns.value.code == 11004

    run_async(exercise())


def test_api_envelopes_and_submission_does_not_run_model(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with prepared_database(tmp_path / "agent.db") as database:
            runtime = Runner()
            app = FastAPI()
            app.state.database = database
            app.state.agent_runtime = runtime
            register_exception_handlers(app)
            app.include_router(router)
            identity = CurrentUser(
                user_id="owner",
                username="owner",
                name="Owner",
                is_admin=False,
                session_id="test",
                jwt="unused",
                cookie="",
            )
            app.dependency_overrides[get_current_user] = lambda: identity
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                request_id = str(uuid4())
                response = await client.post(
                    "/api/v1/agent/tasks/create",
                    json={"request_id": request_id, "message": "Redis"},
                )
                assert response.status_code == 200 and response.json()["code"] == 0
                assert response.json()["data"]["status"] == "queued"
                assert response.headers["Cache-Control"] == "no-store"
                assert not runtime.calls
                invalid = await client.post(
                    "/api/v1/agent/tasks/create", json={"request_id": request_id, "message": "  "}
                )
                assert invalid.status_code == 422 and invalid.json()["code"] == 422
                conflict = await client.post(
                    "/api/v1/agent/tasks/create",
                    json={"request_id": request_id, "message": "pgsql"},
                )
                assert conflict.json()["code"] == 11005 and conflict.json()["data"] is None
                identity = identity.model_copy(update={"user_id": "other"})
                forbidden = await client.post(
                    "/api/v1/agent/tasks/detail", json={"task_id": request_id}
                )
                assert forbidden.status_code == 403 and forbidden.json()["code"] == 403
                assert (await client.get("/api/v1/agent/tasks")).json()["data"]["items"] == []

    run_async(exercise())


def test_worker_stops_while_idle(tmp_path: Path) -> None:
    async def exercise() -> None:
        async with prepared_database(tmp_path / "agent.db") as database:
            stop = asyncio.Event()
            worker = asyncio.create_task(run_worker(database, Runner(), stop))
            stop.set()
            await asyncio.wait_for(worker, timeout=1)

    run_async(exercise())


def test_api_worker_graph_checkpoint_restart_and_resume(tmp_path: Path) -> None:
    class Extractor:
        def __init__(self, namespace: str | None) -> None:
            self.namespace = namespace
            self.calls: list[list[ChatMessage]] = []

        async def extract(self, messages: list[ChatMessage]) -> DeploymentDraft:
            self.calls.append(messages)
            return DeploymentDraft.model_validate(
                {
                    "cluster": "poc",
                    "namespace": self.namespace,
                    "services": [
                        {"kind": "redis", "name": None, "version": "7.4", "storage_gi": 10}
                    ],
                    "unsupported_reason": None,
                }
            )

    async def exercise() -> None:
        async with prepared_database(tmp_path / "business.db") as database:
            identity = CurrentUser(
                user_id="owner",
                username="owner",
                name="Owner",
                is_admin=False,
                session_id="test",
                jwt="unused",
                cookie="",
            )

            def application(extractor: Extractor) -> FastAPI:
                @asynccontextmanager
                async def lifespan(app: FastAPI) -> AsyncIterator[None]:
                    async with aiosqlite.connect(tmp_path / "checkpoints.db") as connection:
                        saver = AsyncSqliteSaver(connection, serde=checkpoint_serializer())
                        await saver.setup()
                        runtime = AgentRuntime(
                            Settings(_env_file=None), checkpointer=saver, extractor=extractor
                        )
                        await runtime.start()
                        app.state.agent_runtime = runtime
                        stop = asyncio.Event()
                        worker = asyncio.create_task(run_worker(database, runtime, stop))
                        try:
                            yield
                        finally:
                            stop.set()
                            worker.cancel()
                            with suppress(asyncio.CancelledError):
                                await worker
                            await runtime.close()

                app = FastAPI(lifespan=lifespan)
                app.state.database = database
                app.dependency_overrides[get_current_user] = lambda: identity
                register_exception_handlers(app)
                app.include_router(router)
                return app

            async def await_status(
                client: AsyncClient, task_id: str, expected: str
            ) -> dict[str, object]:
                async with asyncio.timeout(5):
                    while True:
                        response = await client.post(
                            "/api/v1/agent/tasks/detail", json={"task_id": task_id}
                        )
                        assert response.status_code == 200 and response.json()["code"] == 0
                        data: dict[str, object] = response.json()["data"]
                        if data["status"] == expected:
                            return data
                        assert data["status"] == "queued", data
                        await asyncio.sleep(0.02)

            task_id = str(uuid4())
            first_model = Extractor(None)
            first_app = application(first_model)
            async with first_app.router.lifespan_context(first_app):
                async with AsyncClient(
                    transport=ASGITransport(app=first_app), base_url="http://test"
                ) as client:
                    response = await client.post(
                        "/api/v1/agent/tasks/create",
                        json={"request_id": task_id, "message": "poc 集群部署 Redis 7.4，10Gi"},
                    )
                    assert response.json()["data"]["status"] == "queued"
                    waiting = await await_status(client, task_id, "needs_input")
                    assert waiting["questions"] == ["使用哪个命名空间？"]
                    assert len(first_model.calls) == 1

            # Close graph/checkpoint connections, then start a new consumer against both stores.
            await database.engine.dispose()
            second_model = Extractor("demo")
            second_app = application(second_model)
            async with second_app.router.lifespan_context(second_app):
                async with AsyncClient(
                    transport=ASGITransport(app=second_app), base_url="http://test"
                ) as client:
                    items = (await client.get("/api/v1/agent/tasks")).json()["data"]["items"]
                    assert len(items) == 1 and items[0]["task_id"] == task_id
                    message = {
                        "task_id": task_id,
                        "request_id": str(uuid4()),
                        "expected_revision": 1,
                        "message": "使用 demo 命名空间",
                    }
                    queued = await client.post("/api/v1/agent/tasks/message", json=message)
                    assert queued.json()["data"]["status"] == "queued"
                    complete = await await_status(client, task_id, "ready")
                    assert complete["revision"] == 2
                    assert complete["spec"] == {
                        "target": "kubernetes",
                        "cluster": "poc",
                        "namespace": "demo",
                        "services": [
                            {
                                "kind": "redis",
                                "name": "redis",
                                "version": "7.4",
                                "storage_gi": 10,
                                "replicas": 1,
                            }
                        ],
                    }
                    replayed = await client.post("/api/v1/agent/tasks/message", json=message)
                    assert replayed.json()["data"] == complete
                    assert len(second_model.calls) == 1
                    assert [item.role for item in second_model.calls[0]] == [
                        "user",
                        "assistant",
                        "user",
                    ]
                    assert len(replayed.json()["data"]["messages"]) == 4

    run_async(exercise())


@pytest.mark.skipif(
    not os.environ.get("OLIXOPS_TEST_DATABASE_URL"), reason="Isolated PostgreSQL URL not configured"
)
def test_postgres_capacity_and_workers_skip_locked_turns() -> None:
    async def exercise() -> None:
        database = Database(
            Settings(
                _env_file=None, database_url=SecretStr(os.environ["OLIXOPS_TEST_DATABASE_URL"])
            )
        )
        owner = str(uuid4())
        first_worker: asyncio.Task[bool] | None = None
        try:
            async with database.sessions() as session, session.begin():
                session.add(
                    LocalUser(
                        user_id=owner,
                        username=f"agent-{uuid4().hex}",
                        name="Agent test",
                        password_hash="unused",
                    )
                )

            async def submit() -> int:
                async with database.sessions() as session:
                    try:
                        await AgentService(session, configured=True).create(
                            owner, CreateTaskInput(request_id=uuid4(), message="Redis")
                        )
                        return 0
                    except AgentBusinessError as exc:
                        return exc.code

            codes = await asyncio.gather(*(submit() for _ in range(8)))
            assert codes.count(0) == 5 and codes.count(11004) == 3
            first = Runner()
            first.release.clear()
            first_worker = asyncio.create_task(process_next(database, first))
            await asyncio.wait_for(first.started.wait(), timeout=5)
            second = Runner()
            assert await asyncio.wait_for(process_next(database, second), timeout=5)
            assert first.calls[0][1] != second.calls[0][1]
            # The active task row is not locked by its worker; a new request fails promptly.
            async with database.sessions() as session:
                with pytest.raises(AgentBusinessError) as busy:
                    await asyncio.wait_for(
                        AgentService(session, configured=True).message(
                            owner,
                            MessageInput(
                                task_id=UUID(first.calls[0][0]),
                                request_id=uuid4(),
                                expected_revision=1,
                                message="next",
                            ),
                        ),
                        timeout=2,
                    )
                assert busy.value.code == 11002
            first.release.set()
            assert await asyncio.wait_for(first_worker, timeout=5)
        finally:
            if first_worker is not None and not first_worker.done():
                first_worker.cancel()
                await asyncio.gather(first_worker, return_exceptions=True)
            async with database.sessions() as session, session.begin():
                await session.execute(delete(LocalUser).where(LocalUser.user_id == owner))
            await database.close()

    run_async(exercise())
