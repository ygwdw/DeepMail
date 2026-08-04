"""混合检索：向量 + BM25 + RRF → Reranker。

pgvector 已用于向量检索；BM25 用 PostgreSQL tsvector + plainto_tsquery。
RRF（Reciprocal Rank Fusion, k=60）融合两个榜单。
最后用 Reranker 重排。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm.embeddings import EmbeddingClient
from app.llm.reranker import RerankClient


@dataclass
class RetrievedChunk:
    chunk_id: uuid.UUID
    partition: str
    source: str | None
    content: str
    metadata: dict
    score: float  # 融合后/Reranker 后分数
    vector_rank: int | None = None
    bm25_rank: int | None = None


class HybridRetriever:
    def __init__(
        self,
        db: AsyncSession,
        embed_client: EmbeddingClient,
        rerank_client: RerankClient,
    ) -> None:
        self._db = db
        self._embed = embed_client
        self._rerank = rerank_client

    async def retrieve(
        self,
        *,
        user_id: uuid.UUID,
        query: str,
        partition: str | None = None,
        top_k: int = 5,
        fetcher_k: int = 20,
        use_rerank: bool = True,
    ) -> list[RetrievedChunk]:
        """完整流程：向量 + BM25 → RRF → Reranker → top_k。"""
        if not query.strip():
            return []

        # 1. 向量检索
        qvec = await self._embed.embed_one(query)
        vector_hits = await self._vector_search(
            user_id=user_id, query_vec=qvec, partition=partition, k=fetcher_k
        )
        # 2. BM25 全文检索
        bm25_hits = await self._bm25_search(
            user_id=user_id, query=query, partition=partition, k=fetcher_k
        )

        # 3. RRF 融合
        fused = _rrf_fuse(vector_hits, bm25_hits, k=60)
        if not fused:
            return []

        # 4. Reranker 重排
        if use_rerank and len(fused) > top_k:
            try:
                docs = [self._content(c) for c in fused]
                reranked = await self._rerank.rerank(query, docs, top_n=top_k)
                # 按 reranker 顺序输出
                result = []
                for r in reranked:
                    idx = int(r["index"])
                    if 0 <= idx < len(fused):
                        chunk = fused[idx]
                        chunk.score = float(r["relevance_score"])
                        result.append(chunk)
                return result[:top_k]
            except Exception:
                # Reranker 失败时降级到 RRF 顺序
                pass

        # 不重排 / Reranker 失败：返回 RRF 融合结果前 top_k
        for rank, c in enumerate(fused[:top_k], 1):
            c.score = 1.0 / (60 + rank)
        return fused[:top_k]

    def _content(self, c: RetrievedChunk) -> str:
        return c.content

    async def _vector_search(
        self,
        *,
        user_id: uuid.UUID,
        query_vec: list[float],
        partition: str | None,
        k: int,
    ) -> list[RetrievedChunk]:
        """pgvector cosine 相似度 topk。"""
        params: dict[str, Any] = {"user_id": str(user_id), "k": k}
        partition_clause = ""
        if partition:
            partition_clause = "AND partition = :partition"
            params["partition"] = partition
        sql = text(
            f"""
            SELECT id, partition, source, content, metadata_json,
                   1 - (embedding <=> :qvec) AS similarity
            FROM knowledge_chunks
            WHERE user_id = :user_id
              AND embedding IS NOT NULL
              {partition_clause}
            ORDER BY embedding <=> :qvec
            LIMIT :k
            """
        )
        # asyncpg 不能直接传 list[float]，需要字符串格式
        params["qvec"] = "[" + ",".join(f"{x:.7f}" for x in query_vec) + "]"
        rows = (await self._db.execute(sql, params)).mappings().all()
        return [
            RetrievedChunk(
                chunk_id=r["id"],
                partition=r["partition"],
                source=r["source"],
                content=r["content"],
                metadata=r["metadata_json"] or {},
                score=float(r["similarity"]),
                vector_rank=idx + 1,
            )
            for idx, r in enumerate(rows)
        ]

    async def _bm25_search(
        self,
        *,
        user_id: uuid.UUID,
        query: str,
        partition: str | None,
        k: int,
    ) -> list[RetrievedChunk]:
        """PostgreSQL tsvector 全文检索。"""
        params: dict[str, Any] = {"user_id": str(user_id), "q": query, "k": k}
        partition_clause = ""
        if partition:
            partition_clause = "AND partition = :partition"
            params["partition"] = partition
        sql = text(
            f"""
            SELECT id, partition, source, content, metadata_json,
                   ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', :q)) AS rank
            FROM knowledge_chunks
            WHERE user_id = :user_id
              AND to_tsvector('simple', content) @@ plainto_tsquery('simple', :q)
              {partition_clause}
            ORDER BY rank DESC
            LIMIT :k
            """
        )
        rows = (await self._db.execute(sql, params)).mappings().all()
        return [
            RetrievedChunk(
                chunk_id=r["id"],
                partition=r["partition"],
                source=r["source"],
                content=r["content"],
                metadata=r["metadata_json"] or {},
                score=float(r["rank"]),
                bm25_rank=idx + 1,
            )
            for idx, r in enumerate(rows)
        ]


def _rrf_fuse(
    vector_hits: list[RetrievedChunk],
    bm25_hits: list[RetrievedChunk],
    *,
    k: int = 60,
) -> list[RetrievedChunk]:
    """Reciprocal Rank Fusion."""
    scores: dict[uuid.UUID, float] = {}
    chunks: dict[uuid.UUID, RetrievedChunk] = {}

    for rank, c in enumerate(vector_hits, 1):
        scores[c.chunk_id] = scores.get(c.chunk_id, 0.0) + 1.0 / (k + rank)
        chunks[c.chunk_id] = c
    for rank, c in enumerate(bm25_hits, 1):
        scores[c.chunk_id] = scores.get(c.chunk_id, 0.0) + 1.0 / (k + rank)
        if c.chunk_id not in chunks:
            chunks[c.chunk_id] = c
        # 更新 BM25 排名
        chunks[c.chunk_id].bm25_rank = rank

    # 按 RRF 分数排序
    sorted_ids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
    out: list[RetrievedChunk] = []
    for cid in sorted_ids:
        c = chunks[cid]
        c.score = scores[cid]
        out.append(c)
    return out
