"""/api/todos CRUD。"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
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


class TodoUpdate(BaseModel):
    status: TodoStatus | None = None
    priority: TodoPriority | None = None
    due_date: date | None = Field(default=None)
    content: str | None = Field(default=None, min_length=1, max_length=500)


@router.get("", response_model=Page[TodoRead])
async def list_todos(
    status_filter: TodoStatus | None = Query(default=None, alias="status"),
    priority: TodoPriority | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Page[TodoRead]:
    from sqlalchemy import func

    stmt = select(Todo).where(Todo.user_id == current.id)
    count_stmt = select(func.count(Todo.id)).where(Todo.user_id == current.id)
    if status_filter is not None:
        stmt = stmt.where(Todo.status == status_filter)
        count_stmt = count_stmt.where(Todo.status == status_filter)
    if priority is not None:
        stmt = stmt.where(Todo.priority == priority)
        count_stmt = count_stmt.where(Todo.priority == priority)
    stmt = stmt.order_by(Todo.created_at.desc()).limit(limit).offset(offset)

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
