"""真实 LLM 集成测试样例（与 Mock 测试并列）。

默认 skip；要跑只要在 .env 配置真实 LLM_API_KEY 即可。
- 有真实 LLM_API_KEY → 自动跑
- LLM_API_KEY 是空/占位值 → 自动 skip

运行：
    # 1. 在 .env 配真实 LLM_API_KEY（与 LLM_BASE_URL / LLM_CHAT_MODEL）
    # 2. 跑测试
    uv run python -m pytest tests/test_skills_real_llm.py -v -s

如果想强制 mock 模式（即使配了 key），可临时把 LLM_API_KEY 改回占位值。
"""

from __future__ import annotations

import asyncio

import pytest
from app.agents.schemas import DraftInput, EmailInput
from app.agents.skills import DraftSkill, SpamSkill, SummarySkill
from app.core.config import get_settings
from app.llm.factory import get_chat_model, is_mock_mode

pytestmark = pytest.mark.asyncio


def _should_run_real_llm() -> tuple[bool, str]:
    if is_mock_mode():
        return False, "LLM_API_KEY 未配置或为占位值（请在 .env 设置真实 key）"
    model = get_settings().llm_chat_model
    return True, f"model={model}"


_SKIP_REASON = _should_run_real_llm()[1] or "未启用"
skip_if_no_real_llm = pytest.mark.skipif(
    not _should_run_real_llm()[0],
    reason=f"真实 LLM 测试已禁用（{_SKIP_REASON}）",
)


# ---------- helpers ----------


async def _build_chat_model():
    """从工厂拿到真实 ChatModel。"""
    return await get_chat_model(db=None, user_id=None)


# ============================================================
# 测试 1：摘要
# ============================================================


@skip_if_no_real_llm
async def test_summary_with_real_llm():
    """真实 LLM 跑一次摘要：验证工厂 + with_structured_output + 中文输出。"""
    llm = await _build_chat_model()
    s = get_settings()
    print(f"\n  [config] provider={s.llm_provider} model={s.llm_chat_model} base={s.llm_base_url}")

    skill = SummarySkill()
    inp = EmailInput(
        subject="关于 V3.0 产品评审会议",
        body_text=(
            """各位同事/合作伙伴：

您好！

诚挚邀请您出席“202X年度Q3业务复盘与Q4战略规划会”，共同梳理阶段性成果，明确下一阶段目标与行动路径。

会议详情：

时间：​ 2022年3月5日（周X）14:00–16:30

地点：​ 公司三楼第一会议室 / 腾讯会议（ID：123 456 789）

议程：

Q3核心数据回顾与问题分析（14:00–15:00）

Q4重点项目规划与资源协调（15:00–16:00）

自由讨论与跨部门协作建议（16:00–16:30）
为确保会议高效，烦请您提前梳理本团队/本条线的Q3总结要点及Q4初步计划，如需演示材料，请于X月X日前发送至邮箱：xxx@company.com。
您的专业见解对本次会议至关重要，期待与您共商发展大计，为冲刺年度目标凝聚共识。
请于3月5日前点击链接[报名链接]确认参会，如有疑问请联系行政部小李（电话：138XXXX1234）。
顺颂商祺！
[公司名称] 行政部
202X年X月X日"""
        ),
    )
    result = await skill.run(llm, inp)
    assert result.ok, f"skill failed: {result.error}"
    print(f"result:{result}")
    print(f"  [summary] {result.output.summary}")
    print(f"  [key_points] {result.output.key_points}")

    assert len(result.output.summary) > 10
    assert 1 <= len(result.output.key_points) <= 5
    # 结构化字段类型
    assert isinstance(result.output.summary, str)
    assert all(isinstance(p, str) for p in result.output.key_points)


# ============================================================
# 测试 2：垃圾邮件（用户提到的例子）
# ============================================================


@skip_if_no_real_llm
async def test_spam_with_real_llm():
    """真实 LLM 跑一次垃圾邮件判定。"""
    llm = await _build_chat_model()
    skill = SpamSkill()
    inp = EmailInput(
        subject="正常业务邮件",
        body_text="请查收合同",
        sender_email="partner@real-corp.com",
    )
    result = await skill.run(llm, inp)
    assert result.ok, f"skill failed: {result.error}"

    print(f"\n  [spam_score] {result.output.spam_score}")
    print(f"  [is_spam] {result.output.is_spam}")
    print(f"  [reasons] {result.output.reasons}")

    assert 0.0 <= result.output.spam_score <= 1.0
    assert isinstance(result.output.is_spam, bool)
    # 正常业务邮件应该是低分
    assert result.output.spam_score < 0.5, f"业务邮件 spam_score 偏高: {result.output.spam_score}"


# ============================================================
# 测试 3：垃圾邮件 - 真实广告
# ============================================================


@skip_if_no_real_llm
async def test_spam_with_real_llm_promotion():
    """真实 LLM 识别促销邮件。"""
    llm = await _build_chat_model()
    skill = SpamSkill()
    inp = EmailInput(
        subject="🎉 天猫 88 会员节，全场 5 折起",
        body_text="全站 5 折起，叠加满 300 减 50 优惠券，更有 iPhone 限时抢购！",
        sender_email="promo@tmall.com",
    )
    result = await skill.run(llm, inp)
    assert result.ok, f"skill failed: {result.error}"

    print(f"\n  [promo spam_score] {result.output.spam_score}")
    print(f"  [promo is_spam] {result.output.is_spam}")

    # 广告邮件应该明显高于业务邮件（业务邮件 < 0.5），放宽到 0.3 避免模型波动
    assert result.output.spam_score > 0.3, f"广告邮件 spam_score 过低: {result.output.spam_score}"


# ============================================================
# 测试 4：草稿按发件人语言回复（中文邮件→中文回复）
# ============================================================


@skip_if_no_real_llm
async def test_draft_chinese_with_real_llm():
    """中文邮件应得到中文回复。"""
    llm = await _build_chat_model()
    skill = DraftSkill()
    inp = DraftInput(
        instruction="礼貌同意并确认时间",
        tone="formal",
        sender_email="partner@example-corp.com",
        subject="关于 V3.0 产品评审会议",
        body_text="邀请您参加 V3.0 大版本产品评审。时间：2026 年 8 月 6 日 14:00。",
        history_text="无历史邮件",
    )
    result = await skill.run(llm, inp)
    assert result.ok, f"skill failed: {result.error}"

    print(f"\n  [draft] {result.output.draft_text[:120]}...")

    draft = result.output.draft_text
    # 中文 draft 应包含中文字符
    has_chinese = any("一" <= c <= "鿿" for c in draft)
    assert has_chinese, f"中文邮件应得到中文回复，实际: {draft!r}"


# ============================================================
# 测试 5：草稿按发件人语言回复（英文邮件→英文回复）
# ============================================================


@skip_if_no_real_llm
async def test_draft_english_with_real_llm():
    """英文邮件应得到英文回复。"""
    llm = await _build_chat_model()
    skill = DraftSkill()
    inp = DraftInput(
        instruction="Acknowledge and schedule a follow-up next week",
        tone="formal",
        sender_email="partner@us-corp.com",
        subject="Q3 sync meeting",
        body_text="Hi, would you be available for a Q3 sync next Tuesday at 2pm?",
        history_text="No prior emails",
    )
    result = await skill.run(llm, inp)
    assert result.ok, f"skill failed: {result.error}"

    print(f"\n  [draft] {result.output.draft_text[:120]}")

    draft = result.output.draft_text
    # 英文 draft 应主要含英文（中文标点也允许，但中文汉字应极少）
    chinese_chars = sum(1 for c in draft if "一" <= c <= "鿿")
    assert chinese_chars < 5, f"英文邮件不应有大量中文，实际含 {chinese_chars} 个汉字: {draft!r}"


# ============================================================
# 调试时单独跑这个文件也能输出 Summary
# ============================================================


async def main():
    """脚本入口：uv run python tests/test_skills_real_llm.py"""
    enabled, info = _should_run_real_llm()
    if not enabled:
        print(f"[skip] {info}")
        return
    print(f"[run] {info}")

    llm = await _build_chat_model()
    skill = SummarySkill()
    result = await skill.run(llm, EmailInput(subject="hello", body_text="world"))
    print(f"summary.ok = {result.ok}")
    if result.ok:
        print(f"summary.output = {result.output.model_dump()}")
    else:
        print(f"summary.error = {result.error}")


if __name__ == "__main__":
    asyncio.run(main())
