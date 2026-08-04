"""ORM 模型。导入此处可触发所有模型注册到 Base.metadata。"""

from app.db.models.chat import ChatMessage, ChatSession
from app.db.models.email import Email
from app.db.models.knowledge import (
    Entity,
    KnowledgeChunk,
    Relation,
)
from app.db.models.label import Category, Label
from app.db.models.memory import (
    MemoryLongTerm,
    MemoryMediumTopic,
)
from app.db.models.memory_event import MemoryEvent, MemoryEventTimeline
from app.db.models.persona import Persona
from app.db.models.todo import Todo, TodoPriority, TodoStatus
from app.db.models.usage import UsageLog
from app.db.models.user import LLMConfig, User, UserRole

__all__ = [
    "User",
    "UserRole",
    "LLMConfig",
    "Email",
    "Todo",
    "TodoStatus",
    "TodoPriority",
    "Label",
    "Category",
    "Persona",
    "KnowledgeChunk",
    "Entity",
    "Relation",
    "ChatSession",
    "ChatMessage",
    "MemoryMediumTopic",
    "MemoryLongTerm",
    "MemoryEvent",
    "MemoryEventTimeline",
    "UsageLog",
]
