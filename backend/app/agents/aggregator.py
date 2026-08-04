"""Aggregator 节点：把多个 sub-agent 的输出汇总成最终回复。"""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agents.state import GraphState
from app.core.logging import get_logger

_logger = get_logger(__name__)

AGGREGATOR_PROMPT = """你是 DeepMail 的【汇总员】。多个 sub-agent 已并行完成各自任务。
请把它们的最终回复汇总成一条简洁、面向用户的最终回复。

规则：
- 直接给用户结论（不要列举"agent A 说..."这种元信息）
- 保留关键数据（todo 内容、邮件摘要、命中分数等）
- 中文输出
- 如有错误（error 字段），简要说明
"""


async def aggregator_node(state: GraphState, llm) -> dict:
    """汇总所有 sub-agent 的最后一条 AI 消息。"""
    messages = state.get("messages", [])
    # 提取最近 5 条 AI 消息
    ai_msgs = [m for m in messages if isinstance(m, AIMessage)][-5:]
    if not ai_msgs:
        return {"final_response": "（无结果）"}

    user_query = state.get("user_query", "")
    summary_text = "\n\n---\n\n".join(
        f"[Agent 输出]\n{m.content if isinstance(m.content, str) else str(m.content)}"
        for m in ai_msgs
    )

    msgs = [
        SystemMessage(content=AGGREGATOR_PROMPT),
        HumanMessage(
            content=f"用户原始 query：{user_query}\n\n以下是各 sub-agent 的输出：\n\n{summary_text}"
        ),
    ]
    response = await llm.ainvoke(msgs)
    final = response.content if isinstance(response.content, str) else str(response.content)
    _logger.info("aggregator_done", final_len=len(final))
    return {
        "final_response": final,
        "messages": [AIMessage(content=final)],  # 也加到消息历史
    }
