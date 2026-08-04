"""Token 计数工具（v2-M1）。

- 单例 `tiktoken` 编码（`cl100k_base`），`@lru_cache` 避免重复加载
- `count_tokens(text)`：纯文本 token 数
- `count_message_tokens(msg)`：langchain `BaseMessage` 的真实 token 数
  （纳入 content + tool_calls + reasoning_details）
- `truncate_to_tokens(text, max_tokens)`：token 维度截断（按 token 数）

编码选择：`cl100k_base`（GPT-4 / GPT-3.5 通用 BPE），对中英文都能编码。
MiniMax-M3 是 MiniMax 自定义模型，无对应 tiktoken 映射，`cl100k_base` 是
误差最小的折中（与实际 token 数偏差约 ±10%）。
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from langchain_core.messages import BaseMessage


@lru_cache(maxsize=1)
def get_tokenizer():
    """单例 tiktoken 编码。

    `cl100k_base` 是 OpenAI GPT-4 / GPT-3.5 通用编码，对中英文都可编码。
    多个进程安全：tiktoken 内部是只读编码表。
    """
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """纯文本 token 数（空字符串返回 0）。"""
    if not text:
        return 0
    return len(get_tokenizer().encode(text))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """按 token 数截断文本。`max_tokens <= 0` 时返回空串。"""
    if not text or max_tokens <= 0:
        return ""
    enc = get_tokenizer()
    ids = enc.encode(text)
    if len(ids) <= max_tokens:
        return text
    return enc.decode(ids[:max_tokens])


def _stringify_extra(obj: Any) -> str:
    """把任意对象转为可编码字符串（用于 tool_calls / reasoning_details 计数）。"""
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, (dict, list)):
        try:
            return json.dumps(obj, ensure_ascii=False, default=str)
        except Exception:
            return str(obj)
    return str(obj)


def count_message_tokens(msg: BaseMessage) -> int:
    """单条 langchain 消息的真实 token 数。

    计数范围：
    - `content`（str 或 list）
    - `tool_calls`（AIMessage 通常有）
    - `reasoning_details`（MiniMax-M3 等模型写入 additional_kwargs）
    - 其它 `additional_kwargs` 字段（避免低估）

    非字符串 content（如 list[dict]）按 json 序列化后编码。
    """
    enc = get_tokenizer()

    # content
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        text_parts: list[str] = [content]
    elif isinstance(content, list):
        # 多模态 list[dict] 转 str
        try:
            text_parts = [json.dumps(content, ensure_ascii=False, default=str)]
        except Exception:
            text_parts = [str(content)]
    elif content is None:
        text_parts = []
    else:
        text_parts = [str(content)]

    # tool_calls
    tool_calls = getattr(msg, "tool_calls", None) or []
    if tool_calls:
        try:
            text_parts.append(json.dumps(tool_calls, ensure_ascii=False, default=str))
        except Exception:
            text_parts.append(str(tool_calls))

    # additional_kwargs（含 reasoning_details）
    additional = getattr(msg, "additional_kwargs", None) or {}
    if additional:
        text_parts.append(_stringify_extra(additional))

    total = 0
    for part in text_parts:
        if part:
            total += len(enc.encode(part))
    return total


def count_history_tokens(messages: list[BaseMessage]) -> int:
    """一批消息的总 token 数。"""
    return sum(count_message_tokens(m) for m in messages)


__all__ = [
    "get_tokenizer",
    "count_tokens",
    "count_message_tokens",
    "count_history_tokens",
    "truncate_to_tokens",
]
