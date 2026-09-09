"""Checkpoint lifecycle and idempotent delivery of durable planning turns."""

import asyncio
import math
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from langsmith import tracing_context
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url

from app.agents.model import AgentModelError, CompatibleModel, Extractor
from app.agents.workflow import PlanningState, build_graph
from app.core.config import Settings
from app.schemas.agent import ChatMessage, GraphResult


def checkpoint_serializer() -> JsonPlusSerializer:
    """Only builtin JSON-like values; no pickle or arbitrary imported constructors."""
    return JsonPlusSerializer(
        pickle_fallback=False, allowed_json_modules=[], allowed_msgpack_modules=[]
    )


def postgres_url(settings: Settings) -> str:
    url = make_url(settings.database_url.get_secret_value())
    if url.drivername != "postgresql+psycopg":
        raise ValueError("Production Agent checkpoints require PostgreSQL")
    return url.set(drivername="postgresql").render_as_string(hide_password=False)


async def setup_checkpoints(settings: Settings) -> None:
    """Explicit operator command, never invoked by application startup or requests."""
    async with await AsyncConnection.connect(
        postgres_url(settings),
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=math.ceil(settings.database_timeout_seconds),
    ) as connection:
        await connection.execute("SELECT pg_advisory_lock(721430901)")
        try:
            await connection.execute("CREATE SCHEMA IF NOT EXISTS agent_graph")
            await connection.execute("SET search_path TO agent_graph")
            await AsyncPostgresSaver(connection, serde=checkpoint_serializer()).setup()
        finally:
            await connection.execute("SELECT pg_advisory_unlock(721430901)")


class AgentRuntime:
    def __init__(
        self,
        settings: Settings,
        *,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        extractor: Extractor | None = None,
    ) -> None:
        self.settings = settings
        self.checkpointer = checkpointer
        self.extractor = extractor
        self.pool: AsyncConnectionPool[AsyncConnection[dict[str, Any]]] | None = None
        self.model: CompatibleModel | None = None
        self.graph: CompiledStateGraph[PlanningState, None, PlanningState, PlanningState] | None = (
            None
        )

    @property
    def configured(self) -> bool:
        return self.extractor is not None or bool(
            self.settings.agent_model.strip()
            and self.settings.agent_api_key
            and self.settings.agent_api_key.get_secret_value().strip()
        )

    async def start(self) -> None:
        if not self.configured:
            return
        if self.checkpointer is None:
            self.pool = AsyncConnectionPool(
                postgres_url(self.settings),
                connection_class=AsyncConnection[dict[str, Any]],
                kwargs={
                    "autocommit": True,
                    "prepare_threshold": 0,
                    "row_factory": dict_row,
                    "options": "-c search_path=agent_graph",
                },
                min_size=0,
                max_size=3,
                timeout=self.settings.database_timeout_seconds,
                reconnect_timeout=self.settings.database_timeout_seconds,
                open=False,
            )
            await self.pool.open(wait=False)
            self.checkpointer = AsyncPostgresSaver(self.pool, serde=checkpoint_serializer())
        if self.extractor is None:
            self.model = CompatibleModel(self.settings)
            self.extractor = self.model
        self.graph = build_graph(self.extractor, self.checkpointer)

    async def run_turn(self, task_id: str, turn_id: str, message: str) -> GraphResult:
        """Caller holds the durable turn row lock until the result is committed.

        A worker crash may leave a checkpoint ahead of the business row. Re-delivery
        returns that completed result or resumes pending nodes without appending input twice.
        """
        if self.graph is None:
            raise AgentModelError("Agent 尚未配置或启动。")
        config: RunnableConfig = {"configurable": {"thread_id": task_id}, "recursion_limit": 12}
        try:
            with tracing_context(enabled=False):
                async with asyncio.timeout(self.settings.agent_turn_timeout_seconds):
                    snapshot = await self.graph.aget_state(config)
                    same_turn = snapshot.values.get("turn_id") == turn_id
                    waiting = any(task.interrupts for task in snapshot.tasks)
                    if same_turn and (waiting or not snapshot.next):
                        values = snapshot.values
                    else:
                        if same_turn:
                            graph_input: PlanningState | Command[Any] | None = None
                        elif waiting:
                            graph_input = Command(resume={"turn_id": turn_id, "message": message})
                        else:
                            graph_input = {
                                "turn_id": turn_id,
                                "messages": [
                                    *snapshot.values.get("messages", []),
                                    ChatMessage(role="user", content=message).model_dump(
                                        mode="json"
                                    ),
                                ],
                            }
                        values = await self.graph.ainvoke(graph_input, config, durability="sync")
                    return GraphResult.model_validate(
                        {
                            "messages": values["messages"],
                            "spec": values["spec"],
                            "questions": values["questions"],
                            "status": values["status"],
                        }
                    )
        except TimeoutError as exc:
            raise AgentModelError("需求分析超时，请重试。") from exc

    async def close(self) -> None:
        if self.model:
            await self.model.close()
        if self.pool:
            await self.pool.close()
