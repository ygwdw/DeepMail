"""所有 PipelineAgent 的 Pydantic 输出 schema 与共用类型。

⚠️ 重要：每个字段必须有 `description`！
Pydantic 的 Field description 会原样注入到 LLM prompt（langchain with_structured_output
会自动转成 JSON Schema），缺 description 会显著降低结构化输出质量。
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, RootModel

# ---------- 1. 摘要 ----------


class SummaryOutput(BaseModel):
    summary: str = Field(
        max_length=500,
        description="1-3 句话的中文摘要，抓邮件主旨",
    )
    key_points: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="3-5 个关键要点，每点一行（不超过 30 字）",
    )


# ---------- 2. 待办抽取 ----------


class TodoItem(BaseModel):
    content: str = Field(
        min_length=1,
        max_length=500,
        description="待办内容（动词开头，< 100 字）。例：'签署 Acme NDA 修订版'",
    )
    due_date: date | None = Field(
        default=None,
        description="明确日期 YYYY-MM-DD（邮件中明文提到的日期），无则 null。例：'2026-08-10'",
    )
    priority: Literal["low", "medium", "high"] = Field(
        default="medium",
        description="优先级：high=紧急/截止/事故；medium=重要但非紧急；low=可推迟",
    )


class TodoExtractOutput(BaseModel):
    """v2-M4.2: 用 wrapper class 替代裸 list[TodoItem]。
    - BaseModel.with_structured_output 在 OpenAI 协议下能识别（不识 list 顶层）
    - LLM 直接输出 list 时，_parse_from_text 兜底把 list 包成 {items: [...]}
    - .items 字段访问友好（不像 RootModel 要 .root）
    """
    items: list[TodoItem] = Field(
        default_factory=list,
        description="抽取的待办列表",
    )


# ---------- 3. 实体关系抽取 ----------


class EntityItem(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=256,
        description="实体名（保留原文表述）。例：'陈总监'、'Acme 公司'、'V3.0'",
    )
    type: Literal["person", "org", "project", "date", "location", "product"] = Field(
        description="实体类型：person=人/org=公司机构/project=项目或版本/date=日期/location=地点/product=产品或工具",
    )


class RelationItem(BaseModel):
    subject: str = Field(min_length=1, max_length=256, description="关系主语（实体名）")
    predicate: str = Field(
        min_length=1,
        max_length=64,
        description="关系类型（动词/介词）。例：'works_at'、'reports_to'、'mentions'",
    )
    object: str = Field(min_length=1, max_length=256, description="关系宾语（实体名）")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        default=1.0,
        description="置信度 0-1，1=邮件明文确认，<0.5=推断",
    )


class EntityExtractOutput(BaseModel):
    entities: list[EntityItem] = Field(
        default_factory=list,
        description="从邮件正文提取的实体列表（去重后）",
    )
    relations: list[RelationItem] = Field(
        default_factory=list,
        description="实体间的关系三元组（subject, predicate, object）",
    )


# ---------- 4. 分类 ----------


class ClassifyOutput(BaseModel):
    category_name: str = Field(
        min_length=1,
        max_length=64,
        description="从候选 categories 中选一个最匹配的 name（必须严格等于候选名）",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="分类置信度 0-1，1=完全确定",
    )


# ---------- 5. 打标 ----------


class ExistingLabelMatch(BaseModel):
    name: str = Field(description="匹配的已有 label 名（严格等于现有 label）")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="匹配置信度 0-1，<0.6 不应输出",
    )


class NewLabelSuggestion(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=64,
        description="建议新建的 label 名（1-4 字中文或英文）",
    )
    type: Literal["topic", "action", "entity"] = Field(
        description="label 类型：topic=主题/action=行为/entity=实体",
    )
    reason: str = Field(
        min_length=1,
        max_length=200,
        description="建议此 label 的理由（< 50 字）",
    )


class TagRecommendOutput(BaseModel):
    existing_label_matches: list[ExistingLabelMatch] = Field(
        default_factory=list,
        description="已匹配到的现有 label（置信度 >= 0.6）",
    )
    recommended_new_labels: list[NewLabelSuggestion] = Field(
        default_factory=list,
        description="建议新建的 label（最多 3 个）",
    )


# ---------- 6. 垃圾过滤 ----------


class SpamOutput(BaseModel):
    spam_score: float = Field(
        ge=0.0,
        le=1.0,
        description="垃圾邮件分数 0-1，0=正常邮件，1=100% 垃圾。>=0.8 视为 is_spam=true",
    )
    is_spam: bool = Field(
        description="是否垃圾邮件（true/false），>=0.8 设为 true",
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="判定理由（最多 3 条短句）",
    )


# ---------- 7. 辅助起草 ----------


class DraftOutput(BaseModel):
    draft_text: str = Field(
        min_length=1,
        description="草稿正文（不含 From/To/Subject），用与原邮件同语言",
    )
    key_points: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="起草覆盖的核心要点（<=5）",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="起草置信度 0-1",
    )


# ---------- 输入 schema ----------


class EmailInput(BaseModel):
    subject: str = Field(description="邮件主题")
    body_text: str = Field(description="邮件正文（纯文本）")
    sender_email: str = Field(default="", description="发件人邮箱")
    sender_name: str | None = Field(default=None, description="发件人显示名（可空）")


class ClassifyInput(EmailInput):
    categories: list[CategoryRule] = Field(
        default_factory=list,
        description="候选分类列表（含 is_spam_category 标志）",
    )


class CategoryRule(BaseModel):
    name: str = Field(description="分类名（邮件分类后填此字段，必须严格匹配）")
    description: str = Field(
        default="",
        description="分类描述（帮助 LLM 理解何时选此分类）",
    )
    rules_json: dict = Field(
        default_factory=dict,
        description="分类规则 JSON（含 keywords 等）",
    )
    is_spam_category: bool = Field(
        default=False,
        description="此分类是否视为垃圾邮件分类（系统会自动放进 spam folder）",
    )
    is_system: bool = Field(default=False, description="是否系统预设分类（不可改名/删）")


class LabelInfo(BaseModel):
    """供 Tag skill 参考的标签信息（含描述）。"""

    name: str = Field(description="标签名")
    description: str = Field(default="", description="标签描述（帮助 LLM 决定是否匹配）")


class TagInput(EmailInput):
    existing_labels: list[LabelInfo] = Field(
        default_factory=list,
        description="用户已有标签列表（可空）",
    )


class DraftInput(BaseModel):
    instruction: str = Field(
        min_length=1,
        description="起草要求（中文/英文，按用户原话）",
    )
    tone: Literal["formal", "casual", "auto"] = Field(
        default="auto",
        description="语气：formal=正式/casual=随意/auto=按邮件自动判断",
    )
    sender_email: str = Field(description="原邮件发件人邮箱")
    subject: str = Field(description="原邮件主题")
    body_text: str = Field(description="原邮件正文")
    history_text: str = Field(
        default="",
        description="联系人历史邮件拼成的上下文（已构造）",
    )
    persona: str = Field(
        default="",
        description="用户人格画像（name/age/education/profession/personality/communication_style/language_pref/signature/frequent_topics/sample_phrases），空表示无",
    )


# ---------- Supervisor 决策 ----------


class RoutingDecision(BaseModel):
    agents: list[Literal["email", "todo", "draft", "rag", "tidy"]] = Field(
        min_length=1,
        max_length=3,
        description=(
            "派发的 sub-agent 列表（1-3 个）。"
            "email=邮件处理；todo=待办；draft=起草；rag=知识库；tidy=批量整理"
        ),
    )
    reasoning: str = Field(
        default="",
        description="派发理由（< 80 字）",
    )


ClassifyInput.model_rebuild()
