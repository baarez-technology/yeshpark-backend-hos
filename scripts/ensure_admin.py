"""
Idempotently ensure the default admin user exists with a known password.

Runs against whatever DATABASE_URL is configured (SQLite locally, Postgres in
production). Creates admin@glimmora.com if missing, or resets its password and
re-activates it if it already exists. Safe to run repeatedly.

Usage (on the production server, from the backend root with its venv active):

    python -m scripts.ensure_admin

Override the defaults via env vars if desired:

    ADMIN_EMAIL=admin@glimmora.com ADMIN_PASSWORD='choose-a-strong-one' \
        python -m scripts.ensure_admin
"""
import asyncio
import os

from sqlmodel import select

from app.db.session import async_session_maker
from app.models.user import User
from app.core.security import get_password_hash

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@glimmora.com").lower().strip()
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
ADMIN_NAME = os.getenv("ADMIN_NAME", "System Admin")


async def ensure_admin() -> None:
    async with async_session_maker() as session:
        result = await session.exec(select(User).where(User.email == ADMIN_EMAIL))
        admin = result.first()

        if admin:
            admin.hashed_password = get_password_hash(ADMIN_PASSWORD)
            admin.is_active = True
            admin.is_superuser = True
            admin.role = "admin"
            admin.must_reset_password = False
            admin.first_login = False
            await session.commit()
            print(f"✓ Reset existing admin: {ADMIN_EMAIL}")
        else:
            admin = User(
                email=ADMIN_EMAIL,
                full_name=ADMIN_NAME,
                hashed_password=get_password_hash(ADMIN_PASSWORD),
                is_active=True,
                is_superuser=True,
                role="admin",
            )
            session.add(admin)
            await session.commit()
            print(f"✓ Created admin: {ADMIN_EMAIL}")

        print(f"  Email:    {ADMIN_EMAIL}")
        print(f"  Password: {ADMIN_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(ensure_admin())
