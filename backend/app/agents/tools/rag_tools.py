"""RAG 工具。"""

from __future__ import annotations

import json
import uuid

from langchain_core.tools import tool

from app.core.logging import get_logger

_logger = get_logger(__name__)


@tool
async def search_knowledge(
    query: str,
    partition: str | None = None,
    top_k: int = 5,
) -> str:
    """在知识库中搜索（邮件 + 用户上传的文档）。

    混合检索：向量 + BM25 → RRF → Rerank。

    Args:
        query: 搜索词
        partition: 限定分区（inbox / 用户自定义名），不传则全库搜
        top_k: 返回数量

    Returns:
        JSON 字符串，hits 列表（content / score / metadata）
    """
    from app.agents.tools.context import get_current_user_id

    user_id = get_current_user_id()
    if user_id is None:
        return json.dumps({"error": "no user context"})
    _logger.info("tool_call", tool="search_knowledge", query=query[:50], partition=partition)
    from app.db.session import get_sessionmaker
    from app.services import knowledge_service

    sm = get_sessionmaker()
    async with sm() as db:
        hits = await knowledge_service.search(
            db,
            uuid.UUID(user_id),
            query=query,
            partition=partition,
            top_k=top_k,
            use_rerank=True,
        )
    # 简化返回（只保留最相关字段）
    simple = [
        {
            "score": h["score"],
            "partition": h["partition"],
            "source": h["source"],
            "preview": h["content"][:200],
            "metadata": h["metadata"],
        }
        for h in hits
    ]
    return json.dumps({"hits": simple}, ensure_ascii=False)
