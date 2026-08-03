import asyncio
from sqlmodel import select
from app.db.session import async_session_maker, init_db
from app.models.user import User
from app.core.security import get_password_hash

async def add_user():
    await init_db()
    async with async_session_maker() as session:
        # Check if user exists
        result = await session.exec(select(User).where(User.email == "ishanagrawal1201@gmail.com"))
        existing = result.first()
        
        if existing:
            print(f"User {existing.email} already exists")
        else:
            new_user = User(
                email="ishanagrawal1201@gmail.com",
                full_name="Ishan Agrawal",
                hashed_password=get_password_hash("Ishan@1201"),
                is_active=True,
                is_superuser=False,
                role="staff",
                phone="+1 (555) 123-4567",
                address="1250 Ocean Boulevard",
                city="Santa Monica",
                zip_code="90401",
                country="United States",
                preferences='{"floor":"high","view":"ocean","bedType":"king","quietness":"quiet","temperature":72,"pillowType":["firm"],"minibar":["water","soft-drinks"],"dietary":["vegetarian"]}'
            )
            session.add(new_user)
            await session.commit()
            print(f"User created: {new_user.email}")
        
        # List all users
        result = await session.exec(select(User))
        users = result.all()
        print(f'\nTotal users: {len(users)}')
        for u in users:
            print(f'  - {u.email} (role: {u.role})')

if __name__ == "__main__":
    asyncio.run(add_user())

