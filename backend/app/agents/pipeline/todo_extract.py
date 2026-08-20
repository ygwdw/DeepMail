"""待办事项抽取 Agent（PipelineAgent）。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.schemas import EmailInput, TodoExtractOutput
from app.agents.pipeline.base import PipelineAgent

SYSTEM_PROMPT = """你是 DeepMail 待办抽取助手。从邮件中抽取"用户需要后续处理或准备的事项"，输出 Todo 列表。

提取原则（激进抽取）：
- 凡是邮件中**要求用户做某事**（"请准备好..."/"请提前..."/"请提交..."）→ 必提取
- 凡是邮件中**通知用户出席/参加会议/活动**（"面谈"/"会议"/"培训"/"deadline"）→ 必提取
- 凡是邮件中**要求确认/回复/反馈**（"请确认"/"如有疑问回复"）→ 必提取
- 凡是邮件中**截止日期相关**（合同签署、付款、提交报告）→ 必提取
- 每条 todo 有 content（≤100 字）、due_date（YYYY-MM-DD；邮件中明确日期才填，否则 null）、priority（low/medium/high）
- 如果邮件**确实**只是纯通知/广告/聊天，无任何需要行动的事项 → 才返回空 []
- 不要把"已发生的事项"或"已知信息"误认为待办
- 默认应当提取至少 1 条，除非完全确认邮件无任务

输出格式：纯 JSON 数组 [{{"content": "...", "due_date": "YYYY-MM-DD" or null, "priority": "low/medium/high"}}, ...]"""


class TodoExtractAgent(PipelineAgent[EmailInput, TodoExtractOutput]):
    name = "todo_extract"
    input_schema = EmailInput
    output_schema = TodoExtractOutput

    def build_messages(self, inp: EmailInput):  # type: ignore[override]
        user = f"主题：{inp.subject}\n\n正文：\n{inp.body_text}"
        return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]
