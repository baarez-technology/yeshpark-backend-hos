"""
Migration script to add new columns to the users table.
Run this script once to update the existing database.
"""
import sqlite3
import os

# Get the database path
DB_PATH = os.path.join(os.path.dirname(__file__), "glimmora.db")

def migrate():
    print(f"Migrating database at: {DB_PATH}")

    if not os.path.exists(DB_PATH):
        print("Database file not found!")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check existing columns in users table
    cursor.execute("PRAGMA table_info(users)")
    existing_columns = {row[1] for row in cursor.fetchall()}
    print(f"Existing columns: {existing_columns}")

    # Columns to add
    new_columns = [
        ("address", "TEXT"),
        ("city", "TEXT"),
        ("zip_code", "TEXT"),
        ("country", "TEXT"),
        ("preferences", "TEXT"),
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_columns:
            try:
                sql = f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"
                print(f"Adding column: {col_name}")
                cursor.execute(sql)
                print(f"  -> Added {col_name} successfully")
            except sqlite3.OperationalError as e:
                print(f"  -> Error adding {col_name}: {e}")
        else:
            print(f"Column {col_name} already exists, skipping")

    conn.commit()
    conn.close()
    print("\nMigration complete!")

if __name__ == "__main__":
    migrate()
