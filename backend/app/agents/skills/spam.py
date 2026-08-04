"""垃圾邮件过滤 Skill。"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.schemas import EmailInput, SpamOutput
from app.agents.skills.base import Skill

SYSTEM_PROMPT = """你是 DeepMail 垃圾邮件检测助手。
评估邮件的 spam_score ∈ [0, 1]，并给出 is_spam（spam_score ≥ 0.8 视为垃圾）+ reasons（≤3 条短理由）。

考虑维度：
- 发件人域名可信度
- 是否含推广/营销/诱导点击话术
- 是否冒充官方/银行/快递
- 是否为一次性验证码（验证码 spam_score 应较低，约 0.05-0.15）
- 正文长度异常 / 全部大写 / 多链接

纯业务沟通 spam_score 应较低（≤ 0.2）。"""


class SpamSkill(Skill[EmailInput, SpamOutput]):
    name = "spam"
    input_schema = EmailInput
    output_schema = SpamOutput

    def build_messages(self, inp: EmailInput):  # type: ignore[override]
        sender = f"{inp.sender_name} <{inp.sender_email}>" if inp.sender_name else inp.sender_email
        user = f"发件人：{sender}\n主题：{inp.subject}\n\n正文：\n{inp.body_text}"
        return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]

    def parse_from_markdown(self, text: str) -> SpamOutput | None:
        """兜底：从 markdown 提取 score / 判定 / 理由。"""
        from app.agents.skills.base import _strip_think

        cleaned = _strip_think(text)
        # 抓 score
        score_match = re.search(r"评分[：:]\s*([0-9.]+)", cleaned)
        if score_match is None:
            score_match = re.search(r"spam_score[：:=]\s*([0-9.]+)", cleaned)
        score = float(score_match.group(1)) if score_match else 0.5
        score = max(0.0, min(1.0, score))

        # 抓判定
        is_spam = False
        if re.search(r"判定[：:]\s*是", cleaned) or "is_spam" in cleaned.lower():
            is_spam = True
        if score >= 0.8:
            is_spam = True

        # 抓 reasons
        reasons: list[str] = []
        reasons_match = re.search(r"理由[：:]\s*(.*?)(?:\n\n|\Z)", cleaned, re.DOTALL)
        if reasons_match:
            for line in reasons_match.group(1).splitlines():
                line = re.sub(r"^[\s\-\*\d\.]+", "", line).strip()
                if line:
                    reasons.append(line[:100])
        if not reasons:
            reasons = [cleaned[:100].strip()]

        return SpamOutput(spam_score=score, is_spam=is_spam, reasons=reasons[:3])
