"""待办事项抽取 Skill。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.schemas import EmailInput, TodoExtractOutput
from app.agents.skills.base import Skill

SYSTEM_PROMPT = """你是 DeepMail 待办抽取助手。
从邮件中抽取"需要用户后续处理的事项"，输出 Todo 列表。
- 每条 todo 有 content（≤100 字）、due_date（YYYY-MM-DD；邮件中明确日期才填，否则 null）、priority（low/medium/high）。
- 如果邮件不包含任何待办，返回空列表 []。
- 不要把"已发生的事项"或"已知信息"误认为待办。"""


class TodoExtractSkill(Skill[EmailInput, TodoExtractOutput]):
    name = "todo_extract"
    input_schema = EmailInput
    output_schema = TodoExtractOutput

    def build_messages(self, inp: EmailInput):  # type: ignore[override]
        user = f"主题：{inp.subject}\n\n正文：\n{inp.body_text}"
        return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]
