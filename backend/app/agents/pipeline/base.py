"""PipelineAgent 抽象基类：单点 AI 能力 agent（非编排型 sub-agent）。

原 Skill 命名（v2-P4 改为 agent）：每个 PipelineAgent 接收输入 → 调 LLM
（优先 structured output，失败兜底文本解析）→ 返回结构化结果。
区别于 LangGraph 的 sub-agent（email/todo/draft/rag/tidy 那些编排 agent）。
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from app.llm.mock import reset_current_mock_key, set_current_mock_key

TIn = TypeVar("TIn", bound=BaseModel)
TOut = TypeVar("TOut")


# 公共 prompt 追加：强制 LLM 输出 JSON（防止它输出 markdown）
JSON_ONLY_SUFFIX = """

【输出格式硬约束】
- 必须输出**纯 JSON**，不要 ``` 包裹，不要任何 markdown 标题/列表/解释文字。
- JSON 顶层 key 必须严格匹配 schema 字段。
- 列表场景直接输出 JSON 数组，`[{"key": "value"}, ...]`。
- 如果需要思考，请在思考之前完成 JSON 输出（或使用  块包裹思考）。"""

_THINK_RE = re.compile(r"<\s*think\b.*?<\s*/\s*think\s*>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def _strip_think(text: str) -> str:
    return _THINK_RE.sub("", text)


def _strip_code_fence(text: str) -> str:
    return _FENCE_RE.sub("", text).strip()


def _extract_json(text: str) -> str:
    """从夹杂文本中提取第一个 JSON 块（优先 []，其次 {}）。"""
    cleaned = _strip_think(text)
    cleaned = _strip_code_fence(cleaned)
    # v2-M4.2: 优先找数组（顶层 list），避免 list[{}] 时只取首个 dict
    for opener, closer in [("[", "]"), ("{", "}")]:
        start = cleaned.find(opener)
        if start == -1:
            continue
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(cleaned)):
            ch = cleaned[i]
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return cleaned[start : i + 1]
    return cleaned


@dataclass
class PipelineResult[TOut]:
    """单次 PipelineAgent 执行结果。"""

    output: TOut | None
    tokens_prompt: int = 0
    tokens_completion: int = 0
    latency_ms: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.output is not None

    @property
    def tokens_total(self) -> int:
        return self.tokens_prompt + self.tokens_completion


class PipelineAgent[TIn: BaseModel, TOut](ABC):
    """所有单点 AI 能力 agent 的抽象基类（v2-P4 由 Skill 改名）。"""

    name: str = "pipeline_agent"
    input_schema: type[TIn]
    output_schema: type[TOut]

    @property
    def mock_response_key(self) -> str:
        return self.name

    @abstractmethod
    def build_messages(self, inp: TIn) -> list[BaseMessage]: ...

    def post_process(self, output: TOut) -> TOut:
        return output

    def _finalize_prompt(self, system: str) -> str:
        """在子类 system prompt 末尾追加 JSON 硬约束 + 当前时间。"""
        from app.memory.time_context import inject_time_to_prompt

        return inject_time_to_prompt(system + JSON_ONLY_SUFFIX)

    async def run(self, llm: BaseChatModel, inp: TIn) -> PipelineResult[TOut]:
        """主入口：调用 LLM 并返回 PipelineResult。

        策略：
        1. 优先尝试 `with_structured_output`（Mock LLM 与支持 tool calling 的模型）
        2. 失败时兜底：直接调 LLM 拿 str，清理 think 块 + 提取 JSON + Pydantic 解析
        """
        t0 = time.perf_counter()
        token = set_current_mock_key(self.mock_response_key)
        try:
            messages = self._finalize_messages(self.build_messages(inp))
            try:
                structured = llm.with_structured_output(self.output_schema)
                raw = await structured.ainvoke(messages)
                output = self._coerce_output(raw)
            except Exception:
                # 兜底：直接拿 raw str（适配 thinking model）
                response = await llm.ainvoke(messages)
                content = response.content if hasattr(response, "content") else str(response)
                output = self._parse_from_text(content)

            output = self.post_process(output)
            latency = int((time.perf_counter() - t0) * 1000)
            return PipelineResult[TOut](output=output, latency_ms=latency)
        except Exception as exc:
            latency = int((time.perf_counter() - t0) * 1000)
            return PipelineResult[TOut](
                output=None,
                latency_ms=latency,
                error=f"{type(exc).__name__}: {exc}",
            )
        finally:
            reset_current_mock_key(token)

    def _finalize_messages(self, messages: list[BaseMessage]) -> list[BaseMessage]:
        """在最后一条 system message 末尾追加 JSON 硬约束（如果存在）。"""
        if not messages:
            return messages
        # 找到最后一个 SystemMessage
        for i in range(len(messages) - 1, -1, -1):
            if isinstance(messages[i], SystemMessage):
                messages[i].content = self._finalize_prompt(messages[i].content)
                return messages
        # 没有 system message：插入一条
        return [SystemMessage(content=self._finalize_prompt(""))] + list(messages)

    def _coerce_output(self, raw: object) -> TOut:
        if isinstance(raw, BaseModel):
            return raw  # type: ignore[return-value]
        if isinstance(raw, dict):
            return self.output_schema(**raw)  # type: ignore[return-value]
        if isinstance(raw, list):
            # v2-M4.2: 兼容 LLM 返回裸 list 的场景
            # 通用：找 wrapper class 第一个 list 字段，把 list 装进去
            if isinstance(self.output_schema, type) and issubclass(self.output_schema, BaseModel):
                wrapped = self._try_wrap_list(raw)
                if wrapped is not None:
                    return wrapped  # type: ignore[return-value]
            return raw  # type: ignore[return-value]
        if isinstance(raw, str):
            return self._parse_from_text(raw)
        content = getattr(raw, "content", None)
        if isinstance(content, str):
            return self._parse_from_text(content)
        raise ValidationError.from_exception_data(
            self.output_schema.__name__,
            [{"type": "value_error", "input": raw, "ctx": {"error": "unsupported raw type"}}],
        )

    def _try_wrap_list(self, raw: list) -> object | None:
        """v2-M4.2: 把裸 list 包成 wrapper class。

        启发式：取 wrapper class 第一个 list[...] 类型的字段，把 raw 装进去；
        同 schema 内其他 list 字段默认为空 list（让 Pydantic 用 default_factory）。
        """
        if not (isinstance(self.output_schema, type) and issubclass(self.output_schema, BaseModel)):
            return None
        target_field: str | None = None
        for name, f in self.output_schema.model_fields.items():
            ann = getattr(f, "annotation", None)
            origin = getattr(ann, "__origin__", None)
            if origin in (list, list) or ann is list:
                target_field = name
                break
        if target_field is None:
            return None
        try:
            return self.output_schema(**{target_field: raw})  # type: ignore[arg-type]
        except Exception:
            try:
                return self.output_schema(items=raw) if "items" in self.output_schema.model_fields else None  # type: ignore[arg-type]
            except Exception:
                return None

    def _parse_from_text(self, text: str) -> TOut:
        """从 raw text 解析：(1) JSON 提取 (2) markdown 兜底"""
        # 1. JSON 提取
        try:
            json_text = _extract_json(text)
            data = json.loads(json_text)
            if isinstance(data, list):
                # v2-M4.2: 兼容裸 list → wrapper class（启发式：第一个 list 字段）
                wrapped = self._try_wrap_list(data)
                if wrapped is not None:
                    return wrapped  # type: ignore[return-value]
                return data  # type: ignore[return-value]
            return self.output_schema(**data)  # type: ignore[return-value]
        except Exception:
            pass
        # 2. markdown 兜底（每 skill 自行实现）
        result = self.parse_from_markdown(text)
        if result is not None:
            return result
        # 3. 都失败
        raise ValueError(
            f"Could not parse LLM output as JSON or markdown.\nOutput preview: {text[:300]!r}"
        )

    def parse_from_markdown(self, text: str) -> TOut | None:
        """子类可覆盖：处理 LLM 输出 Markdown 格式（不支持 tool calling 的模型）。

        返回 None 表示不支持 markdown 解析。
        """
        return None
