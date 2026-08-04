"""入库器：把 chunk + embedding 写入 knowledge_chunks 表。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.knowledge import KnowledgeChunk
from app.llm.embeddings import EmbeddingClient
from app.rag.chunker import TextChunk


def _to_metadata_json(meta: dict) -> dict:
    """元数据转 JSON 友好的 dict（datetime → ISO 字符串 等）。"""
    out: dict = {}
    for k, v in meta.items():
        if isinstance(v, datetime):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


class Indexer:
    def __init__(self, db: AsyncSession, embed_client: EmbeddingClient) -> None:
        self._db = db
        self._embed = embed_client

    async def index_chunks(
        self,
        *,
        user_id: uuid.UUID,
        partition: str,
        source: str,
        source_id: str | None,
        chunks: list[TextChunk],
    ) -> int:
        """把 chunks 嵌入并写入 knowledge_chunks。返回新增条数。"""
        if not chunks:
            return 0
        texts = [c.text for c in chunks]
        embeddings = await self._embed.embed(texts)
        for chunk, vec in zip(chunks, embeddings):
            row = KnowledgeChunk(
                user_id=user_id,
                partition=partition,
                source=source,
                source_id=source_id,
                content=chunk.text,
                embedding=vec,
                metadata_json=_to_metadata_json(chunk.metadata),
            )
            self._db.add(row)
        await self._db.commit()
        return len(chunks)

    async def delete_partition(self, user_id: uuid.UUID, partition: str) -> int:
        """删除某用户某分区的所有 chunk。"""
        stmt = delete(KnowledgeChunk).where(
            KnowledgeChunk.user_id == user_id,
            KnowledgeChunk.partition == partition,
        )
        result = await self._db.execute(stmt)
        await self._db.commit()
        return result.rowcount or 0

    async def delete_by_source(
        self,
        user_id: uuid.UUID,
        source: str,
        source_id: str,
    ) -> int:
        stmt = delete(KnowledgeChunk).where(
            KnowledgeChunk.user_id == user_id,
            KnowledgeChunk.source == source,
            KnowledgeChunk.source_id == source_id,
        )
        result = await self._db.execute(stmt)
        await self._db.commit()
        return result.rowcount or 0
