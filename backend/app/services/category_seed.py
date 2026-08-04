"""默认分类种子：注册新用户时自动创建 4 个默认分类。"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.label import Category

DEFAULT_CATEGORIES: list[dict] = [
    {
        "name": "常规",
        "description": "工作沟通、个人私事、信息通知等日常邮件",
        "is_system": True,
        "is_spam_category": False,
        "rules_json": {},
    },
    {
        "name": "一次性验证码",
        "description": "登录、注册、找回密码等一次性验证码邮件（多为自动发送）",
        "is_system": True,
        "is_spam_category": False,
        "rules_json": {"keywords": ["验证码", "code", "verification"]},
    },
    {
        "name": "广告推销",
        "description": "营销活动、折扣促销、订阅推送、品牌宣传等商业推广邮件",
        "is_system": True,
        "is_spam_category": True,
        "rules_json": {"keywords": ["促销", "折扣", "订阅", "限时", "首发"]},
    },
    {
        "name": "有害信息",
        "description": "钓鱼、诈骗、辱骂、虚假中奖等需要警惕的邮件",
        "is_system": True,
        "is_spam_category": True,
        "rules_json": {"keywords": ["钓鱼", "诈骗", "中奖"]},
    },
]


async def seed_default_categories(db: AsyncSession, user_id: uuid.UUID) -> int:
    """为新用户创建 4 个默认分类。返回新增数量。"""
    added = 0
    for cfg in DEFAULT_CATEGORIES:
        db.add(
            Category(
                user_id=user_id,
                name=cfg["name"],
                description=cfg["description"],
                rules_json=cfg["rules_json"],
                is_system=cfg["is_system"],
                is_spam_category=cfg["is_spam_category"],
            )
        )
        added += 1
    if added:
        await db.commit()
    return added
