"""AI 业务编排：调用 skill、落库、计算 folder。"""

from __future__ import annotations

import uuid
from typing import Any

from langchain_core.language_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schemas import (
    ClassifyInput,
    DraftInput,
    DraftOutput,
    EmailInput,
    EntityExtractOutput,
    SpamOutput,
    SummaryOutput,
    TagInput,
    TagRecommendOutput,
    TodoExtractOutput,
)
from app.agents.pipeline import (
    ClassifyAgent,
    DraftAgent,
    EntityExtractAgent,
    SpamAgent,
    SummaryAgent,
    TagRecommendAgent,
    TodoExtractAgent,
)
from app.agents.pipeline.base import PipelineResult
from app.db.models.email import Email
from app.db.models.label import Category, Label
from app.db.models.todo import Todo, TodoPriority, TodoStatus
from app.services.email_service import EmailService
from app.services.usage_service import record_usage

# ---------- 单 PipelineAgent 入口 ----------


async def run_summary(
    llm: BaseChatModel,
    db: AsyncSession,
    email: Email,
    user_id: uuid.UUID,
) -> PipelineResult[SummaryOutput]:
    skill = SummaryAgent()
    inp = EmailInput(subject=email.subject, body_text=email.body_text)
    result = await skill.run(llm, inp)
    if result.ok:
        email.summary = result.output.summary
        await db.flush()
    await record_usage(
        db,
        user_id=user_id,
        skill_name=skill.name,
        email_id=email.id,
        tokens_total=result.tokens_total,
        latency_ms=result.latency_ms,
        error=result.error,
    )
    return result


async def run_todo_extract(
    llm: BaseChatModel,
    db: AsyncSession,
    email: Email,
    user_id: uuid.UUID,
) -> PipelineResult[TodoExtractOutput]:
    skill = TodoExtractAgent()
    inp = EmailInput(subject=email.subject, body_text=email.body_text)
    result = await skill.run(llm, inp)
    if result.ok:
        # v2-M4.2: TodoExtractOutput 现在是 wrapper class（items 字段）
        # 兼容兜底解析（LLM 直接给裸 list 走 _parse_from_text 时仍是 list）
        items = getattr(result.output, "items", result.output)
        if not isinstance(items, list):
            items = []
        # 落库到 todos 表
        existing_stmt = select(Todo).where(Todo.email_id == email.id)
        for t in (await db.execute(existing_stmt)).scalars().all():
            await db.delete(t)
        for item in items:
            db.add(
                Todo(
                    user_id=user_id,
                    email_id=email.id,
                    content=item.content,
                    due_date=item.due_date,
                    status=TodoStatus.PENDING,
                    priority=TodoPriority(item.priority),
                )
            )
        email.todos_extracted = [t.model_dump(mode="json") for t in items]
        await db.flush()
    await record_usage(
        db,
        user_id=user_id,
        skill_name=skill.name,
        email_id=email.id,
        tokens_total=result.tokens_total,
        latency_ms=result.latency_ms,
        error=result.error,
    )
    return result


async def run_entity_extract(
    llm: BaseChatModel,
    db: AsyncSession,
    email: Email,
    user_id: uuid.UUID,
) -> PipelineResult[EntityExtractOutput]:
    from app.db.models.knowledge import Entity, Relation

    skill = EntityExtractAgent()
    inp = EmailInput(subject=email.subject, body_text=email.body_text)
    result = await skill.run(llm, inp)
    if result.ok:
        # v2-M4.2: 用 upsert 兼容并发场景（多个 email 同时提取到同名 entity）
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        for e in result.output.entities:
            stmt = pg_insert(Entity).values(
                user_id=user_id, name=e.name, type=e.type
            )
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["user_id", "name", "type"]
            )
            await db.execute(stmt)
        for r in result.output.relations:
            db.add(
                Relation(
                    user_id=user_id,
                    subject=r.subject,
                    predicate=r.predicate,
                    object=r.object,
                    confidence=r.confidence,
                    source_email_id=email.id,
                )
            )
        email.entities_extracted = [
            {"entities": [e.model_dump() for e in result.output.entities]},
            {"relations": [r.model_dump() for r in result.output.relations]},
        ]
        await db.flush()
    await record_usage(
        db,
        user_id=user_id,
        skill_name=skill.name,
        email_id=email.id,
        tokens_total=result.tokens_total,
        latency_ms=result.latency_ms,
        error=result.error,
    )
    return result


async def run_classify(
    llm: BaseChatModel,
    db: AsyncSession,
    email: Email,
    user_id: uuid.UUID,
) -> PipelineResult[Any]:
    skill = ClassifyAgent()
    # 加载该用户所有分类
    cat_stmt = select(Category).where(Category.user_id == user_id)
    categories = (await db.execute(cat_stmt)).scalars().all()
    cat_inputs = [
        {
            "name": c.name,
            "description": c.description,
            "rules_json": c.rules_json,
            "is_spam_category": c.is_spam_category,
            "is_system": c.is_system,
        }
        for c in categories
    ]
    inp = ClassifyInput(
        subject=email.subject,
        body_text=email.body_text,
        sender_email=email.sender_email,
        sender_name=email.sender_name,
        categories=cat_inputs,  # type: ignore[arg-type]
    )
    result = await skill.run(llm, inp)
    if result.ok:
        chosen = result.output.category_name
        email.categories = [chosen]
        # 重算 folder
        email.folder = _compute_folder(email.categories, cat_inputs)  # type: ignore[arg-type]
        await db.flush()
    await record_usage(
        db,
        user_id=user_id,
        skill_name=skill.name,
        email_id=email.id,
        tokens_total=result.tokens_total,
        latency_ms=result.latency_ms,
        error=result.error,
    )
    return result


async def run_tag_recommend(
    llm: BaseChatModel,
    db: AsyncSession,
    email: Email,
    user_id: uuid.UUID,
) -> PipelineResult[TagRecommendOutput]:
    skill = TagRecommendAgent()
    label_stmt = select(Label).where(Label.user_id == user_id)
    existing_rows = (await db.execute(label_stmt)).scalars().all()
    existing = [{"name": lb.name, "description": lb.description} for lb in existing_rows]
    inp = TagInput(
        subject=email.subject,
        body_text=email.body_text,
        sender_email=email.sender_email,
        sender_name=email.sender_name,
        existing_labels=existing,  # type: ignore[arg-type]
    )
    result = await skill.run(llm, inp)
    await record_usage(
        db,
        user_id=user_id,
        skill_name=skill.name,
        email_id=email.id,
        tokens_total=result.tokens_total,
        latency_ms=result.latency_ms,
        error=result.error,
    )
    return result


async def run_spam(
    llm: BaseChatModel,
    db: AsyncSession,
    email: Email,
    user_id: uuid.UUID,
) -> PipelineResult[SpamOutput]:
    skill = SpamAgent()
    inp = EmailInput(
        subject=email.subject,
        body_text=email.body_text,
        sender_email=email.sender_email,
        sender_name=email.sender_name,
    )
    result = await skill.run(llm, inp)
    if result.ok:
        email.spam_score = result.output.spam_score
        await db.flush()
    await record_usage(
        db,
        user_id=user_id,
        skill_name=skill.name,
        email_id=email.id,
        tokens_total=result.tokens_total,
        latency_ms=result.latency_ms,
        error=result.error,
    )
    return result


async def run_draft(
    llm: BaseChatModel,
    db: AsyncSession,
    email: Email,
    user_id: uuid.UUID,
    *,
    instruction: str,
    tone: str = "auto",
) -> PipelineResult[DraftOutput]:
    skill = DraftAgent()
    history_text = await _build_history_text(db, email, user_id)
    # 注入 persona（人格画像）→ 起草风格贴合用户
    from app.services.persona_service import get_or_create_persona, persona_to_prompt_block

    persona = await get_or_create_persona(db, user_id)
    persona_block = persona_to_prompt_block(persona.profile_json)
    inp = DraftInput(
        instruction=instruction,
        tone=tone,  # type: ignore[arg-type]
        sender_email=email.sender_email,
        subject=email.subject,
        body_text=email.body_text,
        history_text=history_text,
        persona=persona_block,
    )
    result = await skill.run(llm, inp)
    await record_usage(
        db,
        user_id=user_id,
        skill_name=skill.name,
        email_id=email.id,
        tokens_total=result.tokens_total,
        latency_ms=result.latency_ms,
        error=result.error,
    )
    return result


async def apply_tag_recommend(
    db: AsyncSession,
    email: Email,
    result: "PipelineResult[TagRecommendOutput] | None",
    *,
    min_confidence: float = 0.6,
) -> None:
    """v2-M12: 把 tag_recommend 结果落库到 email.labels（多选，覆盖旧值）。

    只采用 existing_label_matches（已存在的标签），confidence ≥ min_confidence。
    recommended_new_labels 不自动建（需要用户确认），避免标签爆炸。
    """
    if result is None or not result.ok:
        return
    try:
        matches = result.output.existing_label_matches or []
        kept = [m.name for m in matches if m.confidence >= min_confidence]
    except Exception:
        return
    email.labels = kept  # 覆盖旧标签（重新打标语义）
    await db.flush()


async def reclassify_emails(
    llm: BaseChatModel,
    db: AsyncSession,
    user_id: uuid.UUID,
    email_ids: list[uuid.UUID],
    *,
    do_tag: bool = True,
) -> dict:
    """v2-M12: 批量重新分类/打标。

    对每封邮件：
    1. run_classify → 更新 email.categories（单选覆盖）+ folder 重算
    2. 若 do_tag → run_tag_recommend → apply_tag_recommend 落 email.labels（多选覆盖）

    逐封串行（每封 2 次 LLM 调用），避免并发触发限流。
    """
    processed = 0
    failed: list[dict] = []
    for eid in email_ids:
        try:
            email = (
                await db.execute(select(Email).where(Email.id == eid, Email.user_id == user_id))
            ).scalar_one_or_none()
            if email is None:
                failed.append({"email_id": str(eid), "error": "not found"})
                continue
            cls_result = await run_classify(llm, db, email, user_id)
            if not cls_result.ok:
                failed.append({"email_id": str(eid), "error": cls_result.error or "classify failed"})
                continue
            if do_tag:
                tag_result = await run_tag_recommend(llm, db, email, user_id)
                await apply_tag_recommend(db, email, tag_result)
            processed += 1
        except Exception as exc:
            failed.append({"email_id": str(eid), "error": f"{type(exc).__name__}: {exc}"})
    await db.commit()
    return {"processed": processed, "failed": failed}


# ---------- Process 全量 ----------


async def run_process(
    llm: BaseChatModel,
    db: AsyncSession,
    email: Email,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    """跑 5 项自动 skill：classify → summary → spam → todo_extract → entity_extract。
    draft 与 tag_recommend 不在此处跑（需用户主动调用）。"""
    items: list[dict[str, Any]] = []
    by_skill: dict[str, dict[str, int]] = {}
    failures: list[dict[str, str]] = []
    total_calls = 0
    total_tokens = 0
    total_latency = 0

    runners: list[tuple[str, Any]] = [
        ("classify", run_classify),
        ("summary", run_summary),
        ("spam", run_spam),
        ("todo_extract", run_todo_extract),
        ("entity_extract", run_entity_extract),
    ]

    for skill_name, runner in runners:
        result = await runner(llm, db, email, user_id)
        output_payload = _serialize_output(result.output) if result.ok else None
        item = {
            "skill": skill_name,
            "output": output_payload,
            "tokens_used": result.tokens_total,
            "latency_ms": result.latency_ms,
            "error": result.error,
        }
        items.append(item)
        by_skill[skill_name] = {
            "calls": 1,
            "tokens": result.tokens_total,
            "latency_ms": result.latency_ms,
        }
        total_calls += 1
        total_tokens += result.tokens_total
        total_latency += result.latency_ms
        if not result.ok:
            failures.append({"skill": skill_name, "error": result.error or "unknown"})

    await db.commit()

    return {
        "email_id": str(email.id),
        "results": items,
        "summary": {
            "total_llm_calls": total_calls,
            "total_tokens": total_tokens,
            "total_latency_ms": total_latency,
            "by_skill": by_skill,
            "failures": failures,
        },
    }


# ---------- helpers ----------


def _serialize_output(output: Any) -> Any:
    """统一序列化：BaseModel → dict；list[BaseModel] → list[dict]；其他原样。"""
    if output is None:
        return None
    if hasattr(output, "model_dump"):
        return output.model_dump(mode="json")
    if isinstance(output, list):
        return [o.model_dump(mode="json") if hasattr(o, "model_dump") else o for o in output]
    return output


def _compute_folder(categories: list[str], all_categories: list[dict]) -> str:
    """如果邮件的分类中包含任一 is_spam_category=true 的分类，folder=spam。"""
    spam_names = {c["name"] for c in all_categories if c.get("is_spam_category")}
    if any(c in spam_names for c in categories):
        return "spam"
    return "inbox"


async def _build_history_text(db: AsyncSession, email: Email, user_id: uuid.UUID) -> str:
    """对该发件人的历史邮件构建上下文（最近 20 封拿正文，更早的只取 summary）。"""
    EmailService(db, provider=None)  # type: ignore[arg-type]
    # 直接用 SQL 取同 sender_email 的邮件
    stmt = (
        select(Email)
        .where(
            Email.user_id == user_id,
            Email.sender_email == email.sender_email,
            Email.id != email.id,
        )
        .order_by(Email.received_at.desc())
        .limit(50)
    )
    rows = list((await db.execute(stmt)).scalars().all())

    MAX_FULL = 20
    head = rows[:MAX_FULL]
    tail = rows[MAX_FULL:]

    parts: list[str] = []
    for i, e in enumerate(head, 1):
        parts.append(
            f"邮件 {i}（{e.received_at.strftime('%Y-%m-%d %H:%M')}）\n"
            f"主题：{e.subject}\n{e.body_text}\n"
        )
    for e in tail:
        summary_part = e.summary or "（无摘要）"
        parts.append(
            f"早期邮件（{e.received_at.strftime('%Y-%m-%d')}）：{e.subject} | 摘要：{summary_part}\n"
        )
    return "\n".join(parts) if parts else "（无历史邮件）"
