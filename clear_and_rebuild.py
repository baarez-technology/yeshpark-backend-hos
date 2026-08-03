"""
Simple script to clear and rebuild database
Make sure to stop the FastAPI server first!
"""
import asyncio
import os
import sys
from pathlib import Path
from sqlalchemy import text
from app.db.session import engine, init_db

# Import all models
from app.models import user, reservations, inventory, operations, precheckin, payment_method, dashboards, help


async def rebuild():
    print("=" * 60)
    print("CLEARING AND REBUILDING DATABASE")
    print("=" * 60)
    print()
    
    # Step 1: Try to drop all tables
    print("Step 1: Dropping all tables...")
    try:
        async with engine.begin() as conn:
            # Disable foreign keys
            await conn.execute(text("PRAGMA foreign_keys=OFF"))
            
            # Get all tables
            result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"))
            tables = [row[0] for row in result.fetchall()]
            
            if tables:
                for table in tables:
                    print(f"  Dropping: {table}")
                    await conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
                print(f"  ✓ Dropped {len(tables)} tables")
            else:
                print("  ✓ No tables to drop")
            
            await conn.execute(text("PRAGMA foreign_keys=ON"))
    except Exception as e:
        print(f"  ✗ Error: {e}")
        print("\n⚠ Make sure the FastAPI server is stopped!")
        return False
    
    # Step 2: Create all tables
    print("\nStep 2: Creating all tables...")
    try:
        await init_db()
        print("  ✓ All tables created")
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False
    
    # Step 3: Verify payment_method table
    print("\nStep 3: Verifying PaymentMethod table...")
    try:
        from app.models.payment_method import PaymentMethod
        async with engine.begin() as conn:
            await conn.run_sync(PaymentMethod.metadata.create_all)
        print("  ✓ PaymentMethod table verified")
    except Exception as e:
        print(f"  ⚠ Warning: {e}")
    
    print("\n" + "=" * 60)
    print("✓ DATABASE REBUILT SUCCESSFULLY!")
    print("=" * 60)
    print("\nNext: Run seed.py or seed_comprehensive.py to add data")
    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(rebuild())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nCancelled")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

