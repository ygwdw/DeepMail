"""Mock LLM：不发真实请求，按 schema 返回预置 JSON。

用于单测 / 集成测试 / 无 key 时本地开发。
"""

from __future__ import annotations

import contextvars
import json
import uuid
from typing import Any, ClassVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import BaseModel

# Skill 通过 contextvar 把要查找的 fixture key 注入；避免从嵌套类型（list[TodoItem]）
# 反推 key 失败。
_current_mock_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_current_mock_key", default=None
)


def set_current_mock_key(key: str) -> contextvars.Token:
    return _current_mock_key.set(key)


def reset_current_mock_key(token: contextvars.Token) -> None:
    _current_mock_key.reset(token)


class MockLLM(BaseChatModel):
    """可注入预置响应的 Mock ChatModel。

    用法：
        mock = MockLLM()
        mock.set_response("summary", {"summary": "..."})
        mock.set_response("todo_extract", [...])
        ...
    或者调用 register_default_responses() 安装所有 skill 的默认 fixture。
    """

    # langchain 要求
    model_name: ClassVar[str] = "mock-llm"

    _responses: dict[str, Any]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._responses = {}
        self._bound_tools: list = []
        self._tool_call_count: int = 0
        register_default_responses(self)

    # ---- 注册预置响应 ----

    def set_response(self, key: str, value: Any) -> None:
        self._responses[key] = value

    def has_response(self, key: str) -> bool:
        return key in self._responses

    # ---- BaseChatModel 接口 ----

    @property
    def _llm_type(self) -> str:
        return "mock"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        # 如果有绑定的 tools（ReAct agent 路径）
        # 第一次返回 tool_call（让 agent 执行 tool）
        # 第二次返回 stop 信号（让 agent 结束并汇总）
        if self._bound_tools:
            self._tool_call_count += 1
            if self._tool_call_count >= 2:
                # 返回 stop（无 tool_call，agent 会结束）
                msg = AIMessage(content="（mock 终止）")
                return ChatResult(generations=[ChatGeneration(message=msg)])

            from langchain_core.messages import ToolCall

            tool = self._bound_tools[0]
            tool_name = getattr(tool, "name", str(tool))
            mock_args = getattr(tool, "mock_args", {}) or {}
            call = ToolCall(name=tool_name, args=mock_args, id=f"mock_call_{uuid.uuid4().hex[:8]}")
            msg = AIMessage(content="(mock tool call)", tool_calls=[call])
            return ChatResult(generations=[ChatGeneration(message=msg)])

        schema = _extract_schema(kwargs)
        key = _guess_key(messages, schema)
        content = self._responses.get(key)
        if content is None:
            raise RuntimeError(
                f"MockLLM: no preset response for key={key!r}. "
                "Call set_response() or register_default_responses()."
            )
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        msg = AIMessage(content=content)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop, **kwargs)

    def with_structured_output(  # type: ignore[override]
        self,
        schema: type[BaseModel] | dict,
        **kwargs: Any,
    ) -> MockStructuredLLM:
        return MockStructuredLLM(self, schema)

    def bind_tools(  # type: ignore[override]
        self,
        tools: list,
        **kwargs: Any,
    ) -> MockLLM:
        """绑定工具列表。返回新的 MockLLM 实例（保留 self 状态），用于 ReAct agent。"""
        new = MockLLM.__new__(MockLLM)
        BaseChatModel.__init__(new)
        new._responses = dict(self._responses)
        new._bound_tools = list(tools or [])
        new._tool_call_count = 0
        return new


class MockBoundLLM:
    """MockLLM.bind_tools() 返回的 wrapper。"""

    def __init__(self, parent: MockLLM, tools: list) -> None:
        self._parent = parent
        self._tools = tools or []

    async def ainvoke(
        self,
        input,
        **kwargs: Any,
    ):
        from langchain_core.messages import AIMessage, ToolCall

        if not self._tools:
            return AIMessage(content="(no tools available)")

        # 简化：直接调用第一个工具，参数 {}（mock）
        tool = self._tools[0]
        tool_name = getattr(tool, "name", str(tool))
        tool_args = getattr(tool, "mock_args", {}) or {}
        call = ToolCall(
            name=tool_name,
            args=tool_args,
            id=f"call_{uuid.uuid4().hex[:8]}",
        )
        return AIMessage(
            content="",
            tool_calls=[call],
        )

    def invoke(self, input, **kwargs: Any):
        import asyncio

        return asyncio.run(self.ainvoke(input, **kwargs))


class MockStructuredLLM:
    """MockLLM.with_structured_output() 返回的 wrapper，直接按 schema 构造。"""

    def __init__(self, parent: MockLLM, schema: type[BaseModel] | dict) -> None:
        self._parent = parent
        self._schema = schema

    async def ainvoke(self, input: Any, **kwargs: Any) -> BaseModel | dict:
        schema = self._schema
        key = _current_mock_key.get() or _guess_key_from_schema(schema)
        data = self._parent._responses.get(key)
        if data is None:
            raise RuntimeError(f"MockStructuredLLM: no preset response for {key!r}")
        if isinstance(schema, type) and issubclass(schema, BaseModel):
            return schema.model_validate(data)
        # list[X] / 其他
        if isinstance(data, list):
            item_type = _extract_list_item_type(schema)
            if item_type is not None and issubclass(item_type, BaseModel):
                return [item_type.model_validate(x) for x in data]
        return data

    def invoke(self, input: Any, **kwargs: Any) -> BaseModel | dict:
        # 同步入口（直接走 ainvoke 的结果，等价）
        import asyncio

        return asyncio.run(self.ainvoke(input, **kwargs))


# ---------- 默认响应 fixture ----------

_DEFAULT_RESPONSES: dict[str, Any] = {
    "summary": {
        "summary": "客户吴女士反馈了对产品的三个改进建议（暗黑模式、Excel 导出、离线缓存）。",
        "key_points": [
            "希望增加暗黑模式，缓解长时间使用眼睛疲劳",
            "数据导出格式需要增加 Excel 选项（目前只有 CSV）",
            "移动端需要增加离线缓存功能",
        ],
    },
    "todo_extract": [
        {
            "content": "在产品中添加暗黑模式",
            "due_date": None,
            "priority": "medium",
        },
        {
            "content": "为数据导出增加 Excel 格式支持",
            "due_date": None,
            "priority": "medium",
        },
        {
            "content": "为移动端增加离线缓存",
            "due_date": None,
            "priority": "low",
        },
    ],
    "entity_extract": {
        "entities": [
            {"name": "吴女士", "type": "person"},
            {"name": "Epsilon 公司", "type": "org"},
            {"name": "Excel", "type": "product"},
            {"name": "CSV", "type": "product"},
        ],
        "relations": [
            {
                "subject": "吴女士",
                "predicate": "works_at",
                "object": "Epsilon 公司",
                "confidence": 0.95,
            },
        ],
    },
    "classify": {"category_name": "常规", "confidence": 0.82},
    "tag_recommend": {
        "existing_label_matches": [
            {"name": "work", "confidence": 0.85},
        ],
        "recommended_new_labels": [
            {"name": "客户反馈", "type": "topic", "reason": "用户主动反馈产品建议"},
        ],
    },
    "spam": {
        "spam_score": 0.05,
        "is_spam": False,
        "reasons": ["发件人为真实业务往来域名", "正文含具体业务诉求"],
    },
    "draft": {
        "draft_text": "感谢您的反馈，我们已记录暗黑模式、Excel 导出与离线缓存三条建议。\n\n感谢您对我们的支持！",
        "key_points": ["感谢反馈", "记录三条建议"],
        "confidence": 0.88,
    },
    "draft_en": {
        "draft_text": "Thanks for your feedback. We have noted the three suggestions: dark mode, Excel export, and offline cache.\n\nWe appreciate your support!",
        "key_points": ["Thanks for feedback", "Noted three suggestions"],
        "confidence": 0.88,
    },
    "routingdecision": {
        "agents": ["email"],
        "reasoning": "(mock default routing: route to email agent)",
    },
}


def register_default_responses(mock: MockLLM) -> None:
    for k, v in _DEFAULT_RESPONSES.items():
        mock.set_response(k, v)


def install_mock_mode() -> MockLLM:
    """返回默认安装好所有 fixture 的 MockLLM。"""
    return MockLLM()


# ---------- 内部工具 ----------


def _extract_schema(kwargs: dict[str, Any]) -> type[BaseModel] | None:
    # langchain 0.3 with_structured_output 通过 kwargs 传 schema
    return kwargs.get("schema")


def _guess_key(messages: list[BaseMessage], schema: type[BaseModel] | None) -> str:
    """根据 schema 类型猜 key（基础 fallback）。"""
    if schema is None:
        return "summary"
    return _strip_schema_suffix(getattr(schema, "__name__", str(schema)))


def _guess_key_from_schema(schema: type[BaseModel] | dict) -> str:
    if isinstance(schema, type):
        return _strip_schema_suffix(schema.__name__)
    return "summary"


def _strip_schema_suffix(name: str) -> str:
    n = name.lower()
    for suffix in ("output", "schema", "result"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
            break
    return n


def _extract_list_item_type(schema: Any) -> type[BaseModel] | None:
    """从 list[X] / List[X] 中提取 X（要求 X 是 BaseModel 子类）。"""
    import typing

    origin = typing.get_origin(schema)
    if origin in (list, list):  # Python 3.9+ 用 list，3.7-3.8 用 typing.List
        args = typing.get_args(schema)
        if args and isinstance(args[0], type) and issubclass(args[0], BaseModel):
            return args[0]
    return None
