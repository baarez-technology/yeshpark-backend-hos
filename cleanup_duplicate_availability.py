"""
Script to clean up duplicate DailyAvailability records
Run this to fix any existing duplicates in the database
"""
import asyncio
from sqlmodel import select, func
from app.db.session import get_session
from app.models.inventory import DailyAvailability

async def cleanup_duplicates():
    """Find and remove duplicate DailyAvailability records"""
    async for session in get_session():
        print("="*80)
        print("CLEANING UP DUPLICATE DailyAvailability RECORDS")
        print("="*80)
        
        # Find duplicates
        stmt = select(
            DailyAvailability.room_type_id,
            DailyAvailability.date,
            func.count(DailyAvailability.id).label('count')
        ).group_by(
            DailyAvailability.room_type_id,
            DailyAvailability.date
        ).having(func.count(DailyAvailability.id) > 1)
        
        result = await session.execute(stmt)
        duplicates = result.all()
        
        if not duplicates:
            print("No duplicate records found. Database is clean!")
            return
        
        print(f"Found {len(duplicates)} room_type_id/date combinations with duplicates")
        
        total_deleted = 0
        for dup in duplicates:
            room_type_id = dup.room_type_id
            date_val = dup.date
            count = dup.count
            
            print(f"\nProcessing: room_type_id={room_type_id}, date={date_val}, count={count}")
            
            # Get all records for this combination
            stmt = select(DailyAvailability).where(
                DailyAvailability.room_type_id == room_type_id,
                DailyAvailability.date == date_val
            ).order_by(DailyAvailability.id.desc())
            
            result = await session.execute(stmt)
            records = result.scalars().all()
            
            # Keep the most recent (first after ordering by id desc), delete others
            keep_id = records[0].id
            print(f"  Keeping record ID: {keep_id} (most recent)")
            
            for record in records[1:]:
                print(f"  Deleting duplicate record ID: {record.id}")
                await session.delete(record)
                total_deleted += 1
        
        await session.commit()
        
        print("\n" + "="*80)
        print(f"CLEANUP COMPLETE: Deleted {total_deleted} duplicate records")
        print("="*80)

if __name__ == "__main__":
    asyncio.run(cleanup_duplicates())
