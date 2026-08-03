import asyncio
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.db.session import engine
from app.models.user import User
from app.core.security import get_password_hash

async def reset_password():
    async with AsyncSession(engine) as session:
        # Find Maria Garcia's user account
        result = await session.exec(select(User).where(User.email == 'housekeeping@glimmora.com'))
        user = result.first()

        if user:
            print(f'Found user: {user.email} (ID: {user.id})')

            # Hash the password
            hashed_password = get_password_hash('123456')

            # Update the password
            user.hashed_password = hashed_password
            session.add(user)
            await session.commit()

            print(f'Password successfully reset to: 123456')
            print(f'User is_active: {user.is_active}')
            print(f'User role: {user.role}')
        else:
            print('User housekeeping@glimmora.com not found')

asyncio.run(reset_password())
