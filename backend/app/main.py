"""FastAPI 应用入口。

v2-M5：可选托管前端构建产物（`frontend/dist`）。
检测目录存在 → mount `/static` + SPA fallback；
不存在 → 仅 API 服务（开发模式：前端走 Vite dev server 5173）。
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.tracing import configure_langsmith
from app.db.session import dispose_engine, get_engine

_settings = get_settings()
_logger = get_logger("deepmail.main")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    configure_langsmith()
    _logger.info("DeepMail_starting", version=__version__, env=_settings.app_env)
    get_engine()

    # v2-P1: L3 每日自动聚类（纯余弦，零 LLM 成本；可配置关闭）
    _cluster_task: asyncio.Task | None = None
    if _settings.cluster_auto_enabled:
        from app.db.session import get_sessionmaker
        from app.memory.cluster_scheduler import daily_cluster_loop

        _cluster_task = asyncio.create_task(
            daily_cluster_loop(
                get_sessionmaker(),
                _settings.cluster_auto_interval_hours,
            )
        )

    try:
        yield
    finally:
        if _cluster_task is not None:
            _cluster_task.cancel()
            try:
                await _cluster_task
            except asyncio.CancelledError:
                pass
        await dispose_engine()
        _logger.info("DeepMail_shutdown")


app = FastAPI(
    title="DeepMail API",
    version=__version__,
    description="AI Agent 邮箱助手",
    lifespan=lifespan,
)
app.include_router(api_router)


# ---------- 前端静态托管（v2-M5）----------

# frontend/dist 在仓库根目录下；用相对路径解析
_FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    _static_dir = _FRONTEND_DIST / "assets"
    _index_html = _FRONTEND_DIST / "index.html"

    # /assets/* 静态资源
    if _static_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_static_dir), name="frontend-assets")

    @app.get("/", include_in_schema=False)
    async def _root_index() -> FileResponse:
        return FileResponse(_index_html)

    # SPA fallback：所有非 /api、非 /assets、非 /docs、非 /openapi.json 的 GET → index.html
    @app.get("/{path:path}", include_in_schema=False)
    async def _spa_fallback(path: str, _request: Request) -> FileResponse:
        # API 路由由 include_router 优先匹配；这里兜底
        # 已存在的文件（favicon.ico 等）不存在时返回 index.html
        return FileResponse(_index_html)

    _logger.info("frontend_static_mounted", dist=str(_FRONTEND_DIST))
else:
    @app.get("/")
    async def root() -> dict[str, str]:
        return {"name": "DeepMail", "version": __version__, "docs": "/docs"}
