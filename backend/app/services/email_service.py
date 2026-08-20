"""邮件业务：从 Provider 读取 + 落库 + 提供查询。"""

from __future__ import annotations

import uuid
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models.email import Email
from app.services.email_provider.base import EmailPayload, EmailProvider

_logger = get_logger(__name__)


class EmailService:
    def __init__(self, db: AsyncSession, provider: EmailProvider) -> None:
        self._db = db
        self._provider = provider

    async def list_emails(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Email]:
        stmt = (
            select(Email)
            .where(Email.user_id == user_id)
            .order_by(Email.received_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list((await self._db.execute(stmt)).scalars().all())

    async def get_email(self, user_id: uuid.UUID, email_id: uuid.UUID) -> Email | None:
        stmt = select(Email).where(Email.user_id == user_id, Email.id == email_id)
        return (await self._db.execute(stmt)).scalar_one_or_none()

    async def count_emails(self, user_id: uuid.UUID) -> int:
        from sqlalchemy import func

        stmt = select(func.count(Email.id)).where(Email.user_id == user_id)
        return int((await self._db.execute(stmt)).scalar_one())

    async def send_email(
        self,
        user_id: uuid.UUID,
        *,
        to: list[str],
        subject: str,
        body_text: str,
        body_html: str | None = None,
        cc: list[str] | None = None,
    ) -> Email:
        """v2-M12: 发送邮件（provider.send_email）+ 存库（folder=sent）。

        返回落库后的 Email ORM。
        """
        payload = await self._provider.send_email(
            user_id,
            to=to,
            subject=subject,
            body_text=body_text,
            body_html=body_html,
        )
        email = Email(
            user_id=user_id,
            message_id=payload.message_id,
            thread_id=payload.thread_id,
            sender_name=payload.sender_name,
            sender_email=payload.sender_email,
            recipients=to,
            cc=cc or payload.cc or [],
            subject=subject,
            body_text=body_text,
            body_html=body_html,
            sent_at=payload.sent_at if payload.sent_at.tzinfo else payload.sent_at.replace(tzinfo=UTC),
            received_at=payload.received_at if payload.received_at.tzinfo else payload.received_at.replace(tzinfo=UTC),
            folder="sent",
            labels=[],
            categories=["常规"],
            raw_payload=payload.raw_payload,
        )
        self._db.add(email)
        await self._db.commit()
        await self._db.refresh(email)
        return email

    async def ensure_from_provider(self, user_id: uuid.UUID) -> int:
        """把 Provider 里的邮件按 user_id 同步进 DB（去重 by message_id）。返回新增条数。

        v2-M4.1: 入库后自动触发向量 + BM25 索引（让 rag agent 能用混合检索找邮件）
        v2-M4.2: 入库后异步跑 AI process（summary + todos + classify）
        v2-M3: IMAP 模式下走 onetime_sync_imap（最近 N 封，一次性）
        """
        # v2-M3: IMAP 模式分支
        from app.services.email_provider.imap_provider import IMAPEmailProvider

        if isinstance(self._provider, IMAPEmailProvider):
            return await self.onetime_sync_imap(user_id)

        payloads = await self._provider.list_emails(user_id, limit=1000, offset=0)
        existing_stmt = select(Email.message_id).where(Email.user_id == user_id)
        existing = {mid for mid in (await self._db.execute(existing_stmt)).scalars().all()}

        new_emails: list[Email] = []
        for p in payloads:
            if p.message_id in existing:
                continue
            email = _to_model(user_id, p)
            self._db.add(email)
            new_emails.append(email)
        # v2-M4.2: flush 一次让 ORM 生成 id，再 commit
        if new_emails:
            await self._db.flush()
            added_ids: list[uuid.UUID] = [e.id for e in new_emails if e.id is not None]
            await self._db.commit()
            # 入库后立即建索引（fire-and-forget 失败不影响主流程）
            await self._index_new_emails(user_id, added_ids)
            # v2-M4.2: 异步跑 AI process（后台 fire-and-forget，不阻塞同步）
            self._schedule_ai_process(user_id, added_ids)

        # v2-M4.1: 同步时同时把"已有但未索引"的邮件也补索引（兜底）
        await self._backfill_index(user_id, exclude_ids=existing)
        # 返回本次新增条数；全部已同步时 new_emails 为空，返回 0（修复 UnboundLocalError）
        return len(new_emails)

    async def onetime_sync_imap(
        self,
        user_id: uuid.UUID,
        *,
        force: bool = False,
    ) -> dict:
        """v2-M3: 一次性同步 IMAP 最近 N 封邮件。

        安全护栏：
        - 真实邮件 folder="real_inbox"（与 mock 的 inbox 区分）
        - 用 message_id 唯一约束去重（已入库邮件直接跳过）
        - force=False 时：若该用户已有 folder="real_inbox" 邮件，**直接拒绝**避免误触发
        - force=True 时：仍按 message_id 去重，但允许增量同步

        返回 {"fetched": N, "added": M, "skipped": K, "folder": "real_inbox"}
        """
        from app.services.email_provider.imap_provider import IMAPEmailProvider

        if not isinstance(self._provider, IMAPEmailProvider):
            raise ValueError("当前 Provider 不是 IMAP；设置 EMAIL_PROVIDER=imap")

        # 守护：已同步过则不重跑
        existing_stmt = (
            select(Email.id)
            .where(Email.user_id == user_id, Email.folder == "real_inbox")
            .limit(1)
        )
        already = (await self._db.execute(existing_stmt)).scalar_one_or_none()
        if already is not None and not force:
            return {
                "fetched": 0,
                "added": 0,
                "skipped": 0,
                "folder": "real_inbox",
                "skipped_reason": "already_synced",
            }

        # 拉邮件
        payloads = await self._provider.onetime_sync(user_id)
        if not payloads:
            return {"fetched": 0, "added": 0, "skipped": 0, "folder": "real_inbox"}

        # 去重
        msg_ids = [p.message_id for p in payloads]
        existing_stmt2 = select(Email.message_id).where(
            Email.user_id == user_id, Email.message_id.in_(msg_ids)
        )
        existing_ids = {
            mid for mid in (await self._db.execute(existing_stmt2)).scalars().all()
        }

        new_emails: list[Email] = []
        skipped = 0
        for p in payloads:
            if p.message_id in existing_ids:
                skipped += 1
                continue
            email = _to_model(user_id, p, folder="real_inbox")
            self._db.add(email)
            new_emails.append(email)

        if new_emails:
            await self._db.flush()
            added_ids: list[uuid.UUID] = [e.id for e in new_emails if e.id is not None]
            await self._db.commit()
            await self._index_new_emails(user_id, added_ids)
            self._schedule_ai_process(user_id, added_ids)

        return {
            "fetched": len(payloads),
            "added": len(new_emails),
            "skipped": skipped,
            "folder": "real_inbox",
        }

    def _schedule_ai_process(self, user_id: uuid.UUID, email_ids: list[uuid.UUID]) -> None:
        """v2-M4.2: 入库后异步跑 AI process（不阻塞主流程）。"""
        import asyncio

        from app.db.session import get_sessionmaker
        from app.llm.factory import get_chat_model
        from app.services.ai_service import run_process

        async def _run_one(eid: uuid.UUID) -> None:
            try:
                sm = get_sessionmaker()
                async with sm() as db:
                    em = (
                        await db.execute(
                            select(Email).where(Email.id == eid, Email.user_id == user_id)
                        )
                    ).scalar_one_or_none()
                    if em is None:
                        return
                    llm = await get_chat_model(db=db, user_id=user_id)
                    _logger.info("email_ai_process_start", email_id=str(eid))
                    await run_process(llm, db, em, user_id)
                    # v2-P2: 噪音邮件（广告/推销/验证码/垃圾/无实质内容）不提取 L2 topic
                    if await _should_extract_email_topics(db, em):
                        # v2-M4.1: 邮件入库后异步触发 L2 topic 提取（email 来源）
                        from app.memory.medium_term import extract_and_store_topics

                        user_msg = f"[邮件主题] {em.subject}\n\n[邮件正文]\n{em.body_text or ''}"
                        ai_msg = f"[摘要] {em.summary or ''}\n[分类] {','.join(em.categories or [])}"
                        try:
                            await extract_and_store_topics(
                                db,
                                user_id,
                                user_msg[:1000],
                                ai_msg[:500],
                                email_id=em.id,
                            )
                        except Exception as exc:
                            _logger.warning(
                                "email_topic_extract_fail",
                                email_id=str(eid),
                                error=str(exc),
                            )
                    await db.commit()
                    _logger.info("email_ai_process_done", email_id=str(eid))
            except Exception as exc:
                _logger.warning("email_ai_process_fail", error=str(exc), email_id=str(eid))

        async def _run_all():
            await asyncio.gather(*[_run_one(eid) for eid in email_ids], return_exceptions=True)

        try:
            asyncio.create_task(_run_all())
        except RuntimeError:
            # 没有 event loop（同步调用）；跳过
            pass

    async def _index_new_emails(self, user_id: uuid.UUID, email_ids: list[uuid.UUID]) -> None:
        """v2-M4.1: 单封入库后立即索引。失败不抛异常（fire-and-forget）。"""
        try:
            from app.services.knowledge_service import index_email

            for eid in email_ids:
                await index_email(self._db, user_id, eid)
        except Exception as exc:
            _logger.warning("email_index_fail", error=str(exc), count=len(email_ids))

    async def _backfill_index(self, user_id: uuid.UUID, *, exclude_ids: set[str]) -> None:
        """v2-M4.1: 兜底 — 把未在 knowledge_chunks 里的邮件补索引。"""
        try:
            from sqlalchemy import String, cast, select

            from app.db.models.knowledge import KnowledgeChunk
            from app.services.knowledge_service import index_email

            # 找出还没 chunk 的 email_id（用左连接 + IS NULL）
            # 注意 source_id 是 String 列，Email.id 是 UUID，需要 cast
            stmt = (
                select(Email.id)
                .outerjoin(
                    KnowledgeChunk,
                    (KnowledgeChunk.source_id == cast(Email.id, String))
                    & (KnowledgeChunk.source == "email")
                    & (KnowledgeChunk.user_id == user_id),
                )
                .where(Email.user_id == user_id)
                .where(KnowledgeChunk.id.is_(None))
                .limit(50)
            )
            ids = [row for row in (await self._db.execute(stmt)).scalars().all()]
            for eid in ids:
                await index_email(self._db, user_id, eid)
        except Exception as exc:
            _logger.warning("email_backfill_fail", error=str(exc))


async def _should_extract_email_topics(db: AsyncSession, email: Email) -> bool:
    """v2-P2: 判断邮件是否值得提取 L2 topic。

    广告/推销/验证码/垃圾（is_spam_category 或"一次性验证码"）或无实质正文 → 跳过，
    避免把噪音存进长期记忆。
    """
    body = (email.body_text or "").strip()
    if len(body) < 20:
        return False
    cats = email.categories or []
    if not cats:
        return True  # 未分类但有实质正文
    from sqlalchemy import select

    from app.db.models.label import Category

    rows = (
        await db.execute(
            select(Category).where(
                Category.user_id == email.user_id,
                Category.name.in_(cats),
            )
        )
    ).scalars().all()
    for c in rows:
        if c.is_spam_category or c.name == "一次性验证码":
            return False
    return True


def _to_model(user_id: uuid.UUID, p: EmailPayload, folder: str = "inbox") -> Email:
    return Email(
        user_id=user_id,
        message_id=p.message_id,
        thread_id=p.thread_id,
        sender_name=p.sender_name,
        sender_email=p.sender_email,
        recipients=p.recipients,
        cc=p.cc,
        subject=p.subject,
        body_text=p.body_text,
        body_html=p.body_html,
        sent_at=p.sent_at if p.sent_at.tzinfo else p.sent_at.replace(tzinfo=UTC),
        received_at=(
            p.received_at if p.received_at.tzinfo else p.received_at.replace(tzinfo=UTC)
        ),
        folder=folder,
        labels=p.labels,
        categories=p.categories,
        raw_payload=p.raw_payload,
    )
