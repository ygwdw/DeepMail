"""pytest 配置：注入 .env 路径，提供 fixtures。"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# 路径：让 `from app.X import Y` 生效
BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
for p in (str(BACKEND_DIR), str(ROOT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

# 测试使用 .env.example，避免依赖真实 .env
os.environ.setdefault("APP_ENV", "test")
# 强制注入一个最小的测试配置
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://deepmail:deepmail@localhost:5432/deepmail"
)
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests-only")
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "Admin@Pass123")
# 注意：不要 setdefault LLM_API_KEY，否则会覆盖 .env 的真实 key（环境变量优先级高于 .env）
# is_mock_mode() 会自动判定：如果 .env 里有真实 LLM_API_KEY，is_mock_mode() = False


import pytest  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import dispose_engine, get_sessionmaker  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
async def _truncate_tables_and_dispose():
    """每个测试前清空业务衍生表 + 测试后 dispose engine。

    v2-M3: 不再 truncate `emails` 和 `users`（保留 mock 邮件 + admin 用户），
    避免每次测试重置数据 + 防止被误清真实 IMAP 同步的邮件。
    """
    sm = get_sessionmaker()
    async with sm() as session:
        # 仅清业务衍生表；emails / users / categories / labels 保留
        # （categories/labels 是用户配置数据，只在创建用户时 seed 一次，
        #   若清掉则现有用户分类永久丢失 —— 见 v2 分类为空 bug 修复）
        await session.execute(
            text(
                "TRUNCATE TABLE chat_messages, chat_sessions, todos, "
                "personas, knowledge_chunks, entities, "
                "relations, memory_medium_topics, memory_long_term, "
                "memory_events, memory_event_timeline, "
                "llm_configs, usage_logs RESTART IDENTITY CASCADE"
            )
        )
        await session.commit()
    try:
        yield
    finally:
        await dispose_engine()


@pytest.fixture
async def async_client():
    """返回 httpx AsyncClient 用于调用 FastAPI（无 DB，仅依赖 JWT/路由）。"""
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
