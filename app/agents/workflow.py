"""Pure planning nodes; the interrupt node has no model calls or external side effects."""

from typing import Any, Literal, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import ValidationError

from app.agents.model import AgentModelError, Extractor
from app.schemas.agent import ChatMessage, DeploymentDraft, DeploymentSpec, ServiceSpec


class PlanningState(TypedDict, total=False):
    turn_id: str
    messages: list[dict[str, Any]]
    draft: dict[str, Any]
    spec: dict[str, Any] | None
    questions: list[str]
    status: Literal["needs_input", "ready"]


def validate_draft(draft: DeploymentDraft) -> tuple[DeploymentSpec | None, list[str]]:
    questions: list[str] = []
    if draft.unsupported_reason:
        questions.append(
            "当前支持 Kubernetes 内单实例 Redis/PostgreSQL、持久存储和集群内访问，请调整需求。"
        )
    if not draft.cluster:
        questions.append("部署到哪个 Kubernetes 集群（例如 poc）？")
    if not draft.namespace:
        questions.append("使用哪个命名空间？")
    if not draft.services:
        questions.append("需要部署 Redis、PostgreSQL，还是两者？")
    services: list[ServiceSpec] = []
    names: set[str] = set()
    for index, service in enumerate(draft.services, start=1):
        name = service.name or service.kind
        label = f"第 {index} 个服务（{name}）"
        if name in names:
            questions.append(f"请为{label}指定不重复的服务名称。")
        names.add(name)
        if service.version is None:
            questions.append(f"{label}使用哪个版本？")
        if service.storage_gi is None:
            questions.append(f"{label}需要多少 Gi 的持久存储？")
        if service.version is not None and service.storage_gi is not None:
            services.append(
                ServiceSpec(
                    kind=service.kind,
                    name=name,
                    version=service.version,
                    storage_gi=service.storage_gi,
                )
            )
    if questions:
        return None, questions
    assert draft.cluster and draft.namespace
    return DeploymentSpec(cluster=draft.cluster, namespace=draft.namespace, services=services), []


def build_graph(
    extractor: Extractor, checkpointer: BaseCheckpointSaver[Any]
) -> CompiledStateGraph[PlanningState, None, PlanningState, PlanningState]:
    async def understand(state: PlanningState) -> PlanningState:
        try:
            messages = [ChatMessage.model_validate(item) for item in state["messages"]]
            draft = await extractor.extract(messages)
            return {"draft": draft.model_dump(mode="json"), "spec": None, "questions": []}
        except ValidationError as exc:
            raise AgentModelError("保存的会话或模型结果格式无效，请新建方案。") from exc

    def validate(state: PlanningState) -> PlanningState:
        draft = DeploymentDraft.model_validate(state["draft"])
        spec, questions = validate_draft(draft)
        content = (
            "\n".join(questions)
            if questions
            else ("部署方案已生成，可继续补充或修改。当前尚未连接目标集群，也未创建任何资源。")
        )
        return {
            "spec": spec.model_dump(mode="json") if spec else None,
            "questions": questions,
            "status": "needs_input" if questions else "ready",
            "messages": [*state["messages"], {"role": "assistant", "content": content}],
        }

    def clarify(state: PlanningState) -> PlanningState:
        answer = interrupt({"questions": state["questions"]})
        # Only the server's persisted turn supplies resume data; it is not a public graph API.
        return {
            "turn_id": str(answer["turn_id"]),
            "messages": [
                *state["messages"],
                ChatMessage(role="user", content=answer["message"]).model_dump(mode="json"),
            ],
        }

    def route(state: PlanningState) -> Literal["clarify", "__end__"]:
        return "clarify" if state["questions"] else "__end__"

    builder = StateGraph(PlanningState)
    builder.add_node("understand", understand)
    builder.add_node("validate", validate)
    builder.add_node("clarify", clarify)
    builder.add_edge(START, "understand")
    builder.add_edge("understand", "validate")
    builder.add_conditional_edges("validate", route)
    builder.add_edge("clarify", "understand")
    return builder.compile(checkpointer=checkpointer)
