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
        # Check if admin exists
        result = await session.exec(select(User).where(User.email == "admin@glimmora.local"))
        admin = result.first()
        
        if admin:
            print(f"Admin user already exists: {admin.email}")
            print(f"  Role: {admin.role}")
            print(f"  Superuser: {admin.is_superuser}")
        else:
            admin = User(
                email="admin@glimmora.local",
                full_name="System Admin",
                hashed_password=get_password_hash("admin123"),
                is_superuser=True,
                role="admin",
                phone="+1 (555) 100-0001",
                address="123 Hotel Street",
                city="Santa Monica",
                zip_code="90401",
                country="United States",
            )
            session.add(admin)
            await session.commit()
            print("✓ Admin user created successfully!")
            print(f"  Email: admin@glimmora.local")
            print(f"  Password: admin123")
        
        # List all users
        result = await session.exec(select(User))
        users = result.all()
        print(f"\nTotal users in database: {len(users)}")
        for u in users:
            print(f"  - {u.email} (role: {u.role}, superuser: {u.is_superuser})")


if __name__ == "__main__":
    asyncio.run(create_admin())

