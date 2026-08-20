"""PipelineAgent 实现（原 Skill，v2-P4 改名）。

单点 AI 能力 agent：接收输入 → 调 LLM（structured output / 文本兜底）→ 返回结构化结果。
区别于 LangGraph 的 sub-agent（email/todo/draft/rag/tidy 编排 agent）。
"""

from app.agents.pipeline.base import PipelineAgent, PipelineResult
from app.agents.pipeline.classify import ClassifyAgent
from app.agents.pipeline.draft import DraftAgent
from app.agents.pipeline.entity_extract import EntityExtractAgent
from app.agents.pipeline.spam import SpamAgent
from app.agents.pipeline.summary import SummaryAgent
from app.agents.pipeline.tag import TagRecommendAgent
from app.agents.pipeline.todo_extract import TodoExtractAgent

__all__ = [
    "PipelineAgent",
    "PipelineResult",
    "SummaryAgent",
    "TodoExtractAgent",
    "EntityExtractAgent",
    "ClassifyAgent",
    "TagRecommendAgent",
    "SpamAgent",
    "DraftAgent",
]
