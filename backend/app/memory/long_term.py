"""L4 语义记忆：长期事实 / 用户画像 / 实体关系。

存储：key-value JSONB，按 category 字段区分：
- "persona": 用户画像（姓名、职业、偏好），自动注入主 agent + draft agent
- "entity_relation": 实体关系（如"张小龙是朋友"、"李红是 A 公司 HR"），只可查询不注入
- "misc": 其他事实，保留扩展

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

# v2-M4.2: L4 category 常量
CATEGORY_PERSONA = "persona"
CATEGORY_ENTITY_RELATION = "entity_relation"
CATEGORY_MISC = "misc"

VALID_CATEGORIES = {CATEGORY_PERSONA, CATEGORY_ENTITY_RELATION, CATEGORY_MISC}


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
    category: str = CATEGORY_MISC,
) -> MemoryLongTerm:
    """upsert：同 user + key 已存在则更新 value / importance / category。"""
    if category not in VALID_CATEGORIES:
        _logger.warning("invalid_category", category=category, fallback=CATEGORY_MISC)
        category = CATEGORY_MISC

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


# v2-M4.2: L4 分类查询入口

async def search_personas(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    min_decay: float = DEFAULT_MIN_DECAY,
    limit: int = 20,
) -> list[MemoryLongTerm]:
    """v2-M4.2: 查询用户画像（category=persona），供主 agent / draft agent 自动注入。"""
    return await list_long_term(
        db,
        user_id,
        category=CATEGORY_PERSONA,
        min_decay=min_decay,
        limit=limit,
    )


async def search_relations(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    subject: str | None = None,
    predicate: str | None = None,
    object: str | None = None,
    min_decay: float = DEFAULT_MIN_DECAY,
    limit: int = 50,
) -> list[MemoryLongTerm]:
    """v2-M4.2: 查询实体关系（category=entity_relation），按 key=value 元数据过滤。

    注意：实体关系存于 key='person_relation_<subject>' 字段，value 含 predicate/object 元数据。
    """
    rows = await list_long_term(
        db,
        user_id,
        category=CATEGORY_ENTITY_RELATION,
        min_decay=min_decay,
        limit=limit,
    )
    out: list[MemoryLongTerm] = []
    for r in rows:
        if subject is not None and r.value.get("subject") != subject:
            continue
        if predicate is not None and r.value.get("predicate") != predicate:
            continue
        if object is not None and r.value.get("object") != object:
            continue
        out.append(r)
    return out


def personas_to_prompt_block(rows: list[MemoryLongTerm]) -> str:
    """v2-M4.2: 把用户画像列表拼成可注入 system prompt 的 block。"""
    if not rows:
        return ""
    lines = ["## 用户画像（自动注入；M4.2 新增）"]
    for r in rows:
        text = r.value.get("text") if isinstance(r.value, dict) else str(r.value)
        lines.append(f"- {r.key}: {text}（重要性 {r.importance:.2f}）")
    return "\n".join(lines)


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
    """用 LLM 提炼用户偏好/事实/实体关系，写入 memory_long_term。

    v2-M4.2: 输出按 category 分类
    - persona: 用户画像（姓名/职业/偏好）
    - entity_relation: 实体关系（人-公司-职位 等三元组）
    - misc: 其他事实
    """
    import json as _json
    import re

    from app.llm.factory import get_chat_model, is_mock_mode
    from app.memory.time_context import inject_time_to_prompt

    if is_mock_mode():
        return 0

    system_prompt = """你是用户偏好与事实提炼助手。从一段对话中抽取值得长期记住的内容。

输出 3 类（按 category 字段区分）：
1. persona（用户画像）：用户自身的事实（姓名、职业、年龄、偏好、习惯）
   例：{"key":"user_name","value":{"text":"陈经理"},"importance":0.9,"category":"persona"}
2. entity_relation（实体关系）：用户提到的实体间关系（人物-公司-职位 等）
   例：{"key":"rel_zhang_xiaolong","value":{"subject":"张小龙","predicate":"是朋友","object":"我"},"importance":0.6,"category":"entity_relation"}
3. misc（其他事实）：不重要但有用的事实

规则：
- 只抽取：用户明确表达的内容；每条 ≤ 30 字
- 不抽取：临时性内容（"今天有空吗"）
- 返回严格 JSON 数组（不加任何说明文字）
[{"key":"...","value":{...},"importance":0.5,"category":"persona|entity_relation|misc"}, ...]"""

    user_prompt = f"""用户：{user_msg[:500]}

助手：{ai_msg[:500]}

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
        category = it.get("category", CATEGORY_MISC)
        await upsert_long_term(
            db,
            user_id,
            key=key,
            value=value,
            importance=float(it.get("importance", 0.5)),
            category=category,
        )
        count += 1
    _logger.info("long_term_extracted", user=str(user_id), count=count)
    return count


# v2-M4.2: 写入实体关系的便捷函数（供外部直接调用，例如工具/前端 API）

async def upsert_entity_relation(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    subject: str,
    predicate: str,
    object: str,
    importance: float = 0.6,
) -> MemoryLongTerm:
    """v2-M4.2: 写入或更新一条实体关系（key 自动生成）。"""
    key = f"rel_{subject}_{predicate}_{object}"
    value = {"subject": subject, "predicate": predicate, "object": object}
    return await upsert_long_term(
        db,
        user_id,
        key=key,
        value=value,
        importance=importance,
        category=CATEGORY_ENTITY_RELATION,
    )


async def upsert_persona(
    db: AsyncSession,
    user_id: uuid.UUID,
    key: str,
    text: str,
    *,
    importance: float = 0.7,
) -> MemoryLongTerm:
    """v2-M4.2: 写入或更新一条用户画像（key 必填，text 是画像描述）。"""
    return await upsert_long_term(
        db,
        user_id,
        key=key,
        value={"text": text},
        importance=importance,
        category=CATEGORY_PERSONA,
    )
