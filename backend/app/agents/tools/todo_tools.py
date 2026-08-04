"""Todo 相关工具。"""

from __future__ import annotations

import json
import uuid

from langchain_core.tools import tool
from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models.todo import Todo, TodoStatus

_logger = get_logger(__name__)


@tool
async def list_todos(status: str = "pending", limit: int = 20) -> str:
    """列出待办。

    Args:
        status: pending / done / cancelled / all
        limit: 数量

    Returns:
        JSON 字符串
    """
    from app.agents.tools.context import get_current_user_id

    user_id = get_current_user_id()
    if user_id is None:
        return json.dumps({"error": "no user context"})
    _logger.info("tool_call", tool="list_todos", status=status, limit=limit)
    from app.db.session import get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as db:
        stmt = select(Todo).where(Todo.user_id == uuid.UUID(user_id))
        if status != "all":
            try:
                stmt = stmt.where(Todo.status == TodoStatus(status))
            except ValueError:
                return json.dumps({"error": f"invalid status {status}"})
        stmt = stmt.order_by(Todo.created_at.desc()).limit(limit)
        rows = list((await db.execute(stmt)).scalars().all())
    items = [
        {
            "id": str(t.id),
            "content": t.content,
            "due_date": t.due_date.isoformat() if t.due_date else None,
            "status": t.status.value,
            "priority": t.priority.value,
        }
        for t in rows
    ]
    return json.dumps({"items": items}, ensure_ascii=False)


@tool
async def create_todo(content: str, due_date: str | None = None, priority: str = "medium") -> str:
    """创建一条待办。

    Args:
        content: 待办内容
        due_date: YYYY-MM-DD（可选）
        priority: low / medium / high

    Returns:
        JSON 字符串（新 todo 信息）
    """
    from app.agents.tools.context import get_current_user_id

    user_id = get_current_user_id()
    if user_id is None:
        return json.dumps({"error": "no user context"})
    _logger.info("tool_call", tool="create_todo", content=content[:50])
    from datetime import date as _date

    from app.db.models.todo import TodoPriority
    from app.db.session import get_sessionmaker

    sm = get_sessionmaker()
    try:
        prio = TodoPriority(priority)
    except ValueError:
        prio = TodoPriority.medium
    parsed_due = None
    if due_date:
        try:
            parsed_due = _date.fromisoformat(due_date)
        except ValueError:
            return json.dumps({"error": f"invalid due_date {due_date}"})
    async with sm() as db:
        todo = Todo(
            user_id=uuid.UUID(user_id),
            content=content,
            due_date=parsed_due,
            priority=prio,
        )
        db.add(todo)
        await db.commit()
        await db.refresh(todo)
    return json.dumps(
        {
            "id": str(todo.id),
            "content": todo.content,
            "due_date": todo.due_date.isoformat() if todo.due_date else None,
            "priority": todo.priority.value,
        },
        ensure_ascii=False,
    )
