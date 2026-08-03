"""
Database Seed Script for Glimmora Hotel Management System
Clears existing data and seeds with realistic data matching frontend expectations.
"""
import sqlite3
import os
import json
from datetime import datetime, timedelta
import random
import hashlib

# Get the database path
DB_PATH = os.path.join(os.path.dirname(__file__), "glimmora.db")

# Password hashing (simple bcrypt-like for seeding)
def hash_password(password: str) -> str:
    """Simple password hash for seeding - in production use bcrypt"""
    import bcrypt
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def clear_database(cursor):
    """Clear all tables"""
    tables = [
        'precheckin', 'bookings', 'rooms', 'room_types', 'rateplan',
        'guests', 'users', 'housekeeping_tasks'
    ]

    for table in tables:
        try:
            cursor.execute(f"DELETE FROM {table}")
            print(f"  Cleared table: {table}")
        except sqlite3.OperationalError:
            print(f"  Table {table} does not exist, skipping")


def seed_users(cursor):
    """Seed admin and test users"""
    print("\nSeeding users...")

    users = [
        {
            "email": "admin@glimmora.com",
            "full_name": "Admin User",
            "phone": "+1 (555) 000-0001",
            "role": "admin",
            "is_superuser": True,
            "is_active": True,
            "email_verified": True,
            "password": "admin123",
        },
        {
            "email": "manager@glimmora.com",
            "full_name": "Sarah Manager",
            "phone": "+1 (555) 000-0002",
            "role": "manager",
            "is_superuser": False,
            "is_active": True,
            "email_verified": True,
        },
        {
            "email": "frontdesk@glimmora.com",
            "full_name": "John Frontdesk",
            "phone": "+1 (555) 000-0003",
            "role": "front_desk",
            "is_superuser": False,
            "is_active": True,
            "email_verified": True,
        },
        {
            "email": "guest@example.com",
            "full_name": "Test Guest",
            "phone": "+1 (555) 000-0004",
            "role": "guest",
            "is_superuser": False,
            "is_active": True,
            "email_verified": True,
        },
        # Staff accounts
        {
            "email": "maria@glimmora.local",
            "full_name": "Maria Housekeeping",
            "phone": "+1 (555) 000-0005",
            "role": "housekeeping",
            "is_superuser": False,
            "is_active": True,
            "email_verified": True,
            "password": "123456",
        },
        {
            "email": "john@glimmora.local",
            "full_name": "John Maintenance",
            "phone": "+1 (555) 000-0006",
            "role": "maintenance",
            "is_superuser": False,
            "is_active": True,
            "email_verified": True,
            "password": "123456",
        },
        {
            "email": "alex@glimmora.local",
            "full_name": "Alex Runner",
            "phone": "+1 (555) 000-0007",
            "role": "runner",
            "is_superuser": False,
            "is_active": True,
            "email_verified": True,
            "password": "123456",
        },
    ]

    default_password_hash = hash_password("password123")
    now = datetime.utcnow().isoformat()

    for user in users:
        # Use custom password if provided, otherwise use default
        if "password" in user:
            user_password_hash = hash_password(user["password"])
        else:
            user_password_hash = default_password_hash

        cursor.execute("""
            INSERT INTO users (email, hashed_password, full_name, phone, role, is_superuser, is_active, email_verified, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user["email"], user_password_hash, user["full_name"], user["phone"],
            user["role"], user["is_superuser"], user["is_active"], user["email_verified"],
            now, now
        ))
        print(f"  Created user: {user['email']}")


def seed_room_types(cursor):
    """Seed room types matching Hotel Yesh Park specification"""
    print("\nSeeding room types...")

    room_types = [
        {
            "name": "Suite",
            "slug": "sui",
            "category": "suite",
            "description": "Luxurious Suite room at Hotel Yesh Park featuring premium amenities, spacious layout, and maximum comfort.",
            "short_description": "Luxury suite with premium comfort - 8 Rooms available",
            "base_price": 4499.00,
            "max_guests": 3,
            "bed_type": "King Bed",
            "size_sqft": 450,
            "view_type": "City View",
            "amenities": json.dumps(["Free WiFi", "Air Conditioning", "Smart TV", "Mini Refrigerator", "Coffee Maker", "In-Room Safe", "Room Service", "Daily Housekeeping", "Work Desk", "Tax 5%"]),
            "features": json.dumps(["Spacious Suite Layout", "Luxury Bath", "Premium Bedding"]),
            "images": json.dumps([
                "/images/rooms/suite-1.jpg",
                "/images/rooms/suite-2.jpg"
            ]),
            "rating": 4.9,
            "review_count": 120,
            "is_active": True,
            "sort_order": 1
        },
        {
            "name": "Superior King",
            "slug": "suk",
            "category": "superior",
            "description": "Elegant Superior King room with plush king bed, work desk, and contemporary decor.",
            "short_description": "Superior King room - 24 Rooms available",
            "base_price": 2899.00,
            "max_guests": 3,
            "bed_type": "King Bed",
            "size_sqft": 350,
            "view_type": "City View",
            "amenities": json.dumps(["Free WiFi", "Air Conditioning", "Smart TV", "Mini Refrigerator", "Coffee Maker", "In-Room Safe", "Room Service", "Daily Housekeeping", "Work Desk", "Tax 5%"]),
            "features": json.dumps(["Plush King Bed", "Modern Amenities", "Work Station"]),
            "images": json.dumps([
                "/images/rooms/superior-king-1.jpg",
                "/images/rooms/superior-king-2.jpg"
            ]),
            "rating": 4.8,
            "review_count": 210,
            "is_active": True,
            "sort_order": 2
        },
        {
            "name": "Superior Twin",
            "slug": "sut",
            "category": "superior",
            "description": "Comfortable Superior Twin room with twin beds, modern workspace, and elegant finishes.",
            "short_description": "Superior Twin room - 8 Rooms available",
            "base_price": 2899.00,
            "max_guests": 3,
            "bed_type": "Twin Bed",
            "size_sqft": 350,
            "view_type": "City View",
            "amenities": json.dumps(["Free WiFi", "Air Conditioning", "Smart TV", "Mini Refrigerator", "Coffee Maker", "In-Room Safe", "Room Service", "Daily Housekeeping", "Work Desk", "Tax 5%"]),
            "features": json.dumps(["Twin Beds", "Work Space", "Modern Bathroom"]),
            "images": json.dumps([
                "/images/rooms/superior-twin-1.jpg",
                "/images/rooms/superior-twin-2.jpg"
            ]),
            "rating": 4.7,
            "review_count": 95,
            "is_active": True,
            "sort_order": 3
        }
    ]

    now = datetime.utcnow().isoformat()

    for rt in room_types:
        cursor.execute("""
            INSERT INTO room_types (name, slug, category, description, short_description, base_price, max_guests,
                bed_type, size_sqft, view_type, amenities, features, images, rating, review_count, is_active, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rt["name"], rt["slug"], rt["category"], rt["description"], rt["short_description"],
            rt["base_price"], rt["max_guests"], rt["bed_type"], rt["size_sqft"], rt["view_type"],
            rt["amenities"], rt["features"], rt["images"], rt["rating"], rt["review_count"],
            rt["is_active"], rt["sort_order"], now, now
        ))
        print(f"  Created room type: {rt['name']}")


def seed_rooms(cursor):
    """Seed individual rooms matching Hotel Yesh Park 40 rooms specification"""
    print("\nSeeding rooms...")

    # Get room type IDs
    cursor.execute("SELECT id, name, base_price, bed_type, max_guests FROM room_types")
    room_types = {row[1]: {"id": row[0], "price": row[1], "bed_type": row[3], "max_guests": row[4]} for row in cursor.fetchall()}

    rooms = [
        # SUI - SUITE (8 Rooms)
        {"number": "1001", "room_type": "Suite", "floor": 1, "status": "available", "view_type": "City View"},
        {"number": "1010", "room_type": "Suite", "floor": 1, "status": "available", "view_type": "City View"},
        {"number": "2001", "room_type": "Suite", "floor": 2, "status": "available", "view_type": "City View"},
        {"number": "2010", "room_type": "Suite", "floor": 2, "status": "available", "view_type": "City View"},
        {"number": "3001", "room_type": "Suite", "floor": 3, "status": "occupied", "view_type": "City View"},
        {"number": "3010", "room_type": "Suite", "floor": 3, "status": "available", "view_type": "City View"},
        {"number": "4001", "room_type": "Suite", "floor": 4, "status": "available", "view_type": "City View"},
        {"number": "4010", "room_type": "Suite", "floor": 4, "status": "available", "view_type": "City View"},

        # SUK - SUPERIOR KING (24 Rooms)
        # Floor 1 (4 rooms)
        {"number": "1002", "room_type": "Superior King", "floor": 1, "status": "available", "view_type": "City View"},
        {"number": "1006", "room_type": "Superior King", "floor": 1, "status": "available", "view_type": "City View"},
        {"number": "1008", "room_type": "Superior King", "floor": 1, "status": "available", "view_type": "City View"},
        {"number": "1009", "room_type": "Superior King", "floor": 1, "status": "cleaning", "view_type": "City View"},
        # Floor 2 (4 rooms)
        {"number": "2002", "room_type": "Superior King", "floor": 2, "status": "available", "view_type": "City View"},
        {"number": "2003", "room_type": "Superior King", "floor": 2, "status": "available", "view_type": "City View"},
        {"number": "2004", "room_type": "Superior King", "floor": 2, "status": "occupied", "view_type": "City View"},
        {"number": "2009", "room_type": "Superior King", "floor": 2, "status": "available", "view_type": "City View"},
        # Floor 3 (8 rooms)
        {"number": "3002", "room_type": "Superior King", "floor": 3, "status": "available", "view_type": "City View"},
        {"number": "3003", "room_type": "Superior King", "floor": 3, "status": "available", "view_type": "City View"},
        {"number": "3004", "room_type": "Superior King", "floor": 3, "status": "available", "view_type": "City View"},
        {"number": "3005", "room_type": "Superior King", "floor": 3, "status": "occupied", "view_type": "City View"},
        {"number": "3006", "room_type": "Superior King", "floor": 3, "status": "available", "view_type": "City View"},
        {"number": "3007", "room_type": "Superior King", "floor": 3, "status": "available", "view_type": "City View"},
        {"number": "3008", "room_type": "Superior King", "floor": 3, "status": "available", "view_type": "City View"},
        {"number": "3009", "room_type": "Superior King", "floor": 3, "status": "available", "view_type": "City View"},
        # Floor 4 (8 rooms)
        {"number": "4002", "room_type": "Superior King", "floor": 4, "status": "available", "view_type": "City View"},
        {"number": "4003", "room_type": "Superior King", "floor": 4, "status": "available", "view_type": "City View"},
        {"number": "4004", "room_type": "Superior King", "floor": 4, "status": "available", "view_type": "City View"},
        {"number": "4005", "room_type": "Superior King", "floor": 4, "status": "available", "view_type": "City View"},
        {"number": "4006", "room_type": "Superior King", "floor": 4, "status": "available", "view_type": "City View"},
        {"number": "4007", "room_type": "Superior King", "floor": 4, "status": "available", "view_type": "City View"},
        {"number": "4008", "room_type": "Superior King", "floor": 4, "status": "available", "view_type": "City View"},
        {"number": "4009", "room_type": "Superior King", "floor": 4, "status": "available", "view_type": "City View"},

        # SUT - SUPERIOR TWIN (8 Rooms)
        # Floor 1 (4 rooms)
        {"number": "1003", "room_type": "Superior Twin", "floor": 1, "status": "available", "view_type": "City View"},
        {"number": "1004", "room_type": "Superior Twin", "floor": 1, "status": "available", "view_type": "City View"},
        {"number": "1005", "room_type": "Superior Twin", "floor": 1, "status": "occupied", "view_type": "City View"},
        {"number": "1007", "room_type": "Superior Twin", "floor": 1, "status": "available", "view_type": "City View"},
        # Floor 2 (4 rooms)
        {"number": "2005", "room_type": "Superior Twin", "floor": 2, "status": "available", "view_type": "City View"},
        {"number": "2006", "room_type": "Superior Twin", "floor": 2, "status": "available", "view_type": "City View"},
        {"number": "2007", "room_type": "Superior Twin", "floor": 2, "status": "available", "view_type": "City View"},
        {"number": "2008", "room_type": "Superior Twin", "floor": 2, "status": "available", "view_type": "City View"},
    ]

    now = datetime.utcnow().isoformat()

    for room in rooms:
        rt = room_types.get(room["room_type"])
        if rt:
            amenities = json.dumps(["Free WiFi", "Air Conditioning", "Smart TV", "Mini Bar", "Room Service"])
            cursor.execute("""
                INSERT INTO rooms (number, room_type_id, floor, status, bed_type, view_type,
                    capacity, max_occupancy, amenities, is_smoking, is_accessible, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                room["number"], rt["id"], room["floor"], room["status"],
                rt["bed_type"], room["view_type"], rt["max_guests"], rt["max_guests"] + 1,
                amenities, False, False, now, now
            ))
            print(f"  Created room: {room['number']} ({room['room_type']})")


def seed_rate_plans(cursor):
    """Seed rate plans - skipping if table doesn't exist"""
    print("\nSeeding rate plans...")

    # Check if rateplan table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='rateplan'")
    if not cursor.fetchone():
        print("  Rate plans table doesn't exist, skipping...")
        return

    # Check schema
    cursor.execute("PRAGMA table_info(rateplan)")
    columns = {row[1] for row in cursor.fetchall()}
    print(f"  Available columns: {columns}")

    # Rate plans data - will use whatever columns exist
    rate_plans = [
        {"code": "BAR", "name": "Best Available Rate", "plan_type": "standard", "base_price": 1.0, "description": "Our standard rate", "is_active": True},
        {"code": "ADVANCE", "name": "Advance Purchase", "plan_type": "advance", "base_price": 0.85, "description": "Book 14+ days ahead for 15% off", "is_active": True},
        {"code": "MEMBER", "name": "Member Rate", "plan_type": "loyalty", "base_price": 0.90, "description": "Exclusive rate for members", "is_active": True},
        {"code": "WEEKEND", "name": "Weekend Getaway", "plan_type": "package", "base_price": 0.95, "description": "Special weekend package", "is_active": True},
    ]

    now = datetime.utcnow().isoformat()

    for rp in rate_plans:
        try:
            cursor.execute("""
                INSERT INTO rateplan (code, name, plan_type, base_price, currency, description, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (rp["code"], rp["name"], rp["plan_type"], rp["base_price"], "INR", rp["description"], rp["is_active"], now, now))
            print(f"  Created rate plan: {rp['name']}")
        except sqlite3.OperationalError as e:
            print(f"  Error creating rate plan {rp['name']}: {e}")


def seed_guests(cursor):
    """Seed guests matching frontend data"""
    print("\nSeeding guests...")

    guests = [
        {
            "first_name": "Sarah", "last_name": "Anderson",
            "email": "sarah.anderson@email.com", "phone": "+1 (555) 123-4567",
            "country": "United States", "city": "Los Angeles", "address": "123 Main St",
            "status": "Active", "vip_status": True, "loyalty_tier": "platinum",
            "total_bookings": 12, "total_spent": 18500.00, "total_nights": 45,
            "preferences": json.dumps({"bedType": "King", "floor": "High Floor", "allergies": "None", "notes": "Prefers room with ocean view"})
        },
        {
            "first_name": "James", "last_name": "Mitchell",
            "email": "james.mitchell@email.co.uk", "phone": "+44 20 7946 0958",
            "country": "United Kingdom", "city": "London", "address": "45 Baker Street",
            "status": "Active", "vip_status": False, "loyalty_tier": "silver",
            "total_bookings": 5, "total_spent": 6250.00, "total_nights": 15,
            "preferences": json.dumps({"bedType": "Queen", "floor": "Any", "allergies": "Peanuts", "notes": "Business traveler, early check-in preferred"})
        },
        {
            "first_name": "Maria", "last_name": "Garcia",
            "email": "maria.garcia@email.es", "phone": "+34 91 123 4567",
            "country": "Spain", "city": "Madrid", "address": "Calle Gran Via 10",
            "status": "Active", "vip_status": True, "loyalty_tier": "gold",
            "total_bookings": 8, "total_spent": 12400.00, "total_nights": 35,
            "preferences": json.dumps({"bedType": "King", "floor": "Top Floor", "allergies": "Gluten", "notes": "Spa packages preferred"})
        },
        {
            "first_name": "David", "last_name": "Chen",
            "email": "david.chen@email.cn", "phone": "+86 10 1234 5678",
            "country": "China", "city": "Beijing", "address": "Chaoyang District",
            "status": "Active", "vip_status": False, "loyalty_tier": "bronze",
            "total_bookings": 1, "total_spent": 790.00, "total_nights": 2,
            "preferences": json.dumps({"bedType": "Twin", "floor": "Low Floor", "allergies": "None"})
        },
        {
            "first_name": "Emma", "last_name": "Wilson",
            "email": "emma.wilson@email.au", "phone": "+61 2 9876 5432",
            "country": "Australia", "city": "Sydney", "address": "42 George Street",
            "status": "Active", "vip_status": False, "loyalty_tier": "silver",
            "total_bookings": 6, "total_spent": 9840.00, "total_nights": 24,
            "preferences": json.dumps({"bedType": "King", "floor": "Mid Floor", "allergies": "Dairy", "notes": "Vegan meals preferred"})
        },
        {
            "first_name": "Hiroshi", "last_name": "Tanaka",
            "email": "h.tanaka@email.jp", "phone": "+81 3 1234 5678",
            "country": "Japan", "city": "Tokyo", "address": "Shibuya-ku",
            "status": "Active", "vip_status": True, "loyalty_tier": "platinum",
            "total_bookings": 15, "total_spent": 52500.00, "total_nights": 80,
            "preferences": json.dumps({"bedType": "King", "floor": "Top Floor", "notes": "Executive suite only"})
        },
        {
            "first_name": "Sophie", "last_name": "Dubois",
            "email": "sophie.dubois@email.fr", "phone": "+33 1 42 86 82 00",
            "country": "France", "city": "Paris", "address": "8 Rue de Rivoli",
            "status": "Active", "vip_status": False, "loyalty_tier": "silver",
            "total_bookings": 4, "total_spent": 4950.00, "total_nights": 12,
            "preferences": json.dumps({"bedType": "Queen", "floor": "Any", "notes": "Wine enthusiast"})
        },
        {
            "first_name": "Michael", "last_name": "Brown",
            "email": "michael.brown@email.com", "phone": "+1 (555) 234-5678",
            "country": "United States", "city": "New York", "address": "500 5th Avenue",
            "status": "Active", "vip_status": False, "loyalty_tier": "gold",
            "total_bookings": 7, "total_spent": 8750.00, "total_nights": 21,
            "preferences": json.dumps({"bedType": "King", "floor": "High Floor", "notes": "Business traveler"})
        },
        {
            "first_name": "Isabella", "last_name": "Rossi",
            "email": "isabella.rossi@email.it", "phone": "+39 06 1234 5678",
            "country": "Italy", "city": "Rome", "address": "Via Veneto 50",
            "status": "Active", "vip_status": True, "loyalty_tier": "gold",
            "total_bookings": 9, "total_spent": 14200.00, "total_nights": 40,
            "preferences": json.dumps({"bedType": "King", "floor": "Any", "notes": "Art lover, museum tours"})
        },
        {
            "first_name": "William", "last_name": "Johnson",
            "email": "william.johnson@email.com", "phone": "+1 (555) 345-6789",
            "country": "United States", "city": "Chicago", "address": "100 Michigan Ave",
            "status": "Active", "vip_status": False, "loyalty_tier": "bronze",
            "total_bookings": 2, "total_spent": 1580.00, "total_nights": 4,
            "preferences": json.dumps({"bedType": "Queen", "floor": "Any"})
        },
    ]

    now = datetime.utcnow().isoformat()

    emotions = ["happy", "neutral", "satisfied"]

    for i, guest in enumerate(guests):
        cursor.execute("""
            INSERT INTO guests (first_name, last_name, email, phone, country, city, address,
                status, emotion, vip_status, loyalty_tier, loyalty_points, total_bookings, total_spent, total_nights,
                preferences, id_verified, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            guest["first_name"], guest["last_name"], guest["email"], guest["phone"],
            guest["country"], guest["city"], guest["address"], guest["status"],
            emotions[i % len(emotions)],  # Cycle through emotions
            guest["vip_status"], guest["loyalty_tier"], int(guest["total_spent"] * 0.1),
            guest["total_bookings"], guest["total_spent"], guest["total_nights"],
            guest["preferences"], True,  # id_verified
            now, now
        ))
        print(f"  Created guest: {guest['first_name']} {guest['last_name']}")


def seed_bookings(cursor):
    """Seed bookings"""
    print("\nSeeding bookings...")

    # Get guest IDs
    cursor.execute("SELECT id, email FROM guests")
    guests = {row[1]: row[0] for row in cursor.fetchall()}

    # Get room IDs and room_type_ids
    cursor.execute("SELECT id, number, room_type_id FROM rooms")
    rooms = {row[1]: {"id": row[0], "room_type_id": row[2]} for row in cursor.fetchall()}

    today = datetime.now().date()

    bookings_data = [
        {
            "booking_number": "BK-2024-001001",
            "confirmation_code": "GLM-001001",
            "guest_email": "sarah.anderson@email.com",
            "room_number": "3001",
            "arrival_date": today - timedelta(days=2),
            "departure_date": today + timedelta(days=1),
            "adults": 2, "children": 0,
            "status": "checked_in",
            "payment_status": "paid",
            "total_price": 13497.00,
            "special_requests": "Late check-in requested",
            "booking_source": "direct"
        },
        {
            "booking_number": "BK-2024-001002",
            "confirmation_code": "GLM-001002",
            "guest_email": "james.mitchell@email.co.uk",
            "room_number": "2001",
            "arrival_date": today,
            "departure_date": today + timedelta(days=2),
            "adults": 1, "children": 0,
            "status": "confirmed",
            "payment_status": "pending",
            "total_price": 8998.00,
            "special_requests": "High floor preferred",
            "booking_source": "ota"
        },
        {
            "booking_number": "BK-2024-001003",
            "confirmation_code": "GLM-001003",
            "guest_email": "maria.garcia@email.es",
            "room_number": "4001",
            "arrival_date": today - timedelta(days=1),
            "departure_date": today + timedelta(days=2),
            "adults": 2, "children": 0,
            "status": "checked_in",
            "payment_status": "paid",
            "total_price": 13497.00,
            "special_requests": "Anniversary celebration",
            "booking_source": "direct"
        },
        {
            "booking_number": "BK-2024-001004",
            "confirmation_code": "GLM-001004",
            "guest_email": "h.tanaka@email.jp",
            "room_number": "1001",
            "arrival_date": today + timedelta(days=3),
            "departure_date": today + timedelta(days=8),
            "adults": 2, "children": 0,
            "status": "confirmed",
            "payment_status": "partial",
            "total_price": 22495.00,
            "special_requests": "Executive client, complete privacy required",
            "booking_source": "direct"
        },
        {
            "booking_number": "BK-2024-001005",
            "confirmation_code": "GLM-001005",
            "guest_email": "emma.wilson@email.au",
            "room_number": "1005",
            "arrival_date": today - timedelta(days=3),
            "departure_date": today,
            "adults": 2, "children": 1,
            "status": "checked_in",
            "payment_status": "paid",
            "total_price": 8697.00,
            "special_requests": "Family vacation, extra bed needed",
            "booking_source": "ota"
        },
        {
            "booking_number": "BK-2024-001006",
            "confirmation_code": "GLM-001006",
            "guest_email": "michael.brown@email.com",
            "room_number": "2004",
            "arrival_date": today - timedelta(days=1),
            "departure_date": today + timedelta(days=3),
            "adults": 2, "children": 0,
            "status": "checked_in",
            "payment_status": "paid",
            "total_price": 11596.00,
            "special_requests": "Business trip",
            "booking_source": "direct"
        },
        {
            "booking_number": "BK-2024-001007",
            "confirmation_code": "GLM-001007",
            "guest_email": "sophie.dubois@email.fr",
            "room_number": "3003",
            "arrival_date": today + timedelta(days=5),
            "departure_date": today + timedelta(days=8),
            "adults": 2, "children": 0,
            "status": "confirmed",
            "payment_status": "pending",
            "total_price": 8697.00,
            "special_requests": "Quiet room requested",
            "booking_source": "direct"
        },
        {
            "booking_number": "BK-2024-001008",
            "confirmation_code": "GLM-001008",
            "guest_email": "isabella.rossi@email.it",
            "room_number": "2008",
            "arrival_date": today + timedelta(days=7),
            "departure_date": today + timedelta(days=12),
            "adults": 1, "children": 0,
            "status": "confirmed",
            "payment_status": "partial",
            "total_price": 12495.00,
            "special_requests": "Single occupancy",
            "booking_source": "direct"
        },
        {
            "booking_number": "BK-2024-001009",
            "confirmation_code": "GLM-001009",
            "guest_email": "william.johnson@email.com",
            "room_number": "1002",
            "arrival_date": today + timedelta(days=1),
            "departure_date": today + timedelta(days=3),
            "adults": 2, "children": 0,
            "status": "confirmed",
            "payment_status": "pending",
            "total_price": 5798.00,
            "special_requests": "",
            "booking_source": "ota"
        },
        {
            "booking_number": "BK-2024-001010",
            "confirmation_code": "GLM-001010",
            "guest_email": "david.chen@email.cn",
            "room_number": "1003",
            "arrival_date": today - timedelta(days=1),
            "departure_date": today + timedelta(days=1),
            "adults": 1, "children": 0,
            "status": "checked_in",
            "payment_status": "paid",
            "total_price": 4998.00,
            "special_requests": "",
            "booking_source": "direct"
        },
    ]

    now = datetime.utcnow().isoformat()

    for bk in bookings_data:
        guest_id = guests.get(bk["guest_email"])
        room_info = rooms.get(bk["room_number"])

        if guest_id and room_info:
            nights = (bk["departure_date"] - bk["arrival_date"]).days
            base_price = bk["total_price"] * 0.85
            taxes = bk["total_price"] * 0.10
            service_fee = bk["total_price"] * 0.05

            cursor.execute("""
                INSERT INTO bookings (booking_number, confirmation_code, guest_id, room_type_id, room_id,
                    arrival_date, departure_date, adults, children, infants, nights, status, payment_status,
                    booking_source, base_price, taxes, service_fee, total_price, discount_amount,
                    special_requests, is_group_booking, vip_flag, modification_count, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                bk["booking_number"], bk["confirmation_code"], guest_id,
                room_info["room_type_id"], room_info["id"],
                bk["arrival_date"].isoformat(), bk["departure_date"].isoformat(),
                bk["adults"], bk["children"], 0, nights, bk["status"], bk["payment_status"],
                bk["booking_source"], base_price, taxes, service_fee, bk["total_price"], 0.0,  # discount_amount
                bk["special_requests"], False, False, 0,  # is_group_booking, vip_flag, modification_count
                now, now
            ))
            print(f"  Created booking: {bk['booking_number']} for {bk['guest_email']}")


def main():
    print("=" * 60)
    print("Glimmora Database Seed Script")
    print("=" * 60)

    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        print("Please run the backend first to create the database.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        print("\n[Step 1] Clearing existing data...")
        clear_database(cursor)

        print("\n[Step 2] Seeding users...")
        seed_users(cursor)

        print("\n[Step 3] Seeding room types...")
        seed_room_types(cursor)

        print("\n[Step 4] Seeding rooms...")
        seed_rooms(cursor)

        print("\n[Step 5] Seeding rate plans...")
        seed_rate_plans(cursor)

        print("\n[Step 6] Seeding guests...")
        seed_guests(cursor)

        print("\n[Step 7] Seeding bookings...")
        seed_bookings(cursor)

        conn.commit()
        print("\n" + "=" * 60)
        print("Database seeding completed successfully!")
        print("=" * 60)
        print("\nDefault login credentials:")
        print("  Admin: admin@glimmora.com / admin123")
        print("  Manager: manager@glimmora.com / password123")
        print("  Front Desk: frontdesk@glimmora.com / password123")
        print("  Guest: guest@example.com / password123")
        print("\nStaff credentials:")
        print("  Housekeeping: maria@glimmora.local / 123456")
        print("  Maintenance: john@glimmora.local / 123456")
        print("  Runner: alex@glimmora.local / 123456")

    except Exception as e:
        print(f"\nError during seeding: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
