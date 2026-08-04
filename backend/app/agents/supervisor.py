"""Supervisor 节点：意图识别 + 路由（可并行 fan-out）。"""

from __future__ import annotations

import re
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Send
from pydantic import BaseModel, Field

from app.agents.state import GraphState
from app.core.logging import get_logger

_logger = get_logger(__name__)

SUPERVISOR_PROMPT = """你是 DeepMail 的【调度员】。根据用户 query，决定派发哪些专业 agent 并行处理。

可用 agent：
- email: 邮件查收 / 摘要 / 分类 / 列表
- todo: 待办列表 / 新建 / 标记完成
- draft: 起草 / 回复邮件（基于联系人历史）
- rag: 知识库检索（邮件+用户上传文档）
- tidy: 批量整理（批量分类、打标等）

规则：
- 只能选择 1~3 个 agent（避免并行风暴）
- 涉及多领域时并行；强依赖（如 draft 需要先 email 摘要）也只选 draft，由其内部调工具
- 你的回复**只**包含一个 JSON 对象（不加 ``` 包裹、不加任何说明文字），格式：
{"agents": ["email", "todo"], "reasoning": "..."}

用户 query：
{QUERY_PLACEHOLDER}

请立即输出 JSON："""


class RoutingDecision(BaseModel):
    agents: list[Literal["email", "todo", "draft", "rag", "tidy"]] = Field(
        min_length=1, max_length=3
    )
    reasoning: str = ""


def _strip_markdown_fence(text: str) -> str:
    """去掉 ```json ... ``` / ``` ... ``` 包裹。"""
    # 多行 ```...```
    text = re.sub(r"```(?:json)?\s*\n?(.*?)\n?```", r"\1", text, flags=re.DOTALL)
    # 单行 ```json {...}```
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    return text.strip()


def _parse_routing(raw_text: str) -> RoutingDecision:
    """LLM 输出可能含 markdown / 思考，先剥 ``` 块。"""
    text = _strip_markdown_fence(raw_text)
    # 找最外层 { ... } 块
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return RoutingDecision.model_validate_json(text)


async def supervisor_node(state: GraphState, llm) -> dict:
    """Supervisor 节点：调用 LLM 决定派发哪些 sub-agent。

    不使用 with_structured_output（OpenAI SDK 解析 ```json fence 会失败），
    改为手动 ainvoke + 解析，能处理 thinking + markdown fence。
    """
    query = state.get("user_query", "")
    if not query:
        return {"next_agents": ["email"], "current_intent": "fallback"}

    _logger.info("supervisor_decide", query=query[:80])
    msg = [
        SystemMessage(content=SUPERVISOR_PROMPT.replace("{QUERY_PLACEHOLDER}", query)),
        HumanMessage(content="请立即输出 JSON。"),
    ]
    response = await llm.ainvoke(msg)
    raw_text = response.content if isinstance(response.content, str) else str(response.content)
    try:
        decision = _parse_routing(raw_text)
    except Exception as e:
        _logger.warning("supervisor_parse_fallback", error=str(e), raw=raw_text[:200])
        decision = RoutingDecision(agents=["email"], reasoning=f"parse fallback: {e}")

    _logger.info(
        "supervisor_decision",
        agents=decision.agents,
        reasoning=decision.reasoning[:80],
    )
    return {
        "next_agents": decision.agents,
        "current_intent": ",".join(decision.agents),
    }


def dispatch(state: GraphState) -> list[Send]:
    """Conditional edge：把 Supervisor 决策 fan-out 到对应 sub-agent。

    限制最大并发为 3。
    """
    agents = state.get("next_agents") or ["email"]
    agents = agents[:3]  # 兜底：即使 LLM 给了 5 个，也只跑前 3
    _logger.info("dispatch", agents=agents)
    return [Send(agent_name, {**state, "current_intent": agent_name}) for agent_name in agents]
