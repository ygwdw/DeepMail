"""/api/todos CRUD。"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.email import Email
from app.db.models.todo import Todo, TodoPriority, TodoStatus
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.common import ORMModel, Page

router = APIRouter(prefix="/api/todos", tags=["todos"])


class TodoRead(ORMModel):
    id: uuid.UUID
    email_id: uuid.UUID | None
    content: str
    due_date: date | None
    status: TodoStatus
    priority: TodoPriority
    # v2-M9 / bug fix: ORM 是 datetime，schema 必须是 datetime 才能 validate；
    # 之前写 str 导致 500。响应序列化时自动转 ISO 字符串。
    created_at: datetime | None = None


class TodoCreate(BaseModel):
    """v2-M9: 新建 todo。due_date 必填（用户决策）。"""
    content: str = Field(min_length=1, max_length=500)
    due_date: date
    priority: TodoPriority = TodoPriority.MEDIUM
    email_id: uuid.UUID | None = None


class TodoUpdate(BaseModel):
    status: TodoStatus | None = None
    priority: TodoPriority | None = None
    due_date: date | None = Field(default=None)
    content: str | None = Field(default=None, min_length=1, max_length=500)


class TodoStats(ORMModel):
    """v2-M9: 待办统计。"""
    pending: int = 0
    done: int = 0
    cancelled: int = 0
    by_priority: dict[str, int] = {}  # {"high": N, "medium": N, "low": N}


@router.get("/stats", response_model=TodoStats)
async def todo_stats(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TodoStats:
    """v2-M9: 按 status / priority 聚合的统计。"""
    from sqlalchemy import func

    items = list(
        (
            await db.execute(
                select(Todo.status, Todo.priority, func.count(Todo.id))
                .where(Todo.user_id == current.id)
                .group_by(Todo.status, Todo.priority)
            )
        ).all()
    )
    pending = done = cancelled = 0
    by_priority: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for status, priority, count in items:
        cnt = int(count)
        if status == TodoStatus.PENDING:
            pending += cnt
        elif status == TodoStatus.DONE:
            done += cnt
        elif status == TodoStatus.CANCELLED:
            cancelled += cnt
        by_priority[priority.value] = by_priority.get(priority.value, 0) + cnt
    return TodoStats(pending=pending, done=done, cancelled=cancelled, by_priority=by_priority)


@router.post("", response_model=TodoRead, status_code=status.HTTP_201_CREATED)
async def create_todo(
    payload: TodoCreate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TodoRead:
    """v2-M9: 新建 todo。"""
    # 校验关联邮件（如果指定）
    if payload.email_id is not None:
        em = (await db.execute(
            select(Email).where(Email.id == payload.email_id, Email.user_id == current.id)
        )).scalar_one_or_none()
        if em is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="email not found")

    todo = Todo(
        user_id=current.id,
        email_id=payload.email_id,
        content=payload.content,
        due_date=payload.due_date,
        priority=payload.priority,
        status=TodoStatus.PENDING,
    )
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return TodoRead.model_validate(todo)


@router.get("", response_model=Page[TodoRead])
async def list_todos(
    status_filter: TodoStatus | None = Query(default=None, alias="status"),
    priority: TodoPriority | None = Query(default=None),
    sort: str = Query(default="created_at", pattern="^(created_at|due_date|priority|status)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[TodoRead]:
    """v2-M9: 支持排序 sort=due_date/priority/status。"""
    from sqlalchemy import func

    stmt = select(Todo).where(Todo.user_id == current.id)
    count_stmt = select(func.count(Todo.id)).where(Todo.user_id == current.id)
    if status_filter is not None:
        stmt = stmt.where(Todo.status == status_filter)
        count_stmt = count_stmt.where(Todo.status == status_filter)
    if priority is not None:
        stmt = stmt.where(Todo.priority == priority)
        count_stmt = count_stmt.where(Todo.priority == priority)

    # 排序
    if sort == "due_date":
        # due_date 升序：NULL 排最后
        stmt = stmt.order_by(Todo.due_date.asc().nulls_last(), Todo.created_at.desc())
    elif sort == "priority":
        stmt = stmt.order_by(Todo.priority.desc(), Todo.created_at.desc())
    elif sort == "status":
        stmt = stmt.order_by(Todo.status.asc(), Todo.created_at.desc())
    else:
        stmt = stmt.order_by(Todo.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)

    items = list((await db.execute(stmt)).scalars().all())
    total = int((await db.execute(count_stmt)).scalar_one())
    return Page[TodoRead](
        items=[TodoRead.model_validate(t) for t in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/{todo_id}", response_model=TodoRead)
async def update_todo(
    todo_id: uuid.UUID,
    payload: TodoUpdate,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TodoRead:
    stmt = select(Todo).where(Todo.id == todo_id, Todo.user_id == current.id)
    todo = (await db.execute(stmt)).scalar_one_or_none()
    if todo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="todo not found")
    if payload.status is not None:
        todo.status = payload.status
    if payload.priority is not None:
        todo.priority = payload.priority
    if payload.due_date is not None:
        todo.due_date = payload.due_date
    if payload.content is not None:
        todo.content = payload.content
    await db.commit()
    await db.refresh(todo)
    return TodoRead.model_validate(todo)


@router.delete("/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(
    todo_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """v2-M9: 删除 todo。"""
    todo = (await db.execute(
        select(Todo).where(Todo.id == todo_id, Todo.user_id == current.id)
    )).scalar_one_or_none()
    if todo is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="todo not found")
    await db.delete(todo)
    await db.commit()
