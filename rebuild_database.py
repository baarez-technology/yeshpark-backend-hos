"""
Script to clear and rebuild the entire database
"""
import asyncio
import os
from pathlib import Path
from sqlalchemy import text, inspect
from sqlmodel import SQLModel
from app.db.session import engine, init_db
from app.core.config import settings

# Import all models to ensure they're registered
from app.models.user import User
from app.models.reservations import Reservation, Guest, ReservationHistory, ReservationNote, Waitlist, GroupBooking
from app.models.inventory import Room
from app.models.operations import HousekeepingTask, MaintenanceRequest, LostFound, LinenInventory, Folio, FolioLineItem, Payment, KeyCard, GuestCommunication, NightAudit, ShiftHandover
from app.models.precheckin import PreCheckIn
from app.models.payment_method import PaymentMethod
from app.models.dashboards import DashboardWidget, DashboardLayout
from app.models.help import HelpArticle, HelpCategory


async def clear_and_rebuild_database():
    """Clear database and rebuild from scratch"""
    import sys
    def flush_print(*args, **kwargs):
        print(*args, **kwargs)
        sys.stdout.flush()
    
    flush_print("=" * 60)
    flush_print("DATABASE REBUILD SCRIPT")
    flush_print("=" * 60)
    
    # Step 1: Drop all existing tables
    flush_print("\n1. Dropping all existing tables...")
    try:
        async with engine.begin() as conn:
            # Get all table names
            inspector = inspect(engine.sync_engine)
            tables = inspector.get_table_names()
            
            if tables:
                # Drop all tables in reverse dependency order
                # Drop foreign key constraints first
                await conn.execute(text("PRAGMA foreign_keys=OFF"))
                
                for table_name in tables:
                    flush_print(f"   Dropping table: {table_name}")
                    await conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
                
                await conn.execute(text("PRAGMA foreign_keys=ON"))
                flush_print(f"   ✓ Dropped {len(tables)} tables")
            else:
                flush_print("   ✓ No existing tables found")
    except Exception as e:
        flush_print(f"   ⚠ Error dropping tables: {e}")
        # Try alternative: drop all using metadata
        try:
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.drop_all)
            flush_print("   ✓ Dropped tables using metadata")
        except Exception as e2:
            flush_print(f"   ✗ Failed to drop tables: {e2}")
            return
    
    # Step 2: Recreate all tables
    flush_print("\n2. Creating database schema...")
    try:
        await init_db()
        flush_print("   ✓ All tables created successfully")
    except Exception as e:
        flush_print(f"   ✗ Error creating tables: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # Step 3: Run migrations
    flush_print("\n3. Running migrations...")
    
    # Migration: Payment Methods table
    try:
        from app.models.payment_method import PaymentMethod
        async with engine.begin() as conn:
            await conn.run_sync(PaymentMethod.metadata.create_all)
        flush_print("   ✓ PaymentMethod table created")
    except Exception as e:
        flush_print(f"   ⚠ PaymentMethod migration: {e}")
    
    # Migration: User table (ensure all columns exist)
    try:
        from app.models.user import User
        async with engine.begin() as conn:
            # Check and add missing columns
            result = await conn.execute(text("PRAGMA table_info(user)"))
            existing_columns = [row[1] for row in result.fetchall()]
            
            columns_to_add = {
                "address": "TEXT",
                "city": "TEXT",
                "zip_code": "TEXT",
                "country": "TEXT",
                "preferences": "TEXT",
            }
            
            for col_name, col_type in columns_to_add.items():
                if col_name not in existing_columns:
                    await conn.execute(text(f"ALTER TABLE user ADD COLUMN {col_name} {col_type}"))
                    flush_print(f"   ✓ Added column: user.{col_name}")
        flush_print("   ✓ User table migration completed")
    except Exception as e:
        flush_print(f"   ⚠ User migration: {e}")
    
    flush_print("\n4. Database rebuild complete!")
    flush_print("=" * 60)
    flush_print("\nNext steps:")
    flush_print("  - Run seed.py to add initial admin user")
    flush_print("  - Run seed_comprehensive.py for full test data")
    flush_print("  - Or run add_user.py to add specific users")
    flush_print("=" * 60)


if __name__ == "__main__":
    import sys
    try:
        asyncio.run(clear_and_rebuild_database())
        sys.exit(0)
    except KeyboardInterrupt:
        print("\n\n⚠ Rebuild cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n✗ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

