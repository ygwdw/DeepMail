"""/api/chat/* 路由。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import ORMModel
from app.services import chat_service

router = APIRouter(prefix="/api/chat", tags=["chat"])


# ---------- Schemas ----------


class ChatSessionCreate(BaseModel):
    title: str = ""


class ChatSessionRead(ORMModel):
    id: uuid.UUID
    title: str
    created_at: str
    updated_at: str


class ChatMessageRead(ORMModel):
    id: uuid.UUID
    role: str
    content: str
    tool_calls: list = []
    created_at: str


class SendMessageRequest(BaseModel):
    content: str


# ---------- 会话 ----------


@router.post("/sessions", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
async def create_session(
    payload: ChatSessionCreate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionRead:
    session = await chat_service.create_session(db, current.id, title=payload.title)
    return ChatSessionRead(
        id=session.id,
        title=session.title,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


@router.get("/sessions", response_model=list[ChatSessionRead])
async def list_sessions(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatSessionRead]:
    sessions = await chat_service.list_sessions(db, current.id)
    return [
        ChatSessionRead(
            id=s.id,
            title=s.title,
            created_at=s.created_at.isoformat(),
            updated_at=s.updated_at.isoformat(),
        )
        for s in sessions
    ]


@router.get("/sessions/{session_id}", response_model=ChatSessionRead)
async def get_session(
    session_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionRead:
    session = await chat_service.get_session(db, current.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return ChatSessionRead(
        id=session.id,
        title=session.title,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    ok = await chat_service.delete_session(db, current.id, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="session not found")


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageRead])
async def list_messages(
    session_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatMessageRead]:
    msgs = await chat_service.get_messages(db, current.id, session_id)
    return [
        ChatMessageRead(
            id=m.id,
            role=m.role,
            content=m.content,
            tool_calls=m.tool_calls or [],
            created_at=m.created_at.isoformat(),
        )
        for m in msgs
    ]


# ---------- 消息（核心：Agent 自主决策） ----------


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: uuid.UUID,
    payload: SendMessageRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """用户发消息，Agent 自主决定调用哪些工具，返回最终回复。

    （阶段 3 同步版：第二期升级为 SSE 流式）
    """
    session = await chat_service.get_session(db, current.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    result = await chat_service.send_message(db, current.id, session_id, payload.content)
    return result
