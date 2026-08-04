"""Embedding 工厂：调用 gitee Qwen3-Embedding-0.6B（OpenAI 兼容协议）。"""

from __future__ import annotations

import httpx
from openai import AsyncOpenAI

from app.core.config import get_settings

_settings = get_settings()


class EmbeddingClient:
    """Qwen3-Embedding-0.6B 异步客户端。

    使用 gitee 的 OpenAI 兼容 /v1/embeddings 端点。
    """

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            base_url=_settings.embed_base_url,
            api_key=_settings.embed_api_key,
            timeout=httpx.Timeout(30.0),
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """批量向量化。空入返回空列表。"""
        if not texts:
            return []
        # gitee/OpenAI 兼容 API 限制 batch size
        batch_size = 32
        results: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            resp = await self._client.embeddings.create(
                model=_settings.llm_embed_model,
                input=batch,
            )
            # 按 index 排序（OpenAI 兼容 API 不保证顺序）
            sorted_data = sorted(resp.data, key=lambda d: d.index)
            for d in sorted_data:
                results.append(d.embedding)
        return results

    async def embed_one(self, text: str) -> list[float]:
        """单条文本向量化。"""
        vec = await self.embed([text])
        return vec[0] if vec else []

    async def aclose(self) -> None:
        await self._client.close()


# 全局单例
_client: EmbeddingClient | None = None


def get_embedding_client() -> EmbeddingClient:
    global _client
    if _client is None:
        _client = EmbeddingClient()
    return _client


async def close_embedding_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
