"""/api/knowledge/* 路由。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models.user import User
from app.db.session import get_db
from app.services import knowledge_service

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# ---------- 分区 ----------


@router.get("/partitions")
async def list_partitions(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await knowledge_service.list_partitions(db, current.id)


@router.delete("/partitions/{partition}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_partition(
    partition: str,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        await knowledge_service.delete_partition(db, current.id, partition)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


# ---------- 文档上传 ----------

SUPPORTED_TEXT_SUFFIXES = {".txt", ".md"}


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    partition: str = Form(...),
    file: UploadFile = File(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """上传纯文本 / markdown 到指定分区。"""
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")
    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in SUPPORTED_TEXT_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported type {suffix}. supported: {SUPPORTED_TEXT_SUFFIXES}",
        )
    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        try:
            content = raw.decode("gbk")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="file must be utf-8 or gbk text")

    n = await knowledge_service.index_document(
        db,
        current.id,
        partition=partition,
        filename=file.filename,
        content=content,
    )
    return {"partition": partition, "filename": file.filename, "chunks_indexed": n}


# ---------- 索引 ----------


@router.post("/index/emails", status_code=status.HTTP_200_OK)
async def index_emails(
    limit: int = Query(default=1000, ge=1, le=10000),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    n = await knowledge_service.index_emails(db, current.id, limit=limit)
    return {"chunks_indexed": n}


@router.post("/index/emails/{email_id}", status_code=status.HTTP_200_OK)
async def index_email(
    email_id: uuid.UUID,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    n = await knowledge_service.index_email(db, current.id, email_id)
    return {"chunks_indexed": n}


# ---------- 检索 ----------


class SearchRequest(BaseModel):
    query: str
    partition: str | None = None
    top_k: int = 5
    use_rerank: bool = True


@router.post("/search")
async def search(
    payload: SearchRequest,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    hits = await knowledge_service.search(
        db,
        current.id,
        query=payload.query,
        partition=payload.partition,
        top_k=payload.top_k,
        use_rerank=payload.use_rerank,
    )
    return {"hits": hits, "total": len(hits)}


# ---------- 统计 ----------


@router.get("/stats")
async def stats(
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await knowledge_service.stats(db, current.id)
