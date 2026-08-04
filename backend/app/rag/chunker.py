"""文本 chunk 策略。

- 邮件：单封 < 2000 字 → 1 chunk；>= 2000 字 → 滑动窗口 800/120
- 文档：滑动窗口 800/120
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class TextChunk:
    text: str
    metadata: dict


def chunk_text(text: str, *, chunk_size: int = 800, overlap: int = 120) -> list[str]:
    """滑动窗口切分（中文字符也是 1 长度，所以 800 字符 ≈ 800 字）。"""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def chunk_email(
    *,
    sender_name: str | None,
    sender_email: str,
    subject: str,
    body_text: str,
    sent_at: str | None,
    thread_id: str | None,
    recipients: list[str],
    labels: list[str],
    chunk_size: int = 800,
    overlap: int = 120,
) -> list[TextChunk]:
    """邮件 → chunks（带 payload 元数据）。"""
    header = (
        f"主题：{subject}\n"
        f"发件人：{sender_name or ''} <{sender_email}>\n"
        f"收件人：{', '.join(recipients)}\n"
        f"日期：{(sent_at or '')}\n"
        f"标签：{', '.join(labels) if labels else ''}\n"
        f"\n---\n"
    )
    body = body_text or ""
    full = (header + body).strip()
    if len(full) <= chunk_size:
        return [
            TextChunk(
                text=full,
                metadata={
                    "sender": sender_email,
                    "subject": subject,
                    "date": sent_at,
                    "thread_id": thread_id,
                    "labels": labels,
                },
            )
        ]
    # 滑动窗口：header 只在第一块出现
    chunks = chunk_text(body, chunk_size=chunk_size - len(header), overlap=overlap)
    out: list[TextChunk] = []
    for i, c in enumerate(chunks):
        if i == 0:
            text = header + c
        else:
            text = f"（续上文）\n{c}"
        out.append(
            TextChunk(
                text=text,
                metadata={
                    "sender": sender_email,
                    "subject": subject,
                    "date": sent_at,
                    "thread_id": thread_id,
                    "labels": labels,
                    "chunk_index": i,
                },
            )
        )
    return out


def chunk_document(
    *,
    text: str,
    partition: str,
    source: str,
    filename: str | None = None,
    chunk_size: int = 800,
    overlap: int = 120,
) -> list[TextChunk]:
    """文档 → chunks。"""
    parts = chunk_text(text, chunk_size=chunk_size, overlap=overlap)
    out: list[TextChunk] = []
    for i, c in enumerate(parts):
        out.append(
            TextChunk(
                text=c,
                metadata={
                    "partition": partition,
                    "source": source,
                    "filename": filename,
                    "chunk_index": i,
                },
            )
        )
    return out


def iter_chunks(texts: list[str]) -> Iterator[tuple[int, str]]:
    """便捷：返回 (原 index, chunk) 对。"""
    yield from enumerate(texts)
