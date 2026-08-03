import asyncio
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.db.session import engine
from app.models.operations import HousekeepingTask

async def reassign():
    async with AsyncSession(engine) as session:
        # Get tasks 51-55 (rooms 204, 301, 302, 303, 304)
        task_ids = [51, 52, 53, 54, 55]

        for task_id in task_ids:
            task = await session.get(HousekeepingTask, task_id)
            if task:
                old_staff = task.assigned_to
                task.assigned_to = 24  # Maria Garcia's ID
                session.add(task)
                print(f'Task {task_id}: Reassigned from staff ID {old_staff} to 24 (Maria Garcia)')
            else:
                print(f'Task {task_id}: Not found')

        await session.commit()
        print('\nAll tasks reassigned successfully!')

asyncio.run(reassign())
