"""
Migration script to add new columns to User table:
- address
- city
- zip_code
- country
- preferences
"""
import sqlite3
from pathlib import Path
import os

def migrate_user_table():
    """Add new columns to User table if they don't exist"""
    
    # Try to get database path from environment or default
    db_path = os.getenv("DATABASE_URL", "glimmora.db")
    
    # Remove sqlite:/// prefix if present
    if db_path.startswith("sqlite:///"):
        db_path = db_path.replace("sqlite:///", "")
    elif db_path.startswith("sqlite+aiosqlite:///"):
        db_path = db_path.replace("sqlite+aiosqlite:///", "")
    
    # Check if database file exists
    if not Path(db_path).exists():
        print(f"Database file not found: {db_path}")
        print("Database will be created with new schema on next server start.")
        return
    
    print(f"Migrating database: {db_path}")
    
    # Connect to SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        # Get existing columns
        cursor.execute("PRAGMA table_info(user)")
        existing_columns = [row[1] for row in cursor.fetchall()]
        
        print(f"Existing columns: {existing_columns}")
        
        # Columns to add
        new_columns = [
            ("address", "TEXT"),
            ("city", "TEXT"),
            ("zip_code", "TEXT"),
            ("country", "TEXT"),
            ("preferences", "TEXT"),
        ]
        
        # Add missing columns
        added_count = 0
        for column_name, column_type in new_columns:
            if column_name not in existing_columns:
                try:
                    alter_sql = f"ALTER TABLE user ADD COLUMN {column_name} {column_type}"
                    cursor.execute(alter_sql)
                    print(f"  ✓ Added column: {column_name}")
                    added_count += 1
                except sqlite3.OperationalError as e:
                    print(f"  ✗ Failed to add column {column_name}: {e}")
            else:
                print(f"  → Column already exists: {column_name}")
        
        conn.commit()
        
        if added_count > 0:
            print(f"\n✓ Migration completed successfully! Added {added_count} column(s).")
        else:
            print("\n✓ All columns already exist. No migration needed.")
        
    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
    finally:
        conn.close()


if __name__ == "__main__":
    migrate_user_table()

