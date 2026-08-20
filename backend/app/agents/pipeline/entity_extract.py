"""实体关系抽取 Agent（PipelineAgent）。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.schemas import EmailInput, EntityExtractOutput
from app.agents.pipeline.base import PipelineAgent

SYSTEM_PROMPT = """你是 DeepMail 实体关系抽取助手。
从邮件中抽取：
1. 实体 entities：person（人名/称谓）/ org（公司/部门）/ project（项目/产品名）/ date（日期时间）/ location（地点）/ product（具体产品/工具）。
2. 关系 relations：三元组 (subject, predicate, object, confidence)，confidence ∈ [0, 1]。

规则：
- 只抽取邮件中**显式出现**的实体，不要推测。
- 实体名称保留原文表述；同一实体的不同写法按"较完整"那个保留。
- 如果邮件无明显实体/关系，返回空对象 {"entities": [], "relations": []}。"""


class EntityExtractAgent(PipelineAgent[EmailInput, EntityExtractOutput]):
    name = "entity_extract"
    input_schema = EmailInput
    output_schema = EntityExtractOutput

    def build_messages(self, inp: EmailInput):  # type: ignore[override]
        user = f"主题：{inp.subject}\n\n正文：\n{inp.body_text}"
        return [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user)]
