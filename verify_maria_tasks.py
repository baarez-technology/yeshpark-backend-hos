import asyncio
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.db.session import engine
from app.models.staff import Staff
from app.models.user import User
from app.models.operations import HousekeepingTask

async def verify():
    async with AsyncSession(engine) as session:
        # Get Maria Garcia's user account
        user_result = await session.exec(select(User).where(User.email == 'housekeeping@glimmora.com'))
        user = user_result.first()

        if user:
            print(f'User Account:')
            print(f'  User ID: {user.id}')
            print(f'  Email: {user.email}')
            print(f'  Role: {user.role}')

            # Get linked staff record
            staff_result = await session.exec(select(Staff).where(Staff.user_id == user.id))
            staff = staff_result.first()

            if staff:
                print(f'\nLinked Staff Record:')
                print(f'  Staff ID: {staff.id}')
                print(f'  Name: {staff.name}')
                print(f'  Email: {staff.email}')

                # Get tasks assigned to this staff
                tasks_result = await session.exec(
                    select(HousekeepingTask)
                    .where(HousekeepingTask.assigned_to == staff.id)
                    .where(HousekeepingTask.status.in_(['pending', 'in_progress', 'assigned']))
                )
                tasks = tasks_result.all()

                print(f'\nActive Tasks Assigned to Staff ID {staff.id}:')
                print(f'  Total: {len(tasks)}')
                for task in tasks:
                    print(f'    Task {task.id}: Room {task.room_id}, Status: {task.status}, Type: {task.task_type}')
            else:
                print(f'\nNo staff record linked to user {user.id}')
        else:
            print('User not found')

asyncio.run(verify())
