"""API 路由聚合。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    ai,
    auth,
    categories,
    chat,
    dashboard,
    emails,
    health,
    knowledge,
    labels,
    me,
    memory,
    persona,
    todos,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(me.router)
api_router.include_router(emails.router)
api_router.include_router(ai.router)
api_router.include_router(todos.router)
api_router.include_router(categories.router)
api_router.include_router(labels.router)
api_router.include_router(knowledge.router)
api_router.include_router(chat.router)
api_router.include_router(memory.router)
api_router.include_router(persona.router)
api_router.include_router(dashboard.router)
