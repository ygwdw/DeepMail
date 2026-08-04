"""L4 语义记忆：长期事实 / 用户画像 / 程序偏好。

存储：key-value JSONB（v1 混在一起；category 字段保留扩展）。
衰减：decay_score = importance * exp(-λ * days_since_update)
查询时过滤 decay_score > 阈值。
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.memory import MemoryLongTerm

_logger = get_logger(__name__)

# 默认衰减常数（λ）；越大衰减越快
DEFAULT_DECAY_LAMBDA = 0.01

# 查询时过滤的最小 decay_score
DEFAULT_MIN_DECAY = 0.1


def compute_decay_score(
    importance: float, days_since_update: float, lam: float = DEFAULT_DECAY_LAMBDA
) -> float:
    """指数衰减：decay = importance * exp(-λ * days)"""
    if importance <= 0:
        return 0.0
    return importance * math.exp(-lam * days_since_update)


def _days_since(dt: datetime) -> float:
    now = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return max(0.0, (now - dt).total_seconds() / 86400.0)


# ---------- CRUD ----------


async def upsert_long_term(
    db: AsyncSession,
    user_id: uuid.UUID,
    key: str,
    value: dict[str, Any],
    *,
    importance: float = 0.5,
    category: str = "misc",
) -> MemoryLongTerm:
    """upsert：同 user + key 已存在则更新 value / importance / category。"""
    stmt = select(MemoryLongTerm).where(
        MemoryLongTerm.user_id == user_id, MemoryLongTerm.key == key
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    now = datetime.now(UTC)
    if row is None:
        row = MemoryLongTerm(
            user_id=user_id,
            key=key,
            value=value,
            importance=importance,
            category=category,
            decay_score=importance,
            updated_at=now,
        )
        db.add(row)
    else:
        row.value = value
        row.importance = importance
        row.category = category
        row.decay_score = importance
        row.updated_at = now
    await db.commit()
    await db.refresh(row)
    _logger.info(
        "long_term_upsert",
        user=str(user_id),
        key=key,
        category=category,
        importance=importance,
    )
    return row


async def list_long_term(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    category: str | None = None,
    min_decay: float = DEFAULT_MIN_DECAY,
    limit: int = 50,
) -> list[MemoryLongTerm]:
    """列出长期记忆（按当前衰减分过滤）。"""
    stmt = (
        select(MemoryLongTerm)
        .where(
            MemoryLongTerm.user_id == user_id,
            MemoryLongTerm.decay_score >= min_decay,
        )
        .order_by(MemoryLongTerm.decay_score.desc())
        .limit(limit)
    )
    if category:
        stmt = stmt.where(MemoryLongTerm.category == category)
    rows = list((await db.execute(stmt)).scalars().all())
    return rows


async def delete_long_term(db: AsyncSession, user_id: uuid.UUID, key: str) -> bool:
    stmt = select(MemoryLongTerm).where(
        MemoryLongTerm.user_id == user_id, MemoryLongTerm.key == key
    )
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


# ---------- 衰减任务 ----------


async def run_decay_update(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    lam: float = DEFAULT_DECAY_LAMBDA,
) -> int:
    """把该用户所有 memory_long_term 的 decay_score 更新为当前衰减分。"""
    stmt = select(MemoryLongTerm).where(MemoryLongTerm.user_id == user_id)
    rows = list((await db.execute(stmt)).scalars().all())
    n = 0
    for row in rows:
        days = _days_since(row.updated_at)
        row.decay_score = round(compute_decay_score(row.importance, days, lam), 4)
        n += 1
    await db.commit()
    _logger.info("decay_updated", user=str(user_id), count=n)
    return n


async def run_global_decay_update(db: AsyncSession, *, lam: float = DEFAULT_DECAY_LAMBDA) -> int:
    """管理员：所有用户的衰减刷新。"""
    stmt = select(MemoryLongTerm)
    rows = list((await db.execute(stmt)).scalars().all())
    for row in rows:
        days = _days_since(row.updated_at)
        row.decay_score = round(compute_decay_score(row.importance, days, lam), 4)
    await db.commit()
    _logger.info("decay_global_updated", count=len(rows))
    return len(rows)


# ---------- 自动提炼（从对话） ----------


async def extract_long_term_from_conversation(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_msg: str,
    ai_msg: str,
) -> int:
    """用 LLM 提炼用户偏好/事实，写入 memory_long_term。

    MVP：mock 模式或 LLM 失败时不写入。
    """
    import json as _json
    import re

    from app.llm.factory import get_chat_model, is_mock_mode
    from app.memory.time_context import inject_time_to_prompt

    if is_mock_mode():
        return 0

    system_prompt = """你是用户偏好与事实提炼助手。从一段对话中抽取值得长期记住的用户偏好或事实。

规则：
- 只抽取：用户明确表达的偏好（如："我习惯..."、"我不喜欢..."）、事实（如："我是XX"、"我在YY公司"）
- 不抽取：临时性内容（"今天有空吗"）
- 每条 ≤ 30 字

返回严格 JSON 数组（不加说明文字）：
[{"key": "user_role", "value": "产品经理", "importance": 0.7, "category": "profile"}, ...]"""

    user_prompt = f"""用户：{user_msg[:300]}

助手：{ai_msg[:300]}

请立即输出 JSON 数组："""

    try:
        llm = await get_chat_model(db=None, user_id=None)
        msg = [
            {"role": "system", "content": inject_time_to_prompt(system_prompt)},
            {"role": "user", "content": user_prompt},
        ]
        response = await llm.ainvoke(msg)
        text = response.content if isinstance(response.content, str) else str(response.content)
        text = re.sub(r"```(?:json)?\s*\n?(.*?)\n?```", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"```(?:json)?\s*", "", text).strip()
        start = text.find("[")
        end = text.rfind("]")
        if start == -1 or end <= start:
            return 0
        items = _json.loads(text[start : end + 1])
    except Exception as exc:
        _logger.warning("long_term_extract_fail", error=str(exc))
        return 0

    count = 0
    for it in items:
        key = it.get("key")
        value = it.get("value")
        if not key or value is None:
            continue
        if isinstance(value, str):
            value = {"text": value}
        await upsert_long_term(
            db,
            user_id,
            key=key,
            value=value,
            importance=float(it.get("importance", 0.5)),
            category=it.get("category", "misc"),
        )
        count += 1
    _logger.info("long_term_extracted", user=str(user_id), count=count)
    return count
