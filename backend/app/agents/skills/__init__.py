"""Skill 实现。"""

from app.agents.skills.base import Skill, SkillResult
from app.agents.skills.classify import ClassifySkill
from app.agents.skills.draft import DraftSkill
from app.agents.skills.entity_extract import EntityExtractSkill
from app.agents.skills.spam import SpamSkill
from app.agents.skills.summary import SummarySkill
from app.agents.skills.tag import TagRecommendSkill
from app.agents.skills.todo_extract import TodoExtractSkill

__all__ = [
    "Skill",
    "SkillResult",
    "SummarySkill",
    "TodoExtractSkill",
    "EntityExtractSkill",
    "ClassifySkill",
    "TagRecommendSkill",
    "SpamSkill",
    "DraftSkill",
]
