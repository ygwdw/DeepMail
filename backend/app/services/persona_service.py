"""人格画像（persona）服务：CRUD + 主动更新 + 注入。

profile_json 字段（v1，10 字段）：
- name                姓名
- age                 年龄
- education           学历
- profession          职业
- personality         性格标签（list）
- communication_style 沟通风格
- language_pref       语言偏好
- signature           邮件签名
- frequent_topics     经常话题（list）
- sample_phrases      高频用词（list）
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.persona import Persona
from app.memory.time_context import inject_time_to_prompt

_logger = get_logger(__name__)


# profile_json 完整 schema（给 LLM 看的"标准"）
PROFILE_KEYS = [
    "name",
    "age",
    "education",
    "profession",
    "personality",
    "communication_style",
    "language_pref",
    "signature",
    "frequent_topics",
    "sample_phrases",
]

PROFILE_SCHEMA_DESC = """
- name:                str | null         # 姓名（中文/英文皆可）
- age:                 int | null         # 年龄，18-100
- education:           str | null         # 学历，如 "本科-计算机科学"、"硕士-金融"
- profession:          str | null         # 职业，如 "产品经理"、"律师"、"软件工程师"
- personality:         list[str]          # 性格标签（1-5 个），如 ["直白", "严谨", "幽默"]
- communication_style: str | null         # 沟通风格，如 "简洁正式"、"详细随意"
- language_pref:       str | null         # 语言偏好，如 "中文"、"英文"、"中英混"
- signature:           str | null         # 邮件签名/落款（3-50 字）
- frequent_topics:     list[str]          # 经常涉及的话题（最多 10 个）
- sample_phrases:      list[str]          # 高频短语/口头禅（最多 10 个）
"""


async def get_or_create_persona(db: AsyncSession, user_id: uuid.UUID) -> Persona:
    stmt = select(Persona).where(Persona.user_id == user_id)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        row = Persona(
            user_id=user_id,
            profile_json={},
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


async def update_persona_fields(
    db: AsyncSession,
    user_id: uuid.UUID,
    fields: dict[str, Any],
    *,
    reason: str = "",
) -> Persona:
    """合并更新 profile_json。返回更新后的 Persona。"""
    persona = await get_or_create_persona(db, user_id)
    before = dict(persona.profile_json or {})
    merged = {**before, **{k: v for k, v in fields.items() if k in PROFILE_KEYS}}
    persona.profile_json = merged
    persona.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(persona)
    _logger.info(
        "persona_updated",
        user=str(user_id),
        changed_fields=list(fields.keys()),
        reason=reason[:80],
    )
    return persona


async def rollback_persona(db: AsyncSession, user_id: uuid.UUID) -> Persona | None:
    """回滚到上一版本：需要 persona_history 表（v1 暂未实现，调用方应自己保留备份）。

    实际策略：v1 不存历史，"回滚" = 清空 profile_json。
    """
    persona = await get_or_create_persona(db, user_id)
    persona.profile_json = {}
    persona.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(persona)
    return persona


def persona_to_prompt_block(profile_json: dict | None) -> str:
    """把 persona 转成可注入 LLM 的 prompt 文本块。空 persona 返回空字符串。"""
    if not profile_json:
        return ""
    lines = ["[用户人格画像]"]
    for key in PROFILE_KEYS:
        v = profile_json.get(key)
        if v is None or v == "" or v == []:
            continue
        if isinstance(v, list):
            v = "、".join(str(x) for x in v)
        lines.append(f"- {key}: {v}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


# ---------- LLM 主动决策 agent ----------

PERSONA_EXTRACTOR_PROMPT = (
    """你是 DeepMail 的【人格画像提炼助手】。判断当前这段对话是否包含值得沉淀到用户人格画像的信息。

可用字段：
"""
    + PROFILE_SCHEMA_DESC
    + """

判断规则：
- 只在用户**明确透露**个人信息时建议更新（"我是XX"、"我今年XX岁"、"我是YY大学毕业"等）
- 用户临时性内容（"今天有空吗"、"帮我查一下"）→ should_update=false
- 推断性内容（"你可能喜欢..."）→ should_update=false
- 已有画像不重复更新（除非用户明确改了）
- 一次最多更新 3 个字段

返回严格 JSON：
{
  "should_update": true/false,
  "fields": {"name": "...", "profession": "...", ...},  // 只包含要更新的字段
  "reason": "更新理由（< 50 字）"
}

当前画像：
{CURRENT_PERSONA}

用户消息：{USER_MSG}

助手回复：{AI_MSG}

请立即输出 JSON："""
)


async def maybe_update_persona(
    db: AsyncSession,
    user_id: uuid.UUID,
    user_msg: str,
    ai_msg: str,
) -> dict | None:
    """LLM 自主决策：是否更新 persona。

    返回 LLM 的决策 dict（含 should_update / fields / reason）；
    如果 should_update=True，persona 已写入。
    失败时返回 None（不阻塞主流程）。
    """
    import json as _json
    import re

    from app.llm.factory import get_chat_model, is_mock_mode

    if is_mock_mode():
        return None

    persona = await get_or_create_persona(db, user_id)
    current_str = persona_to_prompt_block(persona.profile_json) or "（空）"

    system_prompt = (
        PERSONA_EXTRACTOR_PROMPT.replace("{CURRENT_PERSONA}", current_str)
        .replace("{USER_MSG}", user_msg[:500])
        .replace("{AI_MSG}", ai_msg[:500])
    )

    try:
        llm = await get_chat_model(db=None, user_id=None)
        msg = [
            {"role": "system", "content": inject_time_to_prompt(system_prompt)},
            {"role": "user", "content": "请立即输出 JSON。"},
        ]
        response = await llm.ainvoke(msg)
        text = response.content if isinstance(response.content, str) else str(response.content)
        # 提取 JSON
        text = re.sub(r"```(?:json)?\s*\n?(.*?)\n?```", r"\1", text, flags=re.DOTALL)
        text = re.sub(r"```(?:json)?\s*", "", text).strip()
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end <= start:
            return None
        decision = _json.loads(text[start : end + 1])
    except Exception as exc:
        _logger.warning("persona_extract_llm_fail", error=str(exc))
        return None

    if decision.get("should_update") and decision.get("fields"):
        # 过滤非法字段
        fields = {
            k: v for k, v in decision["fields"].items() if k in PROFILE_KEYS and v is not None
        }
        if fields:
            await update_persona_fields(db, user_id, fields, reason=decision.get("reason", ""))
    return decision
