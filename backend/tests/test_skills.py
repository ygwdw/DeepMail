"""7 个 Skill 的单测（用 Mock LLM）。"""

from __future__ import annotations

import pytest
from app.agents.schemas import (
    ClassifyInput,
    DraftInput,
    EmailInput,
    TagInput,
)
from app.agents.skills import (
    ClassifySkill,
    DraftSkill,
    EntityExtractSkill,
    SpamSkill,
    SummarySkill,
    TagRecommendSkill,
    TodoExtractSkill,
)
from app.llm.mock import MockLLM, register_default_responses


@pytest.fixture
def mock_llm() -> MockLLM:
    m = MockLLM()
    register_default_responses(m)
    return m


# ---- 1. Summary ----


async def test_summary_skill(mock_llm: MockLLM) -> None:
    skill = SummarySkill()
    inp = EmailInput(
        subject="产品建议",
        body_text="希望增加暗黑模式、Excel 导出、离线缓存",
    )
    result = await skill.run(mock_llm, inp)
    assert result.ok, result.error
    assert "暗黑模式" in result.output.summary or len(result.output.summary) > 0
    assert 1 <= len(result.output.key_points) <= 5


# ---- 2. TodoExtract ----


async def test_todo_extract_skill(mock_llm: MockLLM) -> None:
    skill = TodoExtractSkill()
    inp = EmailInput(
        subject="产品建议",
        body_text="希望增加暗黑模式、Excel 导出、离线缓存",
    )
    result = await skill.run(mock_llm, inp)
    assert result.ok, result.error
    assert len(result.output) >= 1
    for t in result.output:
        assert t.content
        assert t.priority in ("low", "medium", "high")


# ---- 3. EntityExtract ----


async def test_entity_extract_skill(mock_llm: MockLLM) -> None:
    skill = EntityExtractSkill()
    inp = EmailInput(
        subject="产品建议",
        body_text="我是吴女士，在 Epsilon 公司，希望增加 Excel 导出",
    )
    result = await skill.run(mock_llm, inp)
    assert result.ok, result.error
    names = [e.name for e in result.output.entities]
    assert "吴女士" in names
    assert "Epsilon 公司" in names
    assert any(r.predicate == "works_at" for r in result.output.relations)


# ---- 4. Classify ----


async def test_classify_skill(mock_llm: MockLLM) -> None:
    skill = ClassifySkill()
    inp = ClassifyInput(
        subject="产品建议",
        body_text="希望增加暗黑模式",
        sender_email="wu@example.com",
        categories=[
            {
                "name": "常规",
                "description": "日常工作沟通",
                "rules_json": {},
                "is_spam_category": False,
                "is_system": True,
            },
            {
                "name": "广告推销",
                "description": "营销活动",
                "rules_json": {"keywords": ["促销"]},
                "is_spam_category": True,
                "is_system": True,
            },
        ],
    )
    result = await skill.run(mock_llm, inp)
    assert result.ok, result.error
    assert result.output.category_name == "常规"
    assert 0.0 <= result.output.confidence <= 1.0


def test_classify_skill_prompt_includes_description() -> None:
    """classify skill 的 prompt 必须包含 description。"""
    skill = ClassifySkill()
    from app.agents.schemas import ClassifyInput

    inp = ClassifyInput(
        subject="x",
        body_text="y",
        sender_email="x@y.com",
        categories=[
            {"name": "常规", "description": "日常工作沟通", "rules_json": {}},
            {"name": "广告推销", "description": "营销活动", "rules_json": {}},
        ],
    )
    messages = skill.build_messages(inp)
    user_msg = messages[1].content
    assert "日常工作沟通" in user_msg
    assert "营销活动" in user_msg


# ---- 5. Tag ----


async def test_tag_recommend_skill(mock_llm: MockLLM) -> None:
    skill = TagRecommendSkill()
    inp = TagInput(
        subject="产品建议",
        body_text="希望增加暗黑模式",
        sender_email="wu@example.com",
        existing_labels=[
            {"name": "work", "description": "工作相关"},
            {"name": "personal", "description": ""},
        ],
    )
    result = await skill.run(mock_llm, inp)
    assert result.ok, result.error
    assert any(m.name == "work" for m in result.output.existing_label_matches)


def test_tag_skill_prompt_includes_label_description() -> None:
    """tag skill 的 prompt 必须包含现有 label 的 description。"""
    skill = TagRecommendSkill()
    from app.agents.schemas import TagInput

    inp = TagInput(
        subject="x",
        body_text="y",
        sender_email="x@y.com",
        existing_labels=[
            {"name": "work", "description": "工作相关邮件"},
            {"name": "personal", "description": ""},
        ],
    )
    messages = skill.build_messages(inp)
    user_msg = messages[1].content
    assert "work" in user_msg
    assert "工作相关邮件" in user_msg


# ---- 6. Spam ----


async def test_spam_skill(mock_llm: MockLLM) -> None:
    skill = SpamSkill()
    inp = EmailInput(
        subject="正常业务邮件",
        body_text="请查收合同",
        sender_email="partner@real-corp.com",
    )
    result = await skill.run(mock_llm, inp)
    assert result.ok, result.error
    assert result.output.spam_score < 0.5
    assert result.output.is_spam is False


# ---- 7. Draft ----


async def test_draft_skill(mock_llm: MockLLM) -> None:
    skill = DraftSkill()
    inp = DraftInput(
        instruction="礼貌拒绝并提议下周再约",
        tone="formal",
        sender_email="partner@real-corp.com",
        subject="下周见面",
        body_text="希望本周见面聊一下",
        history_text="邮件 1：上次见面聊了合作意向",
    )
    result = await skill.run(mock_llm, inp)
    assert result.ok, result.error
    assert len(result.output.draft_text) > 10
    assert result.output.confidence > 0


async def test_draft_skill_english_input(mock_llm: MockLLM) -> None:
    """英文邮件应返回英文草稿（验证 mock fixture 切换 + prompt 语言指令）。"""
    # 注册一个英文 draft fixture
    mock_llm.set_response(
        "draft",
        {
            "draft_text": "Thanks for your feedback. We have noted the three suggestions.",
            "key_points": ["Thanks for feedback"],
            "confidence": 0.88,
        },
    )
    skill = DraftSkill()
    inp = DraftInput(
        instruction="Acknowledge and schedule a follow-up",
        tone="formal",
        sender_email="partner@us-corp.com",
        subject="Product feedback",
        body_text="We have some feedback on your product dark mode and offline cache.",
        history_text="Email 1: discussed partnership",
    )
    result = await skill.run(mock_llm, inp)
    assert result.ok, result.error
    # 英文 mock 输出
    assert "Thanks" in result.output.draft_text or "Hi" in result.output.draft_text


def test_draft_skill_prompt_includes_language_instruction() -> None:
    """draft skill 的 system prompt 必须明确要求按原邮件语言回复。"""
    skill = DraftSkill()
    messages = skill.build_messages(
        DraftInput(
            instruction="x",
            tone="auto",
            sender_email="x@y.com",
            subject="x",
            body_text="y",
            history_text="",
        )
    )
    sys_msg = messages[0].content
    assert "回复语言必须与原邮件保持一致" in sys_msg, sys_msg
    assert "中文回复" in sys_msg
    assert "英文回复" in sys_msg


# ---- 错误隔离 ----


async def test_skill_handles_bad_response() -> None:
    """Mock LLM 未注册该 skill 的响应时应返回 error 而不抛异常。"""
    m = MockLLM()
    m._responses.clear()  # 模拟没注册
    skill = SummarySkill()
    inp = EmailInput(subject="x", body_text="y")
    result = await skill.run(m, inp)
    assert not result.ok
    assert result.error is not None
