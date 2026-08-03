"""
Migration script to add room_type_id column to reservation table
Run with: python migrate_add_room_type_id.py
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "glimmora.db")

def migrate():
    """Add room_type_id column to reservation table if it doesn't exist"""
    print(f"Connecting to database: {DB_PATH}")

    if not os.path.exists(DB_PATH):
        print("Database file not found. Run the application first to create it.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check if column already exists
    cursor.execute("PRAGMA table_info(reservation)")
    columns = [row[1] for row in cursor.fetchall()]

    if 'room_type_id' in columns:
        print("Column room_type_id already exists in reservation table.")
    else:
        print("Adding room_type_id column to reservation table...")
        cursor.execute("""
            ALTER TABLE reservation
            ADD COLUMN room_type_id INTEGER REFERENCES room_types(id)
        """)
        print("Column added successfully!")

    # Create index if not exists
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS ix_reservation_room_type_id ON reservation(room_type_id)")
        print("Index created successfully!")
    except sqlite3.OperationalError as e:
        print(f"Index already exists or error: {e}")

    conn.commit()
    conn.close()
    print("Migration completed!")

if __name__ == "__main__":
    migrate()
