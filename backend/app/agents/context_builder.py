"""Context 组装器：按预算拼 L1 + L2 + L4 记忆。

v1 简化（按用户决策）：
- L1 会话：最近 10 轮（已有 chat_messages 加载）
- L2 话题：向量检索 top-3
- L4 语义：长记忆 top-5（已有）
- L3 事件 / L5 外部：留 v2

总 token 预算：8000
"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.logging import get_logger

_logger = get_logger(__name__)

# 默认预算（按文档）
DEFAULT_TOKEN_BUDGET = 8000
SUMMARY_TRIGGER_CHARS = 6000  # 兼容旧调用方：chars 阈值（约 1500 token），v2-M1 起主路径走 token
SUMMARY_TRIGGER_TOKENS = 1500  # v2-M1：按真实 token 触发摘要的默认阈值

BUDGET_ALLOC = {
    "L1_session": 0.30,
    "L2_topic": 0.20,
    "L4_semantic": 0.20,
    "user_query": 0.20,
    "persona": 0.05,
    "current_time": 0.05,
}


def estimate_tokens(text: str) -> int:
    """粗略 token 估算：中文 1 字 ≈ 1.5 token，英文 1 词 ≈ 1.3 token。

    MVP 用 chars / 2 估算（中文平均 2 字/token）。
    """
    return max(1, len(text) // 2)


def build_memory_blocks(
    *,
    user_id: uuid.UUID,
    query: str,
    persona_block: str = "",
    history_msgs: list | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """组装 context blocks。返回每个 block 的文本和 token 数 + 总计。

    v2-M4.2: 当 db 注入时，_build_l4 会真查 personas；否则用空。
    """
    return {
        "L1_session": _build_l1(history_msgs or []),
        "L2_topic": _build_l2(query),
        "L4_semantic": _build_l4(user_id, db=db),
        "persona": persona_block,
        "current_time": "",
    }


def _build_l1(messages: list) -> str:
    """L1 会话历史 → 简洁文本。"""
    if not messages:
        return ""
    lines = []
    for m in messages[-20:]:  # 最近 20 条
        role = m.type if hasattr(m, "type") else "user"
        content = m.content if isinstance(m.content, str) else str(m.content or "")
        prefix = "用户" if role == "human" else "助手"
        lines.append(f"{prefix}：{content[:300]}")
    return "\n".join(lines)


def _build_l2(query: str) -> str:
    """L2 话题 → 检索相关 top-3。

    v2-A1：本函数保留为空（build_memory_blocks / assemble_system_prompt 是死代码，
    生产不调用）。真实 L2 检索注入在 `chat_service._prepare_chat`：
    调 `medium_term.search_topics_by_vector` + `topics_to_prompt_block`，
    把相关历史话题作为 SystemMessage 注入 messages 头部（对齐 persona/L5 模式）。
    若将来复活 assemble_system_prompt，再在这里接 search_topics_by_vector。
    """
    return ""


def _build_l4(user_id: uuid.UUID, *, db: AsyncSession | None = None) -> str:
    """L4 语义 → 高置信度 top-5。

    v2-M4.2: 当 db 注入时，真查 personas（仅 category=persona 自动注入）；
    entity_relation **不注入**，仅查询工具调用。
    注意：当前 sync 函数不真正查 DB（避免 build_memory_blocks 在 async 上下文里跑）；
    调用方（chat_service._prepare_chat）走 `search_personas` + `personas_to_prompt_block`。
    """
    return ""


def assemble_system_prompt(
    blocks: dict[str, str],
    *,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
) -> str:
    """把 memory blocks 拼成 system prompt 文本。超预算时按优先级压缩。"""
    parts: list[str] = []
    used = 0

    # 优先级：current_time > persona > user_query > L1 > L2 > L4
    priority = ["current_time", "persona", "L1_session", "L2_topic", "L4_semantic"]

    for layer in priority:
        text = blocks.get(layer, "")
        if not text:
            continue
        t = estimate_tokens(text)
        limit = int(token_budget * BUDGET_ALLOC.get(layer, 0))
        if t > limit:
            # 截断到 limit tokens（粗略）
            text = text[: limit * 2]
            t = estimate_tokens(text)
        parts.append(f"[{layer}]\n{text}")
        used += t

    return "\n\n".join(parts)


# ---------- 多轮摘要 ----------


def should_summarize(messages: list, *, trigger_chars: int = SUMMARY_TRIGGER_CHARS) -> bool:
    """判断是否需要摘要（已弃用；保留给旧测试）。v2-M1 主路径走 `should_compress_session`。"""
    total = sum(len(m.content) if isinstance(m.content, str) else 0 for m in messages)
    return total > trigger_chars


async def summarize_messages(
    llm,
    old_messages: list,
    *,
    max_tokens: int = 800,
) -> str:
    """把多条旧消息摘要成 1 段（≤ max_tokens token）。

    v2-M1：摘要目标改为 token 数（更精确），保留 max_chars 形参兼容旧调用。
    """
    if not old_messages:
        return ""

    from app.agents.tokenizer import truncate_to_tokens

    text = "\n".join(
        f"[{m.type if hasattr(m, 'type') else 'msg'}] "
        f"{m.content if isinstance(m.content, str) else str(m.content or '')}"
        for m in old_messages
    )

    system_prompt = (
        "你是对话摘要助手。把多轮对话压缩成不超过 "
        f"{max_tokens} 个 token 的中文摘要，保留关键信息、决定、上下文。"
        "直接输出摘要文本，不要加任何说明。"
    )
    user_prompt = f"对话内容：\n{text}\n\n请输出摘要："

    response = await llm.ainvoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
    )
    summary = response.content if isinstance(response.content, str) else str(response.content)
    # 截断到 max_tokens token（按真实 token 截断，避免硬截断破坏编码）
    summary = truncate_to_tokens(summary, max_tokens)
    _logger.info(
        "summary_done",
        original_chars=len(text),
        summary_chars=len(summary),
        max_tokens=max_tokens,
    )
    return summary


def should_compress_session(
    history_msgs: list,
    *,
    trigger_tokens: int | None = None,
    trigger_chars: int | None = None,
    keep_recent: int = 4,
) -> bool:
    """会话历史是否需要压缩（v2-M1：按真实 token 判定）。

    保留最近 `keep_recent` 条原始消息，其余进摘要。
    判定规则（两条都要满足）：
      1. `len(history_msgs) > keep_recent + 2`
      2. 历史总 token 数 > `trigger_tokens`

    兼容旧调用：`trigger_tokens` 缺省时回退到 chars（`trigger_chars`），
    旧 `SUMMARY_TRIGGER_CHARS=6000` 保持默认行为。
    """
    if len(history_msgs) <= keep_recent + 2:
        return False

    if trigger_tokens is not None:
        from app.agents.tokenizer import count_history_tokens

        return count_history_tokens(history_msgs) > trigger_tokens

    # 兼容旧路径
    chars_threshold = (
        trigger_chars if trigger_chars is not None else SUMMARY_TRIGGER_CHARS
    )
    total = sum(len(m.content) if isinstance(m.content, str) else 0 for m in history_msgs)
    return total > chars_threshold
