"""打标推荐 Skill（推荐 + 用户确认，不直接写库）。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.schemas import TagInput, TagRecommendOutput
from app.agents.skills.base import Skill

SYSTEM_PROMPT = """你是 DeepMail 邮件打标助手。
对当前邮件推荐标签（不直接落库，前端展示后用户确认才写入）。

分两部分：
1. existing_label_matches：从"用户已有标签"中找出语义相关的，附 confidence ∈ [0,1]。
2. recommended_new_labels：建议**新创建**的标签（type ∈ topic/action/entity，附 reason）。

原则：
- 邮件不一定非要有标签；如果现有标签都不合适，existing_label_matches 与 recommended_new_labels 都可为空。
- 现有标签匹配阈值 confidence ≥ 0.6 才列出。
- 建议新标签最多 3 个；只在邮件主题或话题明显超出已有标签范围时建议。"""


class TagRecommendSkill(Skill[TagInput, TagRecommendOutput]):
    name = "tag_recommend"
    input_schema = TagInput
    output_schema = TagRecommendOutput

    def build_messages(self, inp: TagInput):  # type: ignore[override]
        if inp.existing_labels:
            label_lines = []
            for lb in inp.existing_labels:
                label_lines.append(
                    f"- {lb.name}（{lb.description}）" if lb.description else f"- {lb.name}"
                )
            existing = "\n".join(label_lines)
        else:
            existing = "（暂无标签）"
        user = f"用户已有标签：\n{existing}\n\n主题：{inp.subject}\n\n正文：\n{inp.body_text}"
        return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]
