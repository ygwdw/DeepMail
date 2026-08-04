"""5 个 ReAct sub-agent。

每个 sub-agent 拥有自己的工具集合，由 langgraph prebuilt `create_react_agent` 创建。
Supervisor 决定调用哪些 sub-agent，可并行。
"""

from __future__ import annotations

from typing import Any

from langgraph.prebuilt import create_react_agent

from app.agents.tools.draft_tools import draft_reply
from app.agents.tools.email_tools import (
    classify_email,
    get_email,
    list_emails,
    summarize_email,
)
from app.agents.tools.rag_tools import search_knowledge
from app.agents.tools.todo_tools import create_todo, list_todos
from app.core.logging import get_logger

_logger = get_logger(__name__)

# 系统提示模板
EMAIL_AGENT_PROMPT = """你是 DeepMail 的【邮件 agent】，负责处理所有邮件相关任务。

你的工具：
- list_emails(folder, limit): 列出邮件
- get_email(email_id): 获取单封详情
- summarize_email(email_id): 生成摘要
- classify_email(email_id): 跑分类

行动原则：
- 涉及多封邮件时，先 list_emails 拿到 id，再针对性处理
- 用户没指定 folder，默认 inbox
- 返回结果时给出 ID，方便后续 agent 引用
- 中文回复
"""

TODO_AGENT_PROMPT = """你是 DeepMail 的【待办 agent】。

你的工具：
- list_todos(status, limit): 列出待办
- create_todo(content, due_date, priority): 新建待办
- list_emails(folder, limit): 顺便查邮件（找需要新建 todo 的邮件）

行动原则：
- 创建待办时如未指定 due_date，设为 null
- 中文回复
"""

DRAFT_AGENT_PROMPT = """你是 DeepMail 的【草稿 agent】，负责起草邮件回复。

你的工具：
- draft_reply(email_id, instruction, tone): 基于联系人历史起草
- get_email(email_id): 查原邮件（如果不知道 email_id）

行动原则：
- 用户没指定 email_id，先 list_emails 让用户选
- 中文回复（除非用户用其他语言）
"""

RAG_AGENT_PROMPT = """你是 DeepMail 的【知识库 agent】。

你的工具：
- search_knowledge(query, partition, top_k): 混合检索

行动原则：
- 用户没指定 partition，先全库搜；结果有歧义再分分区
- 列出命中时给 score + preview + 来源（partition/source）
- 中文回复
"""

TIDY_AGENT_PROMPT = """你是 DeepMail 的【整理 agent】，负责批量处理邮件（分类/打标/移垃圾箱）。

你的工具：
- list_emails(folder, limit): 列出邮件
- classify_email(email_id): 跑分类
- search_emails 不存在 —— 用 list_emails 过滤

行动原则：
- 批量操作前先 list 确认范围
- 中文回复，列出每个动作的影响
"""


def _build_react_agent(
    name: str,
    model: Any,
    tools: list,
    system_prompt: str,
):
    """包装 create_react_agent，统一命名。"""
    agent = create_react_agent(
        model=model,
        tools=tools,
        prompt=system_prompt,
        name=name,
    )
    return agent


def make_sub_agents(model: Any) -> dict[str, Any]:
    """构造 5 个 sub-agent。model 应从外部传入（按用户 LLM 配置）。"""
    return {
        "email": _build_react_agent(
            "email_agent",
            model,
            [list_emails, get_email, summarize_email, classify_email],
            EMAIL_AGENT_PROMPT,
        ),
        "todo": _build_react_agent(
            "todo_agent",
            model,
            [list_todos, create_todo, list_emails],
            TODO_AGENT_PROMPT,
        ),
        "draft": _build_react_agent(
            "draft_agent",
            model,
            [draft_reply, get_email, list_emails],
            DRAFT_AGENT_PROMPT,
        ),
        "rag": _build_react_agent(
            "rag_agent",
            model,
            [search_knowledge],
            RAG_AGENT_PROMPT,
        ),
        "tidy": _build_react_agent(
            "tidy_agent",
            model,
            [list_emails, classify_email, get_email],
            TIDY_AGENT_PROMPT,
        ),
    }
