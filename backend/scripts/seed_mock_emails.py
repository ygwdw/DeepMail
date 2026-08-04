"""种子数据：管理员账号 + 30 封 Mock 邮件。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.models.user import User, UserRole  # noqa: E402
from app.db.session import dispose_engine, get_sessionmaker  # noqa: E402
from app.services.email_provider.mock_provider import MockEmailProvider  # noqa: E402
from app.services.email_service import EmailService  # noqa: E402
from sqlalchemy import select  # noqa: E402

_settings = get_settings()


async def seed_admin(db_session) -> None:
    stmt = select(User).where(User.username == _settings.admin_username)
    existing = (await db_session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        print(f">>> admin '{_settings.admin_username}' already exists, skip")
        return

    user = User(
        username=_settings.admin_username,
        password_hash=hash_password(_settings.admin_password),
        role=UserRole.ADMIN,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    # 同时 seed 默认分类
    from app.services.category_seed import seed_default_categories

    n = await seed_default_categories(db_session, user.id)
    print(f">>> created admin '{_settings.admin_username}' with {n} default categories")


async def seed_emails(db_session, admin_id) -> int:
    provider = MockEmailProvider()
    svc = EmailService(db_session, provider)
    added = await svc.ensure_from_provider(admin_id)
    total = await svc.count_emails(admin_id)
    print(f">>> emails synced: added={added} total={total}")
    return added


async def main() -> None:
    sm = get_sessionmaker()
    async with sm() as db:
        await seed_admin(db)
        stmt = select(User).where(User.username == _settings.admin_username)
        admin = (await db.execute(stmt)).scalar_one()
        await seed_emails(db, admin.id)
    await dispose_engine()
    print(">>> seed complete")


if __name__ == "__main__":
    asyncio.run(main())
