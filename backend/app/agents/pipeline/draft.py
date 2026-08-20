"""辅助起草回复 Agent（PipelineAgent）。"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.schemas import DraftInput, DraftOutput
from app.agents.pipeline.base import PipelineAgent

SYSTEM_PROMPT = """你是 DeepMail 助手，根据用户指示起草一封回复邮件。

约束：
- 仅输出草稿正文（不含 From/To/Subject 行），用纯文本。
- **回复语言必须与原邮件保持一致**：原邮件是中文就中文回复，英文就英文回复，日文就日文回复；不要强行翻译。
- 按 tone（formal/casual/auto）控制语气；auto 时按邮件主题与发件人关系自动选择。
- 不要照抄原邮件；用合适的开场、收尾与签名。
- 起草要简洁，3-8 段为佳。
- 列出 key_points（≤5）说明起草覆盖的核心要点。

draft_text 中可以引用原邮件的关键信息，但不要大段复述。

{PERSONA_BLOCK}"""


class DraftAgent(PipelineAgent[DraftInput, DraftOutput]):
    name = "draft"
    input_schema = DraftInput
    output_schema = DraftOutput

    def build_messages(self, inp: DraftInput):  # type: ignore[override]
        history = inp.history_text or "（无历史邮件）"
        persona_block = inp.persona or ""
        system = SYSTEM_PROMPT.replace("{PERSONA_BLOCK}", persona_block)
        user = (
            f"用户指示：{inp.instruction}\n"
            f"语气：{inp.tone}\n\n"
            f"=== 与该联系人的历史邮件 ===\n{history}\n\n"
            f"=== 待回复的原邮件 ===\n"
            f"主题：{inp.subject}\n\n"
            f"正文：\n{inp.body_text}\n"
        )
        return [SystemMessage(content=system), HumanMessage(content=user)]

    def parse_from_markdown(self, text: str) -> DraftOutput | None:
        """兜底：把 LLM 整段输出（去 think）作为 draft_text。"""
        from app.agents.pipeline.base import _strip_think

        cleaned = _strip_think(text).strip()
        if not cleaned:
            return None
        # 提取 markdown 标题后的正文，过滤掉 "**要点：**" 列表
        lines = [ln for ln in cleaned.splitlines() if ln.strip()]
        body_lines = []
        for ln in lines:
            if ln.startswith("**") and ("要点" in ln or "关键点" in ln):
                break
            if ln.startswith("#"):
                continue
            body_lines.append(ln)
        draft_text = "\n".join(body_lines).strip() or cleaned
        return DraftOutput(
            draft_text=draft_text,
            key_points=[],
            confidence=0.7,
        )
