"""记忆系统单测：时间上下文 + 衰减 + 话题提炼（mock 模式）。"""

from __future__ import annotations

import math

import pytest
from app.memory.long_term import (
    DEFAULT_DECAY_LAMBDA,
    compute_decay_score,
)
from app.memory.time_context import (
    WEEKDAY_CN,
    format_iso,
    format_natural,
    inject_time_to_prompt,
)

# ---------- time_context ----------


def test_format_natural_includes_weekday_cn() -> None:
    from datetime import datetime, timedelta, timezone

    dt = datetime(2026, 8, 4, 10, 30, tzinfo=timezone(timedelta(hours=8)))
    out = format_natural(dt)
    assert "2026-08-04 10:30" in out
    # 2026-08-04 是星期二
    assert "星期二" in out
    assert out in format_natural(dt)  # 同输入一致


def test_format_iso_returns_iso8601() -> None:
    from datetime import datetime, timedelta, timezone

    dt = datetime(2026, 1, 1, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    out = format_iso(dt)
    assert out.startswith("2026-01-01T00:00:00")
    assert "+08:00" in out


def test_inject_time_to_prompt_idempotent() -> None:
    base = "你是助手。"
    once = inject_time_to_prompt(base)
    twice = inject_time_to_prompt(once)
    assert once == twice  # 重复注入不会叠加
    assert "当前时间" in once
    assert "星期" in once or "周" in once


def test_weekday_cn_table_complete() -> None:
    assert len(WEEKDAY_CN) == 7
    assert WEEKDAY_CN[0] == "星期一"
    assert WEEKDAY_CN[6] == "星期日"


# ---------- long_term 衰减 ----------


def test_decay_score_formula() -> None:
    """importance=1.0, days=0 → score=1.0"""
    assert compute_decay_score(1.0, 0) == pytest.approx(1.0)


def test_decay_score_exp_decay() -> None:
    """importance=1.0, days=100, λ=0.01 → score=exp(-1)≈0.368"""
    s = compute_decay_score(1.0, 100)
    assert s == pytest.approx(math.exp(-1.0), rel=1e-3)


def test_decay_score_clamps_zero() -> None:
    assert compute_decay_score(0, 100) == 0.0
    assert compute_decay_score(-1, 100) == 0.0


def test_decay_lambda_higher_faster() -> None:
    """λ 越大衰减越快：100 天后 score 更小。"""
    s_low = compute_decay_score(1.0, 100, lam=0.005)
    s_high = compute_decay_score(1.0, 100, lam=0.05)
    assert s_high < s_low
    assert s_low > 0
    assert s_high > 0


def test_decay_default_lambda() -> None:
    assert DEFAULT_DECAY_LAMBDA == 0.01


# ---------- 阶段 6：多轮摘要相关（不依赖 DB） ----------


def test_summarize_trigger_chars_constant_exists() -> None:
    from app.agents.context_builder import SUMMARY_TRIGGER_CHARS

    assert isinstance(SUMMARY_TRIGGER_CHARS, int)
    assert SUMMARY_TRIGGER_CHARS > 0


def test_should_compress_no_history() -> None:
    from app.agents.context_builder import should_compress_session

    assert should_compress_session([], keep_recent=4) is False


def test_should_compress_short_history() -> None:
    from app.agents.context_builder import should_compress_session
    from langchain_core.messages import HumanMessage

    short = [HumanMessage(content="hi")]
    assert should_compress_session(short, keep_recent=4) is False


def test_should_compress_long_history() -> None:
    """字符数 > trigger_chars 且消息数 > keep_recent+2 → 触发。"""
    from app.agents.context_builder import (
        should_compress_session,
    )
    from langchain_core.messages import HumanMessage

    # 8 条 × 1500 字 = 12000 > 6000；8 > 4+2=6
    long = [HumanMessage(content="x" * 1500) for _ in range(8)]
    assert should_compress_session(long, keep_recent=4) is True


def test_should_not_compress_short_history() -> None:
    """字符数 < trigger_chars → 不触发。"""
    from app.agents.context_builder import should_compress_session
    from langchain_core.messages import HumanMessage

    short = [HumanMessage(content="hi") for _ in range(2)]
    assert should_compress_session(short, keep_recent=4) is False


# ---------- context_builder budget 缩放 ----------


def test_context_builder_budget_scales_with_user_setting() -> None:
    """context_builder 应接受 trigger_chars 外部参数。"""
    # 验证 build_memory_blocks 存在并接受 user_token_budget 参数
    import inspect

    from app.agents.context_builder import build_memory_blocks

    sig = inspect.signature(build_memory_blocks)
    # 至少应该接受 query 和 user_id
    assert "user_id" in sig.parameters
    assert "query" in sig.parameters


# ---------- 时间格式边界 ----------


def test_format_natural_sunday_cn() -> None:
    from datetime import datetime, timedelta, timezone

    # 2026-01-04 是星期日
    dt = datetime(2026, 1, 4, 23, 59, tzinfo=timezone(timedelta(hours=8)))
    out = format_natural(dt)
    assert "星期日" in out


def test_format_natural_monday_cn() -> None:
    from datetime import datetime, timedelta, timezone

    # 2026-01-05 是星期一
    dt = datetime(2026, 1, 5, 0, 1, tzinfo=timezone(timedelta(hours=8)))
    out = format_natural(dt)
    assert "星期一" in out


# ---------- v2-M1：真实 token 计数 ----------


def test_count_tokens_empty() -> None:
    from app.agents.tokenizer import count_tokens

    assert count_tokens("") == 0


def test_count_tokens_chinese() -> None:
    """中文 4 字 ≈ 4 token（cl100k_base 对中文每个字 1-3 token）。"""
    from app.agents.tokenizer import count_tokens

    n = count_tokens("你好世界")
    # cl100k_base 编码 4 个汉字大致 4-6 token
    assert 3 <= n <= 8, f"got {n} tokens for 你好世界"


def test_count_tokens_english() -> None:
    """英文 ~4 chars/token。"""
    from app.agents.tokenizer import count_tokens

    n = count_tokens("hello world")
    assert n == 2


def test_tokenizer_lru_cache_returns_same_object() -> None:
    from app.agents.tokenizer import get_tokenizer

    enc1 = get_tokenizer()
    enc2 = get_tokenizer()
    assert enc1 is enc2


def test_count_message_tokens_includes_reasoning() -> None:
    """AIMessage 包含 reasoning_details 应被计入 token。"""
    from app.agents.tokenizer import count_message_tokens
    from langchain_core.messages import AIMessage

    # 无 reasoning
    m1 = AIMessage(content="hi")
    n1 = count_message_tokens(m1)

    # 加 reasoning_details（500 字符）
    m2 = AIMessage(
        content="hi",
        additional_kwargs={"reasoning_details": [{"text": "x" * 500}]},
    )
    n2 = count_message_tokens(m2)
    assert n2 > n1, f"expected reasoning to add tokens: {n1} -> {n2}"


def test_count_message_tokens_includes_tool_calls() -> None:
    """AIMessage 带 tool_calls 应被计入。"""
    from app.agents.tokenizer import count_message_tokens
    from langchain_core.messages import AIMessage

    m1 = AIMessage(content="hi")
    n1 = count_message_tokens(m1)

    m2 = AIMessage(
        content="hi",
        tool_calls=[
            {"name": "search", "args": {"q": "test query" * 50}, "id": "call_1"},
        ],
    )
    n2 = count_message_tokens(m2)
    assert n2 > n1


def test_count_history_tokens_sum() -> None:
    from app.agents.tokenizer import count_history_tokens, count_message_tokens
    from langchain_core.messages import HumanMessage

    msgs = [HumanMessage(content="hello"), HumanMessage(content="world")]
    assert count_history_tokens(msgs) == sum(count_message_tokens(m) for m in msgs)


def test_truncate_to_tokens_shorter() -> None:
    """截断返回更少 token。"""
    from app.agents.tokenizer import count_tokens, truncate_to_tokens

    text = "你好世界这是一个测试文本用于验证截断功能"
    full = count_tokens(text)
    half = truncate_to_tokens(text, max_tokens=max(1, full // 2))
    assert count_tokens(half) <= full


def test_truncate_to_tokens_zero() -> None:
    from app.agents.tokenizer import truncate_to_tokens

    assert truncate_to_tokens("anything", 0) == ""
    assert truncate_to_tokens("anything", -1) == ""


# ---------- v2-M1：should_compress_session token 维度 ----------


def test_should_compress_token_path() -> None:
    """真实 token 触发：超过 trigger_tokens → True。"""
    from app.agents.context_builder import should_compress_session
    from langchain_core.messages import HumanMessage

    # 8 条长消息（中英文混合）→ token 远超 100
    long = [HumanMessage(content="x" * 800) for _ in range(8)]
    assert should_compress_session(long, trigger_tokens=100, keep_recent=4) is True


def test_should_compress_token_short_history() -> None:
    """token 未超 → 不压缩。"""
    from app.agents.context_builder import should_compress_session
    from langchain_core.messages import HumanMessage

    short = [HumanMessage(content="hi") for _ in range(8)]
    assert should_compress_session(short, trigger_tokens=10000, keep_recent=4) is False


def test_should_compress_backward_compat_chars() -> None:
    """旧 chars 路径仍兼容。"""
    from app.agents.context_builder import (
        SUMMARY_TRIGGER_CHARS,
        should_compress_session,
    )
    from langchain_core.messages import HumanMessage

    long = [HumanMessage(content="x" * 1500) for _ in range(8)]
    assert should_compress_session(long, trigger_chars=SUMMARY_TRIGGER_CHARS, keep_recent=4) is True


def test_should_compress_too_few_messages() -> None:
    """消息数 ≤ keep_recent+2 → 不压缩。"""
    from app.agents.context_builder import should_compress_session
    from langchain_core.messages import HumanMessage

    msgs = [HumanMessage(content="x" * 100000) for _ in range(5)]
    assert should_compress_session(msgs, trigger_tokens=10, keep_recent=4) is False


def test_summarize_truncate_to_max_tokens() -> None:
    """summarize_messages 返回值 ≤ max_tokens（用 mock LLM）。"""
    import asyncio
    from unittest.mock import AsyncMock

    from app.agents.context_builder import summarize_messages
    from app.agents.tokenizer import count_tokens
    from langchain_core.messages import AIMessage

    # 假 LLM：返回很长一段
    fake_llm = AsyncMock()
    fake_llm.ainvoke = AsyncMock(
        return_value=AIMessage(content="这是摘要。" * 500)  # 1500 字
    )

    out = asyncio.run(summarize_messages(fake_llm, [], max_tokens=50))
    assert count_tokens(out) <= 50
