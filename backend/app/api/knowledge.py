"""/api/knowledge/* 路由。"""

from __future__ import annotations

import io
import uuid
import zipfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.logging import get_logger
from app.db.models.user import User
from app.db.session import get_db
from app.services import knowledge_service

_logger = get_logger(__name__)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# ---------- 分区 CRUD ----------


class PartitionRename(BaseModel):
    old_name: str
    new_name: str


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


@router.post("/partitions/rename", status_code=status.HTTP_200_OK)
async def rename_partition(
    payload: PartitionRename,
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """v2-M4.4: 重命名分区（同步改所有 chunk.partition 字段）。"""
    n = await knowledge_service.rename_partition(
        db, current.id, payload.old_name, payload.new_name
    )
    return {
        "renamed_chunks": n,
        "old_name": payload.old_name,
        "new_name": payload.new_name,
    }


# ---------- 文档上传 ----------

SUPPORTED_TEXT_SUFFIXES = {".txt", ".md"}


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    partition: str = Form(...),
    file: UploadFile = File(...),
    current: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """上传纯文本 / markdown / zip 到指定分区。

    v2-M4.4: 支持 zip 解压遍历 .txt/.md。
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="filename required")
    name_lower = file.filename.lower()
    raw = await file.read()
    if name_lower.endswith(".zip"):
        # v2-M4.4: zip 解压 → 遍历 .txt/.md 索引
        try:
            zf = zipfile.ZipFile(io.BytesIO(raw))
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="invalid zip file")
        total = 0
        files_indexed: list[str] = []
        for inner in zf.namelist():
            inner_lower = inner.lower()
            if not (inner_lower.endswith(".txt") or inner_lower.endswith(".md")):
                continue
            try:
                text_bytes = zf.read(inner)
                try:
                    content = text_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    content = text_bytes.decode("gbk", errors="ignore")
            except Exception as exc:
                _logger.warning("zip_member_skip", name=inner, error=str(exc))
                continue
            n = await knowledge_service.index_document(
                db,
                current.id,
                partition=partition,
                filename=inner.split("/")[-1],
                content=content,
                doc_id=f"zip:{file.filename}:{inner}",
            )
            if n > 0:
                files_indexed.append(inner)
            total += n
        return {
            "partition": partition,
            "filename": file.filename,
            "chunks_indexed": total,
            "files_indexed": files_indexed,
            "kind": "zip",
        }
    # 单 txt/md
    suffix = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if suffix not in SUPPORTED_TEXT_SUFFIXES:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported type {suffix}. supported: {SUPPORTED_TEXT_SUFFIXES}",
        )
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
    return {
        "partition": partition,
        "filename": file.filename,
        "chunks_indexed": n,
        "kind": "file",
    }


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
