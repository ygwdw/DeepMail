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
- email: 邮件查收 / 摘要 / 分类 / 列表（用 list_emails / get_email 等工具，按 folder/sender/date 过滤）
- todo: 待办列表 / 新建 / 标记完成
- draft: 起草 / 回复邮件（基于联系人历史）
- rag: 知识库混合检索（向量 + BM25 + Rerank）—— 查找**邮件正文/主题**相关内容时**优先**选这个！
- tidy: 批量整理（批量分类、打标等）

v2-M4.3: L5 知识库注入状态
- l5_injected: {L5_STATUS}
- 当 l5_injected=true 时，rag agent **不要重复检索**（检索结果已经在 system prompt 里）。改派 email agent 处理检索结果。
- 当 l5_injected=false 时，按下面的 rag 规则判断。

规则（v2-P2：默认不派发，宁缺毋滥）：
- **只有用户明确表达邮件 / 待办 / 草稿 / 知识库 / 批量整理 的操作意图时，才选择对应 agent**
- 用户只是问候、闲聊、吐槽、告知状态/日程、意图不清、或没有可执行操作时，输出 {"agents": [], "reasoning": "..."} 表示**直接聊天、不调用任何 agent**
- 例子：
  - "帮我记个待办：下周交报告" → todo；"我下周二去看电影"（只是告知）→ []
  - "看看有没有某人的邮件" → email；"查一下关于 X 的邮件" → rag
  - "你好""在吗""今天天气不错" → []
- 宁可少派发，也不要乱派发；不要为了"做点什么"而硬选 agent
- 只能选择 0~3 个 agent（0 = 直接聊天；避免并行风暴）
- 涉及多领域时并行；强依赖（如 draft 需要先 email 摘要）也只选 draft，由其内部调工具
- 当 l5_injected=false 且用户问"找 / 搜索 / 查找 / 关于 / 提到 / 讨论 X 的邮件"时，可以包含 rag agent（混合检索能按关键字匹配正文）
  - email agent 的 list_emails 只支持 folder/sender/日期过滤，**无法按内容关键字搜索**！
- 你的回复**只**包含一个 JSON 对象（不加 ``` 包裹、不加任何说明文字），格式：
{"agents": ["email", "todo"], "reasoning": "..."}   或   {"agents": [], "reasoning": "直接聊天，不派发"}

用户 query：
{QUERY_PLACEHOLDER}

请立即输出 JSON："""


class RoutingDecision(BaseModel):
    agents: list[Literal["email", "todo", "draft", "rag", "tidy"]] = Field(
        min_length=0,
        max_length=3,
        description="要派发的 agent 列表；空数组表示直接聊天、不调用任何 agent（v2-P2）",
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

    # v2-M4.3: L5 注入状态拼到 prompt
    l5_injected = bool(state.get("l5_injected", False))
    l5_status = "true（外部知识库已挂载到 system prompt；不要重复路由 rag）" if l5_injected else "false（未挂载；按需路由 rag）"
    prompt = SUPERVISOR_PROMPT.replace("{QUERY_PLACEHOLDER}", query).replace(
        "{L5_STATUS}", l5_status
    )

    _logger.info("supervisor_decide", query=query[:80], l5_injected=l5_injected)
    msg = [
        SystemMessage(content=prompt),
        HumanMessage(content="请立即输出 JSON。"),
    ]
    response = await llm.ainvoke(msg)
    raw_text = response.content if isinstance(response.content, str) else str(response.content)
    try:
        decision = _parse_routing(raw_text)
    except Exception as e:
        _logger.warning("supervisor_parse_fallback", error=str(e), raw=raw_text[:200])
        decision = RoutingDecision(agents=["email"], reasoning=f"parse fallback: {e}")

    # v2-M4.3: L5 已注入时硬约束去除 rag（避免 LLM 漏判时仍重复检索）
    if l5_injected and "rag" in decision.agents:
        decision.agents = [a for a in decision.agents if a != "rag"] or ["email"]
        _logger.info(
            "supervisor_rag_suppressed",
            remaining=decision.agents,
            reason="l5_injected=true",
        )

    _logger.info(
        "supervisor_decision",
        agents=decision.agents,
        reasoning=decision.reasoning[:80],
    )
    # v2-P2: 空路由 → 直接聊天（不派发任何 agent）
    current_intent = ",".join(decision.agents) if decision.agents else "chat"
    return {
        "next_agents": decision.agents,
        "current_intent": current_intent,
    }


def dispatch(state: GraphState) -> list[Send] | list[str]:
    """Conditional edge：把 Supervisor 决策 fan-out 到对应 sub-agent。

    限制最大并发为 3。
    v2-M4.3: L5 已注入时硬剥 rag（兜底；supervisor_node 也已过滤）。
    v2-P2: next_agents 为空 → 路由到 "chat" 节点（直接聊天）。
    """
    agents = state.get("next_agents") or []
    if not agents:
        _logger.info("dispatch_chat_only", l5_injected=bool(state.get("l5_injected", False)))
        return ["chat"]
    agents = agents[:3]  # 兜底：即使 LLM 给了 5 个，也只跑前 3
    l5_injected = bool(state.get("l5_injected", False))
    if l5_injected and "rag" in agents:
        agents = [a for a in agents if a != "rag"] or ["email"]
        _logger.warning("dispatch_rag_stripped", l5_injected=l5_injected)
    _logger.info("dispatch", agents=agents, l5_injected=l5_injected)
    return [Send(agent_name, {**state, "current_intent": agent_name}) for agent_name in agents]
