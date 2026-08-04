"""初始化数据库：跑 alembic 迁移 + 自动 seed admin + 30 封 mock 邮件。

v2 改进（用户提）：
- 改前：用户需要分别跑 init_db.py + seed_mock_emails.py；
       只跑 init_db 没有 admin，无法登录
- 改后：init_db.py 一条命令搞定。
       重复跑幂等：seed_admin 检测存在就跳过；
       seed_emails 用 message_id dedup。

用法：
    cd backend && uv run python scripts/init_db.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# 让 alembic 能找到 app.*
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from alembic import command  # noqa: E402  -- sys.path 注入后才能 import
from alembic.config import Config  # noqa: E402

from scripts.seed_mock_emails import seed_admin, seed_emails  # noqa: E402


def _run_alembic_upgrade() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("prepend_sys_path", str(BACKEND_DIR))
    print(">>> alembic upgrade head")
    command.upgrade(cfg, "head")
    print(">>> alembic done")


async def _run_seed() -> None:
    """Seed admin（如不存在）+ 30 封 mock 邮件（如未索引）。幂等。"""
    from app.core.config import get_settings
    from app.db.models.user import User
    from app.db.session import dispose_engine, get_sessionmaker
    from sqlalchemy import select

    settings = get_settings()
    sm = get_sessionmaker()
    async with sm() as db:
        await seed_admin(db)
        # 重新读 admin（seed_admin 内部可能没刷新）
        admin = (
            await db.execute(
                select(User).where(User.username == settings.admin_username)
            )
        ).scalar_one()
        await seed_emails(db, admin.id)
    await dispose_engine()


def main() -> None:
    _run_alembic_upgrade()
    print(">>> seeding admin + 30 mock emails")
    asyncio.run(_run_seed())
    print(">>> seed complete")


if __name__ == "__main__":
    main()
