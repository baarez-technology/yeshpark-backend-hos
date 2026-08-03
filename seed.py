import asyncio
from app.db.session import async_session_maker, init_db
from app.core.security import get_password_hash
from app.models.user import User
from app.models.inventory import Room, RatePlan
from app.models.help import HelpArticle
from sqlmodel import select


async def seed():
    await init_db()
    async with async_session_maker() as session:
        # Admin user
        admin = (await session.exec(select(User).where(User.email == "admin@glimmora.local"))).first()
        if not admin:
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
        # Rooms
        for i in range(101, 121):
            existing = (await session.exec(select(Room).where(Room.number == str(i)))).first()
            if not existing:
                session.add(Room(number=str(i), room_type="king" if i % 2 == 1 else "queen", floor=i // 100))
        # RatePlan
        rp = (await session.exec(select(RatePlan).where(RatePlan.code == "BAR"))).first()
        if not rp:
            session.add(RatePlan(code="BAR", name="Best Available Rate", base_price=12500.0, currency="INR"))
        # Help
        ha = (await session.exec(select(HelpArticle).where(HelpArticle.slug == "getting-started"))).first()
        if not ha:
            session.add(HelpArticle(slug="getting-started", title="Getting Started", content_md="# Welcome", language="en"))
        await session.commit()


if __name__ == "__main__":
    asyncio.run(seed())


