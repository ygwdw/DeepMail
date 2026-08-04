"""知识库业务编排：CRUD + 索引 + 检索。"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.email import Email
from app.db.models.knowledge import KnowledgeChunk
from app.llm.embeddings import get_embedding_client
from app.llm.reranker import get_rerank_client
from app.rag.chunker import chunk_document, chunk_email
from app.rag.indexer import Indexer
from app.rag.retriever import HybridRetriever


def make_indexer(db: AsyncSession) -> Indexer:
    return Indexer(db, get_embedding_client())


def make_retriever(db: AsyncSession) -> HybridRetriever:
    return HybridRetriever(db, get_embedding_client(), get_rerank_client())


# ---------- 分区 ----------


async def list_partitions(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    """列出当前用户的所有分区 + 各分区 chunk 数。"""
    stmt = (
        select(KnowledgeChunk.partition, func.count(KnowledgeChunk.id).label("count"))
        .where(KnowledgeChunk.user_id == user_id)
        .group_by(KnowledgeChunk.partition)
        .order_by(KnowledgeChunk.partition)
    )
    rows = (await db.execute(stmt)).all()
    return [{"name": r[0], "chunk_count": int(r[1])} for r in rows]


async def delete_partition(db: AsyncSession, user_id: uuid.UUID, partition: str) -> int:
    if partition == "inbox":
        raise ValueError("inbox 分区为系统分区，不可删除")
    indexer = make_indexer(db)
    return await indexer.delete_partition(user_id, partition)


# ---------- 索引：邮件 ----------


async def index_emails(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    limit: int = 1000,
) -> int:
    """把当前用户的邮件入向量库（默认 partition=inbox）。"""
    stmt = (
        select(Email)
        .where(Email.user_id == user_id)
        .order_by(Email.received_at.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    indexer = make_indexer(db)
    total = 0
    for em in rows:
        # 全邮件 1 chunk（mail_id 区分）
        chunks = chunk_email(
            sender_name=em.sender_name,
            sender_email=em.sender_email,
            subject=em.subject,
            body_text=em.body_text,
            sent_at=em.sent_at.isoformat() if em.sent_at else None,
            thread_id=em.thread_id,
            recipients=em.recipients,
            labels=em.labels,
        )
        # 追加 email_id 到 metadata（便于回溯）
        for c in chunks:
            c.metadata["email_id"] = str(em.id)
        n = await indexer.index_chunks(
            user_id=user_id,
            partition="inbox",
            source="email",
            source_id=str(em.id),
            chunks=chunks,
        )
        total += n
    return total


async def index_email(db: AsyncSession, user_id: uuid.UUID, email_id: uuid.UUID) -> int:
    """单封邮件入库。"""
    stmt = select(Email).where(Email.user_id == user_id, Email.id == email_id)
    em = (await db.execute(stmt)).scalar_one_or_none()
    if em is None:
        return 0
    chunks = chunk_email(
        sender_name=em.sender_name,
        sender_email=em.sender_email,
        subject=em.subject,
        body_text=em.body_text,
        sent_at=em.sent_at.isoformat() if em.sent_at else None,
        thread_id=em.thread_id,
        recipients=em.recipients,
        labels=em.labels,
    )
    for c in chunks:
        c.metadata["email_id"] = str(em.id)
    indexer = make_indexer(db)
    return await indexer.index_chunks(
        user_id=user_id,
        partition="inbox",
        source="email",
        source_id=str(em.id),
        chunks=chunks,
    )


# ---------- 索引：文档 ----------


async def index_document(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    partition: str,
    filename: str,
    content: str,
    doc_id: str | None = None,
) -> int:
    """上传文档入库（首期只支持 txt/md）。"""
    if not content.strip():
        return 0
    doc_id = doc_id or uuid.uuid4().hex
    chunks = chunk_document(
        text=content,
        partition=partition,
        source="manual",
        filename=filename,
    )
    indexer = make_indexer(db)
    return await indexer.index_chunks(
        user_id=user_id,
        partition=partition,
        source="manual",
        source_id=doc_id,
        chunks=chunks,
    )


# ---------- 检索 ----------


async def search(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    query: str,
    partition: str | None = None,
    top_k: int = 5,
    use_rerank: bool = True,
) -> list[dict]:
    """混合检索。"""
    retriever = make_retriever(db)
    hits = await retriever.retrieve(
        user_id=user_id,
        query=query,
        partition=partition,
        top_k=top_k,
        use_rerank=use_rerank,
    )
    return [
        {
            "chunk_id": str(h.chunk_id),
            "partition": h.partition,
            "source": h.source,
            "content": h.content,
            "metadata": h.metadata,
            "score": float(h.score),
        }
        for h in hits
    ]


# ---------- 统计 ----------


async def stats(db: AsyncSession, user_id: uuid.UUID) -> dict:
    stmt = select(
        func.count(KnowledgeChunk.id).label("total"),
        func.count(func.distinct(KnowledgeChunk.partition)).label("partitions"),
        func.count(func.distinct(KnowledgeChunk.source)).label("sources"),
    ).where(KnowledgeChunk.user_id == user_id)
    row = (await db.execute(stmt)).one()
    return {
        "total_chunks": int(row.total),
        "total_partitions": int(row.partitions),
        "total_sources": int(row.sources),
    }
