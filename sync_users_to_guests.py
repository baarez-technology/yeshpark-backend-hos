"""
Sync Users to Guests
Creates guest records for users who don't have one.
This ensures all registered users appear in the guests list.
"""
import sqlite3
import os
from datetime import datetime

def sync_users_to_guests():
    # Get database path relative to this script
    script_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(script_dir, 'glimmora.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    print("=== Syncing Users to Guests ===\n")

    # Find users who don't have a corresponding guest record
    # Check by user_id link OR by email match
    cursor.execute("""
        SELECT u.id, u.email, u.full_name, u.phone, u.address, u.city, u.country, u.zip_code, u.preferences, u.created_at
        FROM users u
        WHERE u.id NOT IN (SELECT COALESCE(user_id, 0) FROM guests WHERE user_id IS NOT NULL)
        AND u.email NOT IN (SELECT COALESCE(LOWER(email), '') FROM guests WHERE email IS NOT NULL)
    """)

    users_without_guests = cursor.fetchall()
    print(f"Found {len(users_without_guests)} users without guest records\n")

    created_count = 0
    for user in users_without_guests:
        user_id, email, full_name, phone, address, city, country, postal_code, preferences, created_at = user

        # Split full_name into first and last name
        name_parts = (full_name or "").split(" ", 1)
        first_name = name_parts[0] if name_parts else "Guest"
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        print(f"Creating guest for: {email} ({full_name})")

        cursor.execute("""
            INSERT INTO guests (
                user_id, first_name, last_name, email, phone,
                address, city, country, postal_code,
                status, emotion, loyalty_points, loyalty_tier,
                total_bookings, total_spent, total_nights,
                vip_status, id_verified, preferences, member_since, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            first_name,
            last_name,
            email,
            phone,
            address,
            city,
            country,
            postal_code,
            "Active",
            "neutral",  # Default emotion
            0,
            "member",
            0,
            0.0,
            0,
            False,  # vip_status
            False,  # id_verified
            preferences,  # Copy user preferences to guest
            created_at,
            datetime.utcnow().isoformat(),
            datetime.utcnow().isoformat()
        ))
        created_count += 1

    conn.commit()

    # Also link existing guests to users by email if not already linked
    print("\n=== Linking existing guests to users by email ===\n")

    cursor.execute("""
        SELECT g.id, g.email, u.id as user_id
        FROM guests g
        JOIN users u ON LOWER(g.email) = LOWER(u.email)
        WHERE g.user_id IS NULL AND g.email IS NOT NULL
    """)

    guests_to_link = cursor.fetchall()
    linked_count = 0

    for guest_id, email, user_id in guests_to_link:
        print(f"Linking guest {guest_id} ({email}) to user {user_id}")
        cursor.execute("UPDATE guests SET user_id = ? WHERE id = ?", (user_id, guest_id))
        linked_count += 1

    conn.commit()

    # Summary
    print("\n=== Summary ===")
    cursor.execute("SELECT COUNT(*) FROM guests")
    total_guests = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM guests WHERE user_id IS NOT NULL")
    linked_guests = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    print(f"Total users: {total_users}")
    print(f"Total guests: {total_guests}")
    print(f"Guests linked to users: {linked_guests}")
    print(f"New guest records created: {created_count}")
    print(f"Existing guests linked to users: {linked_count}")

    conn.close()
    print("\n=== Sync Complete ===")

if __name__ == "__main__":
    sync_users_to_guests()
