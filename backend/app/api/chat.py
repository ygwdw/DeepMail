"""/api/chat/* 路由。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import ORMModel
from app.services import chat_service
from app.services.email_service import EmailService
from app.api.deps import get_email_provider

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
    # v2-M4.3: L5 挂载检索开关
    enable_l5: bool = False
    enable_l5_partitions: list[str] = []  # 空 = 检索所有非 inbox 分区


class DraftReplyCreate(BaseModel):
    title: str | None = None


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

    v2-M8：保留同步 endpoint（向后兼容 / e2e 测试用）；流式版见 /messages/stream。
    """
    session = await chat_service.get_session(db, current.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    result = await chat_service.send_message(
        db,
        current.id,
        session_id,
        payload.content,
        enable_l5=payload.enable_l5,
        enable_l5_partitions=payload.enable_l5_partitions,
    )
    return result


@router.post("/sessions/{session_id}/messages/stream")
async def send_message_stream(
    session_id: uuid.UUID,
    payload: SendMessageRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """v2-M8：SSE 流式聊天。每次事件格式：`data: {json}\\n\\n`。

    事件类型：user / thinking / tool_start / tool_end / content / usage / error / end。
    """
    from fastapi.responses import StreamingResponse
    import json as _json

    session = await chat_service.get_session(db, current.id, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    async def _gen():
        async for ev in chat_service.send_message_stream(
            db,
            current.id,
            session_id,
            payload.content,
            enable_l5=payload.enable_l5,
            enable_l5_partitions=payload.enable_l5_partitions,
        ):
            yield f"data: {_json.dumps(ev, ensure_ascii=False, default=str)}\n\n"

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
            "Connection": "keep-alive",
        },
    )


# ---------- v2-M7：写信助手专用会话 ----------


@router.post("/sessions/draft-reply", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED)
async def create_draft_reply_session(
    email_id: uuid.UUID = Query(..., description="要回复的邮件 ID"),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    provider = Depends(get_email_provider),
) -> ChatSessionRead:
    """为"写信助手"创建一个空会话；前端拿到 session_id 后构造 prompt 调 send_message。

    v2 修正：不再预加载消息（之前会塞 system/user 进 messages，前端误把 system 展示给用户）。
    """
    svc = EmailService(db, provider)
    email = await svc.get_email(current.id, email_id)
    if email is None:
        raise HTTPException(status_code=404, detail="email not found")

    title = f"回复：{email.subject or '(无主题)'}"[:100]
    session = await chat_service.create_session(db, current.id, title=title)
    return ChatSessionRead(
        id=session.id,
        title=session.title,
        created_at=session.created_at.isoformat(),
        updated_at=session.updated_at.isoformat(),
    )
