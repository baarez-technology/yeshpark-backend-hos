"""
Migration script to add new fields to MaintenanceRequest table
Run this script to add: title, issue_type, room_number columns
"""
import asyncio
from sqlalchemy import text
from app.db.session import engine


async def column_exists(conn, table_name, column_name):
    """Check if a column exists in SQLite table"""
    result = await conn.execute(text(f"PRAGMA table_info({table_name})"))
    columns = result.fetchall()
    return any(col[1] == column_name for col in columns)


async def migrate():
    """Add new columns to maintenancerequest table"""
    print("=" * 60)
    print("Migration: Adding new fields to MaintenanceRequest table")
    print("=" * 60)

    async with engine.begin() as conn:
        # Check if columns exist and add them if not
        columns_to_add = [
            ("title", "VARCHAR(255)"),
            ("issue_type", "VARCHAR(100)"),
            ("room_number", "VARCHAR(20)"),
        ]

        for column_name, column_type in columns_to_add:
            try:
                if await column_exists(conn, "maintenancerequest", column_name):
                    print(f"  -> Column already exists: {column_name}")
                else:
                    await conn.execute(
                        text(f"ALTER TABLE maintenancerequest ADD COLUMN {column_name} {column_type}")
                    )
                    print(f"  + Added column: {column_name}")
            except Exception as e:
                print(f"  ! Error adding {column_name}: {e}")

        # Create indexes for new columns
        indexes = [
            ("idx_maintenancerequest_issue_type", "issue_type"),
            ("idx_maintenancerequest_room_number", "room_number"),
        ]

        for index_name, column_name in indexes:
            try:
                await conn.execute(
                    text(f"CREATE INDEX IF NOT EXISTS {index_name} ON maintenancerequest ({column_name})")
                )
                print(f"  + Created index: {index_name}")
            except Exception as e:
                if "already exists" in str(e).lower():
                    print(f"  -> Index already exists: {index_name}")
                else:
                    print(f"  ! Error creating index {index_name}: {e}")

        # Update existing records to populate issue_type from category
        try:
            result = await conn.execute(
                text("UPDATE maintenancerequest SET issue_type = category WHERE issue_type IS NULL")
            )
            print(f"  + Updated {result.rowcount} records: set issue_type = category")
        except Exception as e:
            print(f"  ! Error updating issue_type: {e}")

        # Update existing records to populate title from issue
        try:
            result = await conn.execute(
                text("UPDATE maintenancerequest SET title = issue WHERE title IS NULL")
            )
            print(f"  + Updated {result.rowcount} records: set title = issue")
        except Exception as e:
            print(f"  ! Error updating title: {e}")

    print("")
    print("=" * 60)
    print("Migration completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(migrate())
