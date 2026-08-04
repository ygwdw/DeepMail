"""时间上下文：把当前时间注入到 LLM prompt。

格式约定：
  - 自然语言："2026-08-04 10:30 星期二"
  - ISO 格式："2026-08-04T10:30:00+08:00"（用于 GraphState.current_time / 持久化）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


# 默认时区（阶段 4 写死上海；后期可放 settings）
DEFAULT_TZ = timezone(timedelta(hours=8))


def _now(tz: timezone = DEFAULT_TZ) -> datetime:
    return datetime.now(tz)


def format_natural(dt: datetime | None = None) -> str:
    """自然语言时间，例如 "2026-08-04 10:30 星期二" """
    if dt is None:
        dt = _now()
    weekday = WEEKDAY_CN[dt.weekday()]
    return f"{dt.strftime('%Y-%m-%d %H:%M')} {weekday}"


def format_iso(dt: datetime | None = None) -> str:
    """ISO 格式，例如 "2026-08-04T10:30:00+08:00" """
    if dt is None:
        dt = _now()
    return dt.isoformat()


def now_natural() -> str:
    """快捷：当前自然语言时间"""
    return format_natural()


# 系统 prompt 注入用的辅助
TIME_PREFIX = "当前时间"


def inject_time_to_prompt(prompt: str) -> str:
    """把当前时间追加到 system prompt 末尾（如果还没有的话）。

    使用方式：所有 skill 系统 prompt 在调用 LLM 前过一下本函数。
    """
    now_str = format_natural()
    if TIME_PREFIX in prompt:
        return prompt
    return f"{prompt}\n\n[{TIME_PREFIX}：{now_str}（Asia/Shanghai）]"
