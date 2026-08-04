"""RAG 模块单测：chunker + RRF 融合。用 mock embedding / rerank。"""

from __future__ import annotations

import uuid

from app.rag.chunker import chunk_document, chunk_email, chunk_text
from app.rag.retriever import RetrievedChunk, _rrf_fuse

# ---------- chunker ----------


def test_chunk_text_short() -> None:
    chunks = chunk_text("hello world")
    assert chunks == ["hello world"]


def test_chunk_text_long() -> None:
    text = "x" * 1000
    chunks = chunk_text(text, chunk_size=200, overlap=50)
    # 期望 1000 字，每 150 步长, 5 段
    assert len(chunks) >= 5
    # overlap 正确
    for i in range(len(chunks) - 1):
        assert chunks[i][-50:] == chunks[i + 1][:50]


def test_chunk_text_empty() -> None:
    assert chunk_text("") == []
    assert chunk_text("   ") == []


def test_chunk_email_short() -> None:
    chunks = chunk_email(
        sender_name="Alice",
        sender_email="alice@example.com",
        subject="hi",
        body_text="hello",
        sent_at="2026-01-01T00:00:00",
        thread_id="t1",
        recipients=["bob@example.com"],
        labels=["work"],
    )
    assert len(chunks) == 1
    assert chunks[0].metadata["sender"] == "alice@example.com"
    assert "主题：hi" in chunks[0].text
    assert "工作" not in chunks[0].text  # 工作是要求里的"工作相关"是 labels 但不进 text


def test_chunk_email_long() -> None:
    long_body = "邮件正文很长" * 500  # 3000+ 字符，肯定超过 chunk_size
    chunks = chunk_email(
        sender_name="Alice",
        sender_email="alice@example.com",
        subject="S",
        body_text=long_body,
        sent_at=None,
        thread_id=None,
        recipients=[],
        labels=[],
    )
    assert len(chunks) > 1
    assert chunks[0].metadata["chunk_index"] == 0
    assert chunks[1].metadata["chunk_index"] == 1


def test_chunk_document() -> None:
    chunks = chunk_document(
        text="段落一\n\n段落二" * 100,
        partition="contracts",
        source="manual",
        filename="contract.md",
    )
    assert len(chunks) >= 1
    assert chunks[0].metadata["partition"] == "contracts"
    assert chunks[0].metadata["filename"] == "contract.md"


# ---------- RRF 融合 ----------


def _mk_chunk(idx: int, score: float = 0.5) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid.UUID(int=idx),
        partition="inbox",
        source="email",
        content=f"chunk {idx}",
        metadata={"sender": "x@y.com"},
        score=score,
        vector_rank=None,
        bm25_rank=None,
    )


def test_rrf_fuse_intersect() -> None:
    """向量 + BM25 各返回 3 条，其中 2 条重叠 → 融合后 4 条，重叠项排前。"""
    a = [_mk_chunk(1), _mk_chunk(2), _mk_chunk(3)]  # vector
    b = [_mk_chunk(2), _mk_chunk(3), _mk_chunk(4)]  # bm25
    fused = _rrf_fuse(a, b, k=60)
    assert len(fused) == 4
    # 2 和 3 在两个列表都出现，融合分数更高
    ids = [c.chunk_id for c in fused]
    assert ids[0] in {uuid.UUID(int=2), uuid.UUID(int=3)}
    assert ids[1] in {uuid.UUID(int=2), uuid.UUID(int=3)}
    # 1 和 4 各只在一边
    assert uuid.UUID(int=1) in ids
    assert uuid.UUID(int=4) in ids


def test_rrf_fuse_only_vector() -> None:
    a = [_mk_chunk(1), _mk_chunk(2)]
    fused = _rrf_fuse(a, [], k=60)
    assert len(fused) == 2
    assert all(c.bm25_rank is None for c in fused)


def test_rrf_fuse_only_bm25() -> None:
    b = [_mk_chunk(1), _mk_chunk(2)]
    fused = _rrf_fuse([], b, k=60)
    assert len(fused) == 2
    assert all(c.vector_rank is None for c in fused)
    assert fused[0].bm25_rank == 1


def test_rrf_fuse_empty() -> None:
    assert _rrf_fuse([], []) == []
