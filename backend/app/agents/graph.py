"""主图装配：Supervisor + 并行 sub-agents + Aggregator。"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.agents.aggregator import aggregator_node
from app.agents.state import GraphState
from app.agents.sub_agents import make_sub_agents
from app.agents.supervisor import dispatch, supervisor_node
from app.agents.tools.context import agent_context
from app.core.logging import get_logger
from app.llm.factory import get_chat_model

_logger = get_logger(__name__)


# 全局缓存构建好的图（用户级）
_graphs: dict[str, Any] = {}


async def build_graph(user_id: str, session_id: str, *, force_mock: bool = False):
    """为用户构建主图。

    Args:
        force_mock: 强制使用 MockLLM（单测 / 无 LLM key 时）
    """
    if force_mock or is_mock_mode_cached():
        from app.llm.mock import MockLLM

        sm: Any = MockLLM()
    else:
        sm = await get_chat_model(db=None, user_id=None)

    sub_agents = make_sub_agents(sm)

    async def sup(state):
        async with agent_context(user_id=user_id, session_id=session_id):
            return await supervisor_node(state, sm)

    async def agg(state):
        async with agent_context(user_id=user_id, session_id=session_id):
            return await aggregator_node(state, sm)

    def wrap(name, agent):
        async def wrapped(state):
            async with agent_context(user_id=user_id, session_id=session_id):
                return await agent.ainvoke(state)

        wrapped.__name__ = f"{name}_node"
        return wrapped

    wrapped_agents = {name: wrap(name, ag) for name, ag in sub_agents.items()}

    builder = StateGraph(GraphState)
    builder.add_node("supervisor", sup)
    for name, node in wrapped_agents.items():
        builder.add_node(name, node)
    builder.add_node("aggregator", agg)

    builder.add_edge(START, "supervisor")
    builder.add_conditional_edges(
        "supervisor",
        dispatch,
        {name: name for name in wrapped_agents.keys()},
    )
    for name in wrapped_agents.keys():
        builder.add_edge(name, "aggregator")
    builder.add_edge("aggregator", END)

    return builder.compile()


def is_mock_mode_cached() -> bool:
    from app.llm.factory import is_mock_mode

    return is_mock_mode()


async def get_or_build_graph(user_id: str, session_id: str, *, force_mock: bool = False):
    key = f"{user_id}:{session_id}"
    if key not in _graphs:
        _graphs[key] = await build_graph(user_id, session_id, force_mock=force_mock)
    return _graphs[key]


def clear_graph_cache() -> None:
    _graphs.clear()
