"""
Quick script to create admin user
"""
import asyncio
from sqlmodel import select
from app.db.session import async_session_maker
from app.models.user import User
from app.core.security import get_password_hash


async def create_admin():
    async with async_session_maker() as session:
        # Ensure admin@glimmora.local
        result = await session.exec(select(User).where(User.email == "admin@glimmora.local"))
        admin_local = result.first()
        if admin_local:
            admin_local.hashed_password = get_password_hash("admin123")
            admin_local.is_superuser = True
            admin_local.is_active = True
            session.add(admin_local)
            print("[OK] Reset admin@glimmora.local password to admin123")
        else:
            admin_local = User(
                email="admin@glimmora.local",
                full_name="System Admin",
                hashed_password=get_password_hash("admin123"),
                is_superuser=True,
                is_active=True,
                role="admin",
                phone="+1 (555) 100-0001",
            )
            session.add(admin_local)
            print("[OK] Created admin@glimmora.local with password admin123")

        # Ensure admin@glimmora.com
        result_com = await session.exec(select(User).where(User.email == "admin@glimmora.com"))
        admin_com = result_com.first()
        if admin_com:
            admin_com.hashed_password = get_password_hash("admin123")
            admin_com.is_superuser = True
            admin_com.is_active = True
            session.add(admin_com)
            print("[OK] Reset admin@glimmora.com password to admin123")
        else:
            admin_com = User(
                email="admin@glimmora.com",
                full_name="System Admin",
                hashed_password=get_password_hash("admin123"),
                is_superuser=True,
                is_active=True,
                role="admin",
                phone="+1 (555) 100-0002",
            )
            session.add(admin_com)
            print("[OK] Created admin@glimmora.com with password admin123")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(create_admin())

