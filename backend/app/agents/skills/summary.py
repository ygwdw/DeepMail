"""邮件摘要 Skill。"""

from __future__ import annotations

import re

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.schemas import EmailInput, SummaryOutput
from app.agents.skills.base import Skill

SYSTEM_PROMPT = """你是 DeepMail 邮件摘要助手。
阅读用户给出的邮件，输出 1-3 句话的中文摘要，并列出 3-5 个关键点（每点一行、不超过 20 字）。
如果邮件是验证码、广告、无意义内容，summary 可以只写一句"验证码邮件"/"广告邮件"等。"""


class SummarySkill(Skill[EmailInput, SummaryOutput]):
    name = "summary"
    input_schema = EmailInput
    output_schema = SummaryOutput

    def build_messages(self, inp: EmailInput):  # type: ignore[override]
        user = f"主题：{inp.subject}\n\n正文：\n{inp.body_text}"
        return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]

    def parse_from_markdown(self, text: str) -> SummaryOutput | None:
        """兜底：解析 `**摘要：**` + `**关键点：**` 格式。"""
        from app.agents.skills.base import _strip_think

        cleaned = _strip_think(text)
        # 找 summary 段
        summary_match = re.search(
            r"\*\*摘要[：:]\*\*\s*(.*?)(?=\*\*关键点[：:]\*\*|\Z)",
            cleaned,
            re.DOTALL,
        )
        if summary_match is None:
            summary_match = re.search(
                r"(?:^|\n)#+\s*摘要[：:]\s*(.*?)(?=\n#+\s*关键点|\Z)",
                cleaned,
                re.DOTALL,
            )
        if summary_match is None:
            return None
        summary = summary_match.group(1).strip()

        # 找 key_points 段
        kp_match = re.search(
            r"\*\*关键点[：:]\*\*\s*(.*?)(?:\Z|---|\n\*\*\s)",
            cleaned,
            re.DOTALL,
        )
        key_points: list[str] = []
        if kp_match:
            for line in kp_match.group(1).splitlines():
                line = re.sub(r"^[\s\-\*\d\.]+", "", line).strip()
                if line:
                    key_points.append(line[:100])

        if not summary:
            return None
        return SummaryOutput(summary=summary, key_points=key_points[:5])
