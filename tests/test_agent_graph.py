"""Exercise real LangGraph checkpoints, replay, interrupts and a bounded model boundary."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import aiosqlite
import httpx
import pytest
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from openai import AsyncOpenAI
from pydantic import SecretStr, ValidationError

from app.agents.model import AgentModelError, CompatibleModel
from app.agents.runtime import AgentRuntime, checkpoint_serializer, setup_checkpoints
from app.agents.workflow import validate_draft
from app.core.config import Settings
from app.core.context import trace_id
from app.core.event_loop import run_async
from app.schemas.agent import ChatMessage, DeploymentDraft


def draft(*, complete: bool = True, storage: int = 10) -> DeploymentDraft:
    return DeploymentDraft.model_validate(
        {
            "cluster": "poc",
            "namespace": "demo" if complete else None,
            "services": [{"kind": "redis", "name": None, "version": "7.4", "storage_gi": storage}],
            "unsupported_reason": None,
        }
    )


class ScriptedModel:
    def __init__(self, replies: list[DeploymentDraft | Exception]) -> None:
        self.replies = replies
        self.calls: list[list[ChatMessage]] = []

    async def extract(self, messages: list[ChatMessage]) -> DeploymentDraft:
        self.calls.append(messages)
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_interrupt_restarts_replays_and_revises_without_duplicate_messages(tmp_path: Path) -> None:
    path = tmp_path / "checkpoints.db"

    async def exercise() -> None:
        first = ScriptedModel([draft(complete=False)])
        async with aiosqlite.connect(path) as connection:
            saver = AsyncSqliteSaver(connection, serde=checkpoint_serializer())
            await saver.setup()
            runtime = AgentRuntime(Settings(_env_file=None), checkpointer=saver, extractor=first)
            await runtime.start()
            result = await runtime.run_turn("thread-a", "turn-a", "在 poc 部署 Redis7.4，10Gi")
            assert result.status == "needs_input" and result.spec is None
            assert result.questions == ["使用哪个命名空间？"]
            replay = await runtime.run_turn("thread-a", "turn-a", "在 poc 部署 Redis7.4，10Gi")
            assert result == replay and len(first.calls) == 1
        second = ScriptedModel([draft(), draft(storage=20)])
        async with aiosqlite.connect(path) as connection:
            saver = AsyncSqliteSaver(connection, serde=checkpoint_serializer())
            runtime = AgentRuntime(Settings(_env_file=None), checkpointer=saver, extractor=second)
            await runtime.start()
            result = await runtime.run_turn("thread-a", "turn-b", "命名空间 demo")
            assert result.status == "ready" and result.spec is not None
            assert result.spec.namespace == "demo" and result.spec.services[0].name == "redis"
            assert len(result.messages) == 4
            assert await runtime.run_turn("thread-a", "turn-b", "命名空间 demo") == result
            updated = await runtime.run_turn("thread-a", "turn-c", "改成20Gi")
            assert updated.spec is not None and updated.spec.services[0].storage_gi == 20
            assert len(updated.messages) == 6 and len(second.calls) == 2

    run_async(exercise())


@pytest.mark.parametrize("after_interrupt", [False, True])
def test_failed_model_node_retries_pending_work_without_readding_input(
    tmp_path: Path,
    after_interrupt: bool,
) -> None:
    async def exercise() -> None:
        replies: list[DeploymentDraft | Exception] = []
        if after_interrupt:
            replies.append(draft(complete=False))
        replies.extend([AgentModelError("safe-provider-failure"), draft()])
        model = ScriptedModel(replies)
        async with aiosqlite.connect(tmp_path / "retry.db") as connection:
            saver = AsyncSqliteSaver(connection, serde=checkpoint_serializer())
            runtime = AgentRuntime(Settings(_env_file=None), checkpointer=saver, extractor=model)
            await runtime.start()
            if after_interrupt:
                await runtime.run_turn("thread", "initial", "Redis")
            with pytest.raises(AgentModelError, match="safe-provider-failure"):
                await runtime.run_turn("thread", "retry-me", "命名空间demo")
            # Build a fresh runtime against persisted state, as after a worker restart.
            resumed = AgentRuntime(Settings(_env_file=None), checkpointer=saver, extractor=model)
            await resumed.start()
            result = await resumed.run_turn("thread", "retry-me", "命名空间demo")
            assert result.status == "ready"
            assert sum(item.content == "命名空间demo" for item in result.messages) == 1

    run_async(exercise())


def test_schema_rejects_code_invalid_names_and_unsupported_requests() -> None:
    payload = draft().model_dump()
    for key, value in [("command", "kubectl apply"), ("namespace", "../../default")]:
        with pytest.raises(ValidationError):
            DeploymentDraft.model_validate({**payload, key: value})
    payload["services"][0]["storage_gi"] = True
    with pytest.raises(ValidationError):
        DeploymentDraft.model_validate(payload)
    unsupported = draft().model_copy(update={"unsupported_reason": "requires HA"})
    spec, questions = validate_draft(unsupported)
    assert spec is None and questions
    duplicate = draft().model_copy(update={"services": [draft().services[0]] * 2})
    assert validate_draft(duplicate)[0] is None


def test_turn_deadline_cancels_model_and_keeps_input_recoverable(tmp_path: Path) -> None:
    class SlowModel:
        cancelled = False

        async def extract(self, messages: list[ChatMessage]) -> DeploymentDraft:
            try:
                await asyncio.Event().wait()
                return draft()
            finally:
                self.cancelled = True

    async def exercise() -> None:
        model = SlowModel()
        async with aiosqlite.connect(tmp_path / "timeout.db") as connection:
            saver = AsyncSqliteSaver(connection, serde=checkpoint_serializer())
            # Shorten only the test deadline; production settings require at least 5 seconds.
            settings = Settings(_env_file=None).model_copy(
                update={"agent_turn_timeout_seconds": 0.1}
            )
            runtime = AgentRuntime(settings, checkpointer=saver, extractor=model)
            await runtime.start()
            with pytest.raises(AgentModelError, match="超时"):
                await runtime.run_turn("timeout-thread", "turn", "Redis")
            assert model.cancelled
            resumed = AgentRuntime(
                Settings(_env_file=None), checkpointer=saver, extractor=ScriptedModel([draft()])
            )
            await resumed.start()
            result = await resumed.run_turn("timeout-thread", "turn", "Redis")
            assert result.status == "ready"
            assert [message.content for message in result.messages if message.role == "user"] == [
                "Redis"
            ]

    run_async(exercise())


@pytest.mark.parametrize("response_format", ["json_object", "json_schema"])
def test_model_uses_compatible_api_validates_json_and_propagates_only_trace(
    response_format: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "test-completion",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": draft().model_dump_json(),
                        },
                    }
                ],
            },
        )

    async def exercise() -> None:
        settings = Settings(
            _env_file=None, agent_model="test-model", agent_response_format=response_format
        )
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = AsyncOpenAI(
                api_key="model-only-key",
                base_url="https://gateway.invalid/v1",
                http_client=http,
                max_retries=0,
            )
            model = CompatibleModel(settings, client=client)
            token = trace_id.set("agent-trace")
            try:
                assert (
                    await model.extract([ChatMessage(role="user", content="部署 Redis")]) == draft()
                )
            finally:
                trace_id.reset(token)

    run_async(exercise())
    assert len(requests) == 1
    request = requests[0]
    assert str(request.url) == "https://gateway.invalid/v1/chat/completions"
    assert request.headers["x-request-id"] == "agent-trace"
    assert request.headers["authorization"] == "Bearer model-only-key"
    assert "cookie" not in request.headers
    payload = json.loads(request.content)
    assert payload["response_format"]["type"] == response_format
    assert payload["max_completion_tokens"] == 4096
    assert "model-only-key" not in request.content.decode()


@pytest.mark.parametrize(
    "case", ["http_error", "invalid_json", "truncated", "refusal", "no_choices"]
)
def test_model_failures_never_expose_provider_bodies(case: str) -> None:
    secret = "provider-private-payload"

    def handler(request: httpx.Request) -> httpx.Response:
        if case == "http_error":
            return httpx.Response(401, json={"error": {"message": secret}})
        return httpx.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": []
                if case == "no_choices"
                else [
                    {
                        "index": 0,
                        "finish_reason": "length" if case == "truncated" else "stop",
                        "message": {
                            "role": "assistant",
                            "content": secret,
                            "refusal": secret if case == "refusal" else None,
                        },
                    }
                ],
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = AsyncOpenAI(api_key="test-only", http_client=http, max_retries=0)
            model = CompatibleModel(Settings(_env_file=None, agent_model="test"), client=client)
            with pytest.raises(AgentModelError) as error:
                await model.extract([ChatMessage(role="user", content="Redis")])
            assert secret not in str(error.value)

    run_async(exercise())


@pytest.mark.skipif(
    not os.environ.get("OLIXOPS_TEST_DATABASE_URL"), reason="Isolated PostgreSQL URL not configured"
)
def test_real_postgres_checkpoint_restart_and_replay() -> None:
    async def exercise() -> None:
        settings = Settings(
            _env_file=None, database_url=SecretStr(os.environ["OLIXOPS_TEST_DATABASE_URL"])
        )
        await setup_checkpoints(settings)
        task_id = str(uuid4())
        first = AgentRuntime(settings, extractor=ScriptedModel([draft(complete=False)]))
        await first.start()
        try:
            result = await first.run_turn(task_id, "turn-1", "Redis")
            assert result.status == "needs_input"
        finally:
            await first.close()
        second = AgentRuntime(settings, extractor=ScriptedModel([draft()]))
        await second.start()
        try:
            result = await second.run_turn(task_id, "turn-2", "demo")
            assert result.status == "ready"
            assert await second.run_turn(task_id, "turn-2", "demo") == result
        finally:
            assert second.checkpointer is not None
            await second.checkpointer.adelete_thread(task_id)
            await second.close()

    run_async(exercise())
