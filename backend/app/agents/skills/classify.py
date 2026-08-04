"""邮件分类 Skill。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.schemas import ClassifyInput, ClassifyOutput
from app.agents.skills.base import Skill

SYSTEM_PROMPT = """你是 DeepMail 邮件分类助手。
从给定的 categories 列表中选一个最匹配的 category_name，并给出 confidence ∈ [0, 1]。

优先参考每条分类的 rules_json.keywords（如果有），如：
- "验证码" → 一次性验证码
- "促销/折扣/订阅" → 广告推销
- "投诉/辱骂/诈骗" → 有害信息
- 都不匹配 → 常规

只输出一个分类，不要解释。"""


class ClassifySkill(Skill[ClassifyInput, ClassifyOutput]):
    name = "classify"
    input_schema = ClassifyInput
    output_schema = ClassifyOutput

    def build_messages(self, inp: ClassifyInput):  # type: ignore[override]
        cat_lines = []
        for c in inp.categories:
            kws = (c.rules_json or {}).get("keywords", [])
            kw_part = f", keywords={kws}" if kws else ""
            desc_part = f" — {c.description}" if c.description else ""
            cat_lines.append(
                f"- {c.name}{desc_part} (system={c.is_system}, spam_cat={c.is_spam_category}{kw_part})"
            )
        cat_block = "\n".join(cat_lines) or "（无候选分类，默认常规）"

        user = (
            f"候选分类：\n{cat_block}\n\n"
            f"发件人：{inp.sender_email}\n主题：{inp.subject}\n\n正文：\n{inp.body_text}"
        )
        return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]
