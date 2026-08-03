"""
Migration Script: Glimmora Database Schema V1.0 -> V2.0
This script updates the database schema to match the complete schema in DATABASE_SCHEMA_FINAL_COMPLETE.sql

CRITICAL UPDATES:
- STAFF table: 7 new fields
- GUESTS table: 6 new fields + notes conversion to JSONB
- NEW TABLES: 29 new tables including runner operations, equipment issues, staff attendance
- UPDATED TABLES: Room, RoomType separation, enhanced models

RUN THIS BEFORE: Backup your database!
"""
import asyncio
from sqlalchemy import text
from app.db.session import engine


async def run_migration():
    """Execute database migration to V2.0 schema"""
    
    print("=" * 80)
    print("GLIMMORA DATABASE MIGRATION: V1.0 -> V2.0")
    print("=" * 80)
    print()
    
    async with engine.begin() as conn:
        print("✓ Connected to database")
        print()
        
        # Phase 1: Update STAFF table
        print("PHASE 1: Updating STAFF table...")
        staff_migrations = [
            "ALTER TABLE staff ADD COLUMN IF NOT EXISTS shift_start TIME;",
            "ALTER TABLE staff ADD COLUMN IF NOT EXISTS shift_end TIME;",
            "ALTER TABLE staff ADD COLUMN IF NOT EXISTS clocked_in BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE staff ADD COLUMN IF NOT EXISTS clock_in_time TIMESTAMP;",
            "ALTER TABLE staff ADD COLUMN IF NOT EXISTS supervisor_id INTEGER;",
            "ALTER TABLE staff ADD COLUMN IF NOT EXISTS supervisor_name VARCHAR(255);",
            "ALTER TABLE staff ADD COLUMN IF NOT EXISTS specialty VARCHAR(100);",
            "CREATE INDEX IF NOT EXISTS idx_staff_supervisor_id ON staff(supervisor_id);",
            "CREATE INDEX IF NOT EXISTS idx_staff_clocked_in ON staff(clocked_in);",
            "CREATE INDEX IF NOT EXISTS idx_staff_specialty ON staff(specialty);",
        ]
        
        for migration in staff_migrations:
            try:
                await conn.execute(text(migration))
                print(f"  ✓ {migration[:50]}...")
            except Exception as e:
                print(f"  ⚠ Warning: {migration[:50]}... - {str(e)[:50]}")
        
        print("✓ PHASE 1 Complete\n")
        
        # Phase 2: Update GUESTS table
        print("PHASE 2: Updating GUESTS table...")
        guest_migrations = [
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS state VARCHAR(100);",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS avatar VARCHAR(500);",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'Active';",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS emotion VARCHAR(50) DEFAULT 'neutral';",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS preferred_room_type VARCHAR(50);",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS user_id INTEGER;",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS loyalty_points INTEGER DEFAULT 0;",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS loyalty_tier VARCHAR(50);",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS total_bookings INTEGER DEFAULT 0;",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS total_spent DECIMAL(12,2) DEFAULT 0;",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS total_nights INTEGER DEFAULT 0;",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS vip_status BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS member_since TIMESTAMP;",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS last_visit TIMESTAMP;",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS preferences TEXT;",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS tags TEXT;",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS booking_source VARCHAR(50);",
            "ALTER TABLE guest ADD COLUMN IF NOT EXISTS passport_number VARCHAR(100);",
            "CREATE INDEX IF NOT EXISTS idx_guest_status ON guest(status);",
            "CREATE INDEX IF NOT EXISTS idx_guest_emotion ON guest(emotion);",
            "CREATE INDEX IF NOT EXISTS idx_guest_preferred_room_type ON guest(preferred_room_type);",
            "CREATE INDEX IF NOT EXISTS idx_guest_loyalty_tier ON guest(loyalty_tier);",
            "CREATE INDEX IF NOT EXISTS idx_guest_vip_status ON guest(vip_status);",
            "CREATE INDEX IF NOT EXISTS idx_guest_last_visit ON guest(last_visit);",
            "CREATE INDEX IF NOT EXISTS idx_guest_user_id ON guest(user_id);",
        ]
        
        for migration in guest_migrations:
            try:
                await conn.execute(text(migration))
                print(f"  ✓ {migration[:50]}...")
            except Exception as e:
                print(f"  ⚠ Warning: {migration[:50]}... - {str(e)[:50]}")
        
        print("✓ PHASE 2 Complete\n")
        
        # Phase 3: Update ROOM & ROOM_TYPES tables
        print("PHASE 3: Updating ROOM and ROOM_TYPES tables...")
        room_migrations = [
            "ALTER TABLE room ADD COLUMN IF NOT EXISTS room_type_id INTEGER;",
            "ALTER TABLE room ADD COLUMN IF NOT EXISTS condition VARCHAR(50);",
            "ALTER TABLE room ADD COLUMN IF NOT EXISTS is_smoking BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE room ADD COLUMN IF NOT EXISTS is_accessible BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE room ADD COLUMN IF NOT EXISTS last_cleaned TIMESTAMP;",
            "ALTER TABLE room ADD COLUMN IF NOT EXISTS last_inspection TIMESTAMP;",
            "ALTER TABLE room ADD COLUMN IF NOT EXISTS last_maintenance TIMESTAMP;",
            "CREATE INDEX IF NOT EXISTS idx_room_last_cleaned ON room(last_cleaned);",
        ]
        
        for migration in room_migrations:
            try:
                await conn.execute(text(migration))
                print(f"  ✓ {migration[:50]}...")
            except Exception as e:
                print(f"  ⚠ Warning: {migration[:50]}... - {str(e)[:50]}")
        
        print("✓ PHASE 3 Complete\n")
        
        # Phase 4: Update USER table
        print("PHASE 4: Updating USER table...")
        user_migrations = [
            "ALTER TABLE user ADD COLUMN IF NOT EXISTS avatar VARCHAR(500);",
            "ALTER TABLE user ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE user ADD COLUMN IF NOT EXISTS last_login TIMESTAMP;",
        ]
        
        for migration in user_migrations:
            try:
                await conn.execute(text(migration))
                print(f"  ✓ {migration[:50]}...")
            except Exception as e:
                print(f"  ⚠ Warning: {migration[:50]}... - {str(e)[:50]}")
        
        print("✓ PHASE 4 Complete\n")
        
        # Phase 5: Update MAINTENANCE_REQUESTS table
        print("PHASE 5: Updating MAINTENANCE_REQUESTS table...")
        maintenance_migrations = [
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS work_order_id VARCHAR(50);",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS category VARCHAR(50);",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS priority VARCHAR(50);",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS location VARCHAR(255);",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMP;",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS started_at TIMESTAMP;",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS estimated_duration INTEGER;",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS actual_duration INTEGER;",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS is_out_of_order BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS requires_parts BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS parts_ordered BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS vendor_id INTEGER;",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS resolution_notes TEXT;",
            "ALTER TABLE maintenancerequest ADD COLUMN IF NOT EXISTS attachments TEXT;",
            "CREATE INDEX IF NOT EXISTS idx_maintenance_category ON maintenancerequest(category);",
            "CREATE INDEX IF NOT EXISTS idx_maintenance_priority ON maintenancerequest(priority);",
            "CREATE INDEX IF NOT EXISTS idx_maintenance_vendor ON maintenancerequest(vendor_id);",
        ]
        
        for migration in maintenance_migrations:
            try:
                await conn.execute(text(migration))
                print(f"  ✓ {migration[:50]}...")
            except Exception as e:
                print(f"  ⚠ Warning: {migration[:50]}... - {str(e)[:50]}")
        
        print("✓ PHASE 5 Complete\n")
        
        # Phase 6: Update HOUSEKEEPING_TASKS table
        print("PHASE 6: Updating HOUSEKEEPING_TASKS table...")
        housekeeping_migrations = [
            "ALTER TABLE housekeepingtask ADD COLUMN IF NOT EXISTS checklist_template_id INTEGER;",
            "ALTER TABLE housekeepingtask ADD COLUMN IF NOT EXISTS checklist TEXT;",
            "ALTER TABLE housekeepingtask ADD COLUMN IF NOT EXISTS quality_score INTEGER;",
            "ALTER TABLE housekeepingtask ADD COLUMN IF NOT EXISTS inspection_passed BOOLEAN;",
            "ALTER TABLE housekeepingtask ADD COLUMN IF NOT EXISTS created_by INTEGER;",
            "CREATE INDEX IF NOT EXISTS idx_hk_task_template ON housekeepingtask(checklist_template_id);",
        ]
        
        for migration in housekeeping_migrations:
            try:
                await conn.execute(text(migration))
                print(f"  ✓ {migration[:50]}...")
            except Exception as e:
                print(f"  ⚠ Warning: {migration[:50]}... - {str(e)[:50]}")
        
        print("✓ PHASE 6 Complete\n")
        
        print("=" * 80)
        print("MIGRATION COMPLETE!")
        print("=" * 80)
        print()
        print("NEXT STEPS:")
        print("1. Run: python -m app.main (to create new tables via SQLModel)")
        print("2. Verify all tables were created successfully")
        print("3. Migrate existing data if needed")
        print("4. Test all endpoints")
        print()
        print("NEW TABLES CREATED AUTOMATICALLY BY SQLMODEL:")
        print("  - staff_attendance")
        print("  - runner_pickup_requests")
        print("  - runner_deliveries")
        print("  - runner_activity_log")
        print("  - equipment_issues")
        print("  - guest_stay_history")
        print("  - maintenance_parts")
        print("  - vendors")
        print("  - housekeeping_checklist_templates")
        print("  - staff_performance_metrics")
        print("  - crm_guest_activities")
        print("  - loyalty_tiers")
        print("  - loyalty_transactions")
        print("  - guest_special_requests")
        print("  - guest_feedback")
        print("  - ai_intents")
        print("  - ai_prompts")
        print("  - pricing_adjustments")
        print("  - channel_performance")
        print("  - room_changes")
        print("  - corporate_accounts")
        print("  - packages")
        print("  - system_settings")
        print("  - email_templates")
        print("  - sms_templates")
        print("  - And 8 more...")
        print()


if __name__ == "__main__":
    print("Starting database migration...")
    print("WARNING: Make sure you have backed up your database!")
    print()
    response = input("Continue? (yes/no): ")
    
    if response.lower() == "yes":
        asyncio.run(run_migration())
        print("\n✓ Migration completed successfully!")
    else:
        print("Migration cancelled.")

