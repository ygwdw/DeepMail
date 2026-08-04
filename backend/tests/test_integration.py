"""集成测试：所有路由 import + 列表 + ORM schema 一致性。"""

from __future__ import annotations


def test_app_imports() -> None:
    """整个 app 链能 import 起来。"""
    from app.main import app

    assert app is not None
    assert app.title == "DeepMail API"


def test_openapi_paths_completeness() -> None:
    """核心 API 路径都已注册（用 OpenAPI schema 检查，比 app.routes 更可靠）。"""
    from app.main import app

    openapi = app.openapi()
    paths = set(openapi["paths"].keys())

    # 阶段 0
    assert "/health" in paths
    assert "/api/auth/login" in paths
    assert "/api/auth/register" in paths
    assert "/api/me" in paths

    # 阶段 1
    assert "/api/emails" in paths
    assert "/api/todos" in paths
    assert "/api/categories" in paths
    assert "/api/labels" in paths
    assert "/api/emails/{email_id}/process" in paths
    assert "/api/emails/{email_id}/summary" in paths
    assert "/api/emails/{email_id}/draft" in paths

    # 阶段 2
    assert "/api/knowledge/search" in paths
    assert "/api/knowledge/index/emails" in paths
    assert "/api/knowledge/partitions" in paths

    # 阶段 3
    assert "/api/chat/sessions" in paths
    assert "/api/chat/sessions/{session_id}/messages" in paths

    # 阶段 4
    assert "/api/memory/topics" in paths
    assert "/api/memory/events" in paths
    assert "/api/memory/long-term" in paths

    # 阶段 5
    assert "/api/persona" in paths
    assert "/api/persona/rollback" in paths

    # 阶段 7
    assert "/api/dashboard/events" in paths


def test_openapi_total_paths() -> None:
    """总共路径数 > 30（动态检查所有端点都注册）。"""
    from app.main import app

    paths = app.openapi()["paths"]
    assert len(paths) >= 30, f"only {len(paths)} paths, expected >= 30"


def test_orm_models_metadata_consistent() -> None:
    """所有 ORM 模型的表都能从 metadata 加载。"""
    from app.db.base import Base

    for tbl in [
        "users",
        "llm_configs",
        "emails",
        "todos",
        "labels",
        "categories",
        "personas",
        "knowledge_chunks",
        "entities",
        "relations",
        "chat_sessions",
        "chat_messages",
        "memory_medium_topics",
        "memory_long_term",
        "memory_events",
        "memory_event_timeline",
    ]:
        assert tbl in Base.metadata.tables, f"table {tbl} not in metadata"


def test_settings_loadable() -> None:
    """Settings 能从环境加载。"""
    from app.core.config import get_settings

    s = get_settings()
    assert s.app_env in ("development", "test", "production")
    assert s.llm_chat_model
    assert s.llm_embed_dim > 0
    assert s.jwt_secret


def test_logging_configure_idempotent() -> None:
    """logging.configure_logging 可重复调用不报错。"""
    from app.core.logging import configure_logging

    configure_logging()
    configure_logging()  # idempotent


def test_tracing_configure() -> None:
    """tracing.configure_langsmith 不报错（即使没 key）。"""
    from app.core.tracing import configure_langsmith

    configure_langsmith()


def test_models_importable() -> None:
    """所有 Pydantic schema 可 import。"""
    from app.agents.schemas import (
        RoutingDecision,
        SummaryOutput,
    )

    assert SummaryOutput is not None
    assert RoutingDecision is not None
