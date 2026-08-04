"""Reranker：调用 gitee Qwen3-Reranker-0.6B。"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import get_settings

_settings = get_settings()


class RerankClient:
    """Qwen3-Reranker-0.6B 异步客户端（gitee /v1/rerank 端点）。"""

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=_settings.rerank_base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {_settings.rerank_api_key}"},
            timeout=30.0,
        )

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """对 documents 按与 query 的相关性排序。

        返回 [{"index": i, "relevance_score": float}, ...]，按 score 降序。
        """
        if not documents:
            return []
        payload: dict[str, Any] = {
            "model": _settings.llm_rerank_model,
            "query": query,
            "documents": documents,
        }
        if top_n is not None:
            payload["top_n"] = top_n
        resp = await self._client.post("/rerank", json=payload)
        resp.raise_for_status()
        data = resp.json()
        # gitee Qwen3-Reranker 格式：{"results": [{"index": ..., "relevance_score": ...}]}
        results = data.get("results") or data.get("data") or []
        return [
            {"index": r["index"], "relevance_score": float(r.get("relevance_score", 0.0))}
            for r in results
        ]

    async def aclose(self) -> None:
        await self._client.aclose()


_client: RerankClient | None = None


def get_rerank_client() -> RerankClient:
    global _client
    if _client is None:
        _client = RerankClient()
    return _client


async def close_rerank_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
