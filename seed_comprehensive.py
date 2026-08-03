"""
Comprehensive Database Seed Script for Glimmora Hotel Management System
Creates presentable demo data for all aspects of the system.
"""
import sqlite3
import os
import json
from datetime import datetime, timedelta, date, time
import random
import string

# Get the database path
DB_PATH = os.path.join(os.path.dirname(__file__), "glimmora.db")

def hash_password(password: str) -> str:
    """Password hash using passlib bcrypt (same as app)"""
    from passlib.context import CryptContext
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    return pwd_context.hash(password)

def generate_id(prefix: str, num: int) -> str:
    """Generate ID like WO-2024-001"""
    return f"{prefix}-{datetime.now().year}-{str(num).zfill(6)}"

def random_phone():
    return f"+1 (555) {random.randint(100,999)}-{random.randint(1000,9999)}"

def clear_all_tables(cursor):
    """Clear all tables for fresh seed"""
    tables = [
        # Core
        'users', 'guests', 'bookings', 'reservation', 'rooms', 'room_types', 'rateplan',
        # Staff
        'staff', 'staff_attendance', 'staff_performance_metrics', 'staff_schedules',
        'staff_leave', 'staff_certifications', 'staff_training',
        # Operations
        'housekeeping_tasks', 'housekeeping_checklist_templates', 'housekeeping_supplies',
        'maintenancerequest', 'equipment_issues', 'maintenance_parts', 'vendors',
        'preventive_maintenance_schedules',
        'runner_pickup_requests', 'runner_deliveries', 'runner_activity_log',
        'lostfound', 'lineninventory',
        # Reviews & CRM
        'reviews', 'ota_stats', 'sentiment_trends',
        'guest_feedback', 'guest_special_requests', 'guest_stay_history',
        'crm_guest_activities', 'crm_segments', 'guest_segments',
        'loyalty_tiers', 'loyalty_transactions', 'campaigns',
        # Finance
        'folio', 'foliolineitem', 'payment',
        'pricing_adjustments', 'channel_performance', 'dynamic_pricing_rules',
        'competitor_data', 'forecast_data',
        # Other
        'guestcommunication', 'nightaudit', 'shifthandover',
        'keycard', 'digital_keys',
    ]

    for table in tables:
        try:
            cursor.execute(f"DELETE FROM {table}")
            print(f"  Cleared: {table}")
        except sqlite3.OperationalError:
            pass  # Table doesn't exist

def seed_users(cursor):
    """Seed comprehensive user accounts"""
    print("\n[1/15] Seeding users...")

    now = datetime.utcnow().isoformat()

    users = [
        # Admin & Management
        {"email": "admin@glimmora.com", "name": "Admin User", "role": "admin", "password": "admin123", "is_superuser": True},
        {"email": "gm@glimmora.com", "name": "Robert Sterling", "role": "owner", "password": "password123", "is_superuser": True},
        {"email": "manager@glimmora.com", "name": "Sarah Mitchell", "role": "manager", "password": "password123"},
        {"email": "assistant.manager@glimmora.com", "name": "David Kim", "role": "manager", "password": "password123"},

        # Front Desk
        {"email": "frontdesk@glimmora.com", "name": "Emily Chen", "role": "front_desk", "password": "password123"},
        {"email": "reception1@glimmora.com", "name": "Michael Torres", "role": "front_desk", "password": "password123"},
        {"email": "reception2@glimmora.com", "name": "Jessica Park", "role": "front_desk", "password": "password123"},
        {"email": "nightaudit@glimmora.com", "name": "Thomas Wright", "role": "front_desk", "password": "password123"},

        # Housekeeping
        {"email": "maria@glimmora.local", "name": "Maria Santos", "role": "housekeeping", "password": "123456"},
        {"email": "rosa@glimmora.local", "name": "Rosa Martinez", "role": "housekeeping", "password": "123456"},
        {"email": "linda@glimmora.local", "name": "Linda Nguyen", "role": "housekeeping", "password": "123456"},
        {"email": "carmen@glimmora.local", "name": "Carmen Lopez", "role": "housekeeping", "password": "123456"},
        {"email": "anna@glimmora.local", "name": "Anna Kowalski", "role": "housekeeping", "password": "123456"},
        {"email": "housekeeping.sup@glimmora.com", "name": "Gloria Reyes", "role": "housekeeping", "password": "password123"},

        # Maintenance
        {"email": "john@glimmora.local", "name": "John Miller", "role": "maintenance", "password": "123456"},
        {"email": "carlos@glimmora.local", "name": "Carlos Rodriguez", "role": "maintenance", "password": "123456"},
        {"email": "mike@glimmora.local", "name": "Mike Johnson", "role": "maintenance", "password": "123456"},
        {"email": "maintenance.sup@glimmora.com", "name": "Frank Thompson", "role": "maintenance", "password": "password123"},

        # Runners/Bell Staff
        {"email": "alex@glimmora.local", "name": "Alex Rivera", "role": "runner", "password": "123456"},
        {"email": "james@glimmora.local", "name": "James Lee", "role": "runner", "password": "123456"},
        {"email": "kevin@glimmora.local", "name": "Kevin Patel", "role": "runner", "password": "123456"},
        {"email": "ryan@glimmora.local", "name": "Ryan O'Connor", "role": "runner", "password": "123456"},

        # Finance
        {"email": "finance@glimmora.com", "name": "Patricia Williams", "role": "finance", "password": "password123"},
        {"email": "accounting@glimmora.com", "name": "Steven Brown", "role": "finance", "password": "password123"},

        # Guest accounts
        {"email": "guest@example.com", "name": "Test Guest", "role": "guest", "password": "password123"},
    ]

    user_ids = {}
    for user in users:
        pw_hash = hash_password(user["password"])
        cursor.execute("""
            INSERT INTO users (email, hashed_password, full_name, phone, role, is_superuser, is_active, email_verified, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?)
        """, (user["email"], pw_hash, user["name"], random_phone(), user["role"], user.get("is_superuser", False), now, now))
        user_ids[user["email"]] = cursor.lastrowid
        print(f"    Created user: {user['email']} ({user['role']})")

    return user_ids

def seed_staff(cursor, user_ids):
    """Seed staff records linked to users"""
    print("\n[2/15] Seeding staff records...")

    now = datetime.utcnow().isoformat()
    today = date.today()

    staff_data = [
        # Management
        {"email": "gm@glimmora.com", "dept": "management", "shift": "day", "emp_id": "MGR-001", "salary": 120000, "hire_days_ago": 1825},
        {"email": "manager@glimmora.com", "dept": "management", "shift": "day", "emp_id": "MGR-002", "salary": 85000, "hire_days_ago": 730},
        {"email": "assistant.manager@glimmora.com", "dept": "management", "shift": "day", "emp_id": "MGR-003", "salary": 65000, "hire_days_ago": 365},

        # Front Desk
        {"email": "frontdesk@glimmora.com", "dept": "frontdesk", "shift": "morning", "emp_id": "FD-001", "hourly": 22, "hire_days_ago": 540},
        {"email": "reception1@glimmora.com", "dept": "frontdesk", "shift": "afternoon", "emp_id": "FD-002", "hourly": 20, "hire_days_ago": 365},
        {"email": "reception2@glimmora.com", "dept": "frontdesk", "shift": "morning", "emp_id": "FD-003", "hourly": 20, "hire_days_ago": 180},
        {"email": "nightaudit@glimmora.com", "dept": "frontdesk", "shift": "night", "emp_id": "FD-004", "hourly": 24, "hire_days_ago": 450},

        # Housekeeping
        {"email": "housekeeping.sup@glimmora.com", "dept": "housekeeping", "shift": "day", "emp_id": "HK-001", "salary": 52000, "hire_days_ago": 900, "is_supervisor": True},
        {"email": "maria@glimmora.local", "dept": "housekeeping", "shift": "morning", "emp_id": "HK-002", "hourly": 18, "hire_days_ago": 720, "floors": [1,2]},
        {"email": "rosa@glimmora.local", "dept": "housekeeping", "shift": "morning", "emp_id": "HK-003", "hourly": 18, "hire_days_ago": 540, "floors": [3,4]},
        {"email": "linda@glimmora.local", "dept": "housekeeping", "shift": "afternoon", "emp_id": "HK-004", "hourly": 17, "hire_days_ago": 365, "floors": [5,6]},
        {"email": "carmen@glimmora.local", "dept": "housekeeping", "shift": "morning", "emp_id": "HK-005", "hourly": 17, "hire_days_ago": 270, "floors": [1,2,3]},
        {"email": "anna@glimmora.local", "dept": "housekeeping", "shift": "afternoon", "emp_id": "HK-006", "hourly": 16, "hire_days_ago": 90, "floors": [4,5,6,7]},

        # Maintenance
        {"email": "maintenance.sup@glimmora.com", "dept": "maintenance", "shift": "day", "emp_id": "MT-001", "salary": 58000, "hire_days_ago": 1095, "specialty": "general", "is_supervisor": True},
        {"email": "john@glimmora.local", "dept": "maintenance", "shift": "morning", "emp_id": "MT-002", "hourly": 25, "hire_days_ago": 730, "specialty": "electrical"},
        {"email": "carlos@glimmora.local", "dept": "maintenance", "shift": "afternoon", "emp_id": "MT-003", "hourly": 24, "hire_days_ago": 450, "specialty": "plumbing"},
        {"email": "mike@glimmora.local", "dept": "maintenance", "shift": "morning", "emp_id": "MT-004", "hourly": 23, "hire_days_ago": 180, "specialty": "hvac"},

        # Runners
        {"email": "alex@glimmora.local", "dept": "runner", "shift": "morning", "emp_id": "RN-001", "hourly": 16, "hire_days_ago": 365},
        {"email": "james@glimmora.local", "dept": "runner", "shift": "afternoon", "emp_id": "RN-002", "hourly": 16, "hire_days_ago": 270},
        {"email": "kevin@glimmora.local", "dept": "runner", "shift": "evening", "emp_id": "RN-003", "hourly": 16, "hire_days_ago": 180},
        {"email": "ryan@glimmora.local", "dept": "runner", "shift": "morning", "emp_id": "RN-004", "hourly": 15, "hire_days_ago": 60},

        # Finance
        {"email": "finance@glimmora.com", "dept": "finance", "shift": "day", "emp_id": "FN-001", "salary": 72000, "hire_days_ago": 1460},
        {"email": "accounting@glimmora.com", "dept": "finance", "shift": "day", "emp_id": "FN-002", "salary": 55000, "hire_days_ago": 540},
    ]

    shift_times = {
        "morning": (time(6, 0), time(14, 0)),
        "afternoon": (time(14, 0), time(22, 0)),
        "evening": (time(16, 0), time(0, 0)),
        "night": (time(22, 0), time(6, 0)),
        "day": (time(8, 0), time(17, 0)),
    }

    staff_ids = {}
    supervisor_map = {}  # dept -> supervisor staff_id

    for s in staff_data:
        user_id = user_ids.get(s["email"])
        if not user_id:
            continue

        hire_date = (today - timedelta(days=s["hire_days_ago"])).isoformat()
        shift_start, shift_end = shift_times.get(s["shift"], (time(8,0), time(17,0)))

        # Get user name from users table
        cursor.execute("SELECT full_name FROM users WHERE id = ?", (user_id,))
        name = cursor.fetchone()[0]

        skills = json.dumps(["Customer Service", "Safety Training", "First Aid"])
        languages = json.dumps(["English", "Spanish"] if random.random() > 0.5 else ["English"])
        certifications = json.dumps(["Safety Training", "Fire Safety"])
        floors = json.dumps(s.get("floors", []))

        cursor.execute("""
            INSERT INTO staff (user_id, employee_id, name, email, phone, role, department, specialty, status, shift,
                shift_start, shift_end, clocked_in, floor_assignment, hire_date, salary, hourly_rate,
                performance_rating, certifications, skills, languages_spoken, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id, s["emp_id"], name, s["email"], random_phone(),
            s["dept"], s["dept"], s.get("specialty"),
            s["shift"], shift_start.isoformat(), shift_end.isoformat(),
            random.choice([True, False]),
            floors, hire_date,
            s.get("salary"), s.get("hourly"),
            round(random.uniform(3.5, 5.0), 1),
            certifications, skills, languages, now, now
        ))

        staff_id = cursor.lastrowid
        staff_ids[s["email"]] = staff_id

        if s.get("is_supervisor"):
            supervisor_map[s["dept"]] = staff_id

        print(f"    Created staff: {name} ({s['dept']})")

    # Update supervisors
    for s in staff_data:
        if not s.get("is_supervisor") and s["dept"] in supervisor_map:
            cursor.execute("UPDATE staff SET supervisor_id = ? WHERE employee_id = ?",
                         (supervisor_map[s["dept"]], s["emp_id"]))

    return staff_ids

def seed_guests(cursor):
    """Seed comprehensive guest data"""
    print("\n[3/15] Seeding guests...")

    now = datetime.utcnow().isoformat()

    guests = [
        # VIP Platinum Guests
        {"first": "Victoria", "last": "Blackwood", "email": "v.blackwood@fortune500.com", "country": "United States", "city": "Manhattan, NY",
         "vip": True, "tier": "platinum", "bookings": 45, "spent": 156000, "nights": 180, "emotion": "happy",
         "prefs": {"bedType": "California King", "floor": "Penthouse", "temperature": "68F", "minibar": "Premium wines only"}},
        {"first": "Hiroshi", "last": "Tanaka", "email": "h.tanaka@tanaka-corp.jp", "country": "Japan", "city": "Tokyo",
         "vip": True, "tier": "platinum", "bookings": 38, "spent": 142000, "nights": 150, "emotion": "happy",
         "prefs": {"bedType": "King", "floor": "High Floor", "notes": "Japanese breakfast, green tea service"}},
        {"first": "Sheikh", "last": "Al-Rashid", "email": "al.rashid@emirates-holdings.ae", "country": "UAE", "city": "Dubai",
         "vip": True, "tier": "platinum", "bookings": 22, "spent": 198000, "nights": 90, "emotion": "satisfied",
         "prefs": {"bedType": "King", "floor": "Presidential Suite Only", "notes": "Halal cuisine, prayer mat"}},

        # VIP Gold Guests
        {"first": "Sarah", "last": "Anderson", "email": "sarah.anderson@email.com", "country": "United States", "city": "Los Angeles",
         "vip": True, "tier": "gold", "bookings": 18, "spent": 32500, "nights": 65, "emotion": "happy",
         "prefs": {"bedType": "King", "floor": "High Floor", "allergies": "None", "notes": "Ocean view preferred"}},
        {"first": "Jean-Pierre", "last": "Dubois", "email": "jp.dubois@luxurytravel.fr", "country": "France", "city": "Paris",
         "vip": True, "tier": "gold", "bookings": 15, "spent": 28000, "nights": 52, "emotion": "happy",
         "prefs": {"bedType": "King", "floor": "Suite", "notes": "Wine connoisseur, arrange sommelier"}},
        {"first": "Isabella", "last": "Rossi", "email": "isabella.rossi@email.it", "country": "Italy", "city": "Rome",
         "vip": True, "tier": "gold", "bookings": 14, "spent": 24500, "nights": 48, "emotion": "satisfied",
         "prefs": {"bedType": "King", "floor": "Any", "notes": "Art lover, museum tour arrangements"}},

        # Silver Tier Guests
        {"first": "James", "last": "Mitchell", "email": "james.mitchell@email.co.uk", "country": "United Kingdom", "city": "London",
         "vip": False, "tier": "silver", "bookings": 8, "spent": 12500, "nights": 28, "emotion": "neutral",
         "prefs": {"bedType": "Queen", "floor": "Any", "allergies": "Peanuts", "notes": "Business traveler"}},
        {"first": "Maria", "last": "Garcia", "email": "maria.garcia@email.es", "country": "Spain", "city": "Madrid",
         "vip": False, "tier": "silver", "bookings": 7, "spent": 11200, "nights": 25, "emotion": "happy",
         "prefs": {"bedType": "King", "floor": "Mid Floor", "allergies": "Gluten", "notes": "Spa packages"}},
        {"first": "Emma", "last": "Wilson", "email": "emma.wilson@email.au", "country": "Australia", "city": "Sydney",
         "vip": False, "tier": "silver", "bookings": 6, "spent": 9840, "nights": 24, "emotion": "happy",
         "prefs": {"bedType": "King", "floor": "Mid Floor", "allergies": "Dairy", "notes": "Vegan meals"}},
        {"first": "Michael", "last": "Brown", "email": "michael.brown@email.com", "country": "United States", "city": "Chicago",
         "vip": False, "tier": "silver", "bookings": 7, "spent": 8750, "nights": 21, "emotion": "satisfied",
         "prefs": {"bedType": "King", "floor": "High Floor", "notes": "Business traveler, quiet room"}},
        {"first": "Sophie", "last": "Martin", "email": "sophie.martin@email.fr", "country": "France", "city": "Lyon",
         "vip": False, "tier": "silver", "bookings": 5, "spent": 7200, "nights": 18, "emotion": "happy",
         "prefs": {"bedType": "Queen", "floor": "Any", "notes": "Wine enthusiast"}},

        # Bronze Tier Guests
        {"first": "David", "last": "Chen", "email": "david.chen@email.cn", "country": "China", "city": "Shanghai",
         "vip": False, "tier": "bronze", "bookings": 3, "spent": 2850, "nights": 8, "emotion": "neutral",
         "prefs": {"bedType": "Twin", "floor": "Low Floor"}},
        {"first": "William", "last": "Johnson", "email": "william.johnson@email.com", "country": "United States", "city": "Houston",
         "vip": False, "tier": "bronze", "bookings": 2, "spent": 1580, "nights": 4, "emotion": "neutral",
         "prefs": {"bedType": "Queen", "floor": "Any"}},
        {"first": "Anna", "last": "Mueller", "email": "anna.mueller@email.de", "country": "Germany", "city": "Berlin",
         "vip": False, "tier": "bronze", "bookings": 2, "spent": 1450, "nights": 5, "emotion": "happy",
         "prefs": {"bedType": "Queen", "floor": "Non-smoking"}},
        {"first": "Lucas", "last": "Silva", "email": "lucas.silva@email.br", "country": "Brazil", "city": "Sao Paulo",
         "vip": False, "tier": "bronze", "bookings": 1, "spent": 890, "nights": 3, "emotion": "satisfied",
         "prefs": {"bedType": "King", "floor": "Any"}},

        # New/Regular Guests
        {"first": "Jennifer", "last": "Taylor", "email": "jennifer.taylor@email.com", "country": "United States", "city": "Denver",
         "vip": False, "tier": "member", "bookings": 1, "spent": 650, "nights": 2, "emotion": "neutral",
         "prefs": {"bedType": "Queen"}},
        {"first": "Robert", "last": "Anderson", "email": "robert.anderson@email.com", "country": "Canada", "city": "Toronto",
         "vip": False, "tier": "member", "bookings": 1, "spent": 520, "nights": 2, "emotion": "happy",
         "prefs": {"bedType": "King"}},
        {"first": "Lisa", "last": "Wang", "email": "lisa.wang@email.com", "country": "Taiwan", "city": "Taipei",
         "vip": False, "tier": "member", "bookings": 0, "spent": 0, "nights": 0, "emotion": "neutral",
         "prefs": {}},
        {"first": "Ahmed", "last": "Hassan", "email": "ahmed.hassan@email.com", "country": "Egypt", "city": "Cairo",
         "vip": False, "tier": "member", "bookings": 0, "spent": 0, "nights": 0, "emotion": "neutral",
         "prefs": {}},
        {"first": "Priya", "last": "Sharma", "email": "priya.sharma@email.in", "country": "India", "city": "Mumbai",
         "vip": False, "tier": "member", "bookings": 1, "spent": 780, "nights": 3, "emotion": "happy",
         "prefs": {"bedType": "King", "notes": "Vegetarian meals"}},
        {"first": "Oliver", "last": "Schmidt", "email": "oliver.schmidt@email.de", "country": "Germany", "city": "Munich",
         "vip": False, "tier": "bronze", "bookings": 2, "spent": 1650, "nights": 5, "emotion": "satisfied",
         "prefs": {"bedType": "Queen"}},

        # Family bookings
        {"first": "The Thompson", "last": "Family", "email": "thompson.family@email.com", "country": "United States", "city": "Seattle",
         "vip": False, "tier": "silver", "bookings": 4, "spent": 6200, "nights": 16, "emotion": "happy",
         "prefs": {"bedType": "2 Queens", "notes": "Family with 2 children, crib needed"}},
        {"first": "Carlos", "last": "Mendez", "email": "carlos.mendez@email.mx", "country": "Mexico", "city": "Mexico City",
         "vip": False, "tier": "bronze", "bookings": 2, "spent": 1890, "nights": 6, "emotion": "satisfied",
         "prefs": {"bedType": "King", "notes": "Honeymoon trip"}},

        # Corporate accounts
        {"first": "Tech Corp", "last": "Travel Dept", "email": "travel@techcorp.com", "country": "United States", "city": "San Francisco",
         "vip": True, "tier": "gold", "bookings": 25, "spent": 45000, "nights": 80, "emotion": "satisfied",
         "prefs": {"notes": "Corporate account, direct billing"}},
    ]

    guest_ids = {}
    for g in guests:
        tags = []
        if g["vip"]:
            tags.append("vip")
        if g["tier"] == "platinum":
            tags.append("high-value")
        if "Corporate" in g.get("prefs", {}).get("notes", "") or "Corp" in g["first"]:
            tags.append("corporate")
        if "family" in g["first"].lower() or "children" in str(g.get("prefs", {})):
            tags.append("family")
        if g["bookings"] >= 5:
            tags.append("frequent")

        cursor.execute("""
            INSERT INTO guests (first_name, last_name, email, phone, country, city,
                status, emotion, vip_status, loyalty_tier, loyalty_points,
                total_bookings, total_spent, total_nights, preferences, tags,
                id_verified, member_since, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'Active', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """, (
            g["first"], g["last"], g["email"], random_phone(),
            g["country"], g["city"],
            g["emotion"], g["vip"], g["tier"],
            int(g["spent"] * 0.1),  # loyalty points
            g["bookings"], g["spent"], g["nights"],
            json.dumps(g.get("prefs", {})),
            json.dumps(tags),
            (datetime.now() - timedelta(days=random.randint(30, 1000))).isoformat(),
            now, now
        ))
        guest_ids[g["email"]] = cursor.lastrowid
        print(f"    Created guest: {g['first']} {g['last']} ({g['tier']})")

    return guest_ids

def seed_room_types_and_rooms(cursor):
    """Seed room types and rooms"""
    print("\n[4/15] Seeding room types and rooms...")

    now = datetime.utcnow().isoformat()

    room_types = [
        {"name": "Minimalist Studio", "slug": "minimalist-studio", "category": "standard", "price": 180, "max": 2, "bed": "Queen", "sqft": 280},
        {"name": "Coastal Retreat", "slug": "coastal-retreat", "category": "standard", "price": 185, "max": 2, "bed": "Queen", "sqft": 320},
        {"name": "Urban Oasis", "slug": "urban-oasis", "category": "deluxe", "price": 245, "max": 3, "bed": "King", "sqft": 425},
        {"name": "Sunset Vista", "slug": "sunset-vista", "category": "deluxe", "price": 315, "max": 3, "bed": "King", "sqft": 450},
        {"name": "Pacific Suite", "slug": "pacific-suite", "category": "suite", "price": 385, "max": 4, "bed": "King", "sqft": 680},
        {"name": "Wellness Suite", "slug": "wellness-suite", "category": "suite", "price": 425, "max": 2, "bed": "King", "sqft": 520},
        {"name": "Family Sanctuary", "slug": "family-sanctuary", "category": "suite", "price": 485, "max": 6, "bed": "1 King + 2 Twin", "sqft": 780},
        {"name": "Oceanfront Penthouse", "slug": "oceanfront-penthouse", "category": "presidential", "price": 750, "max": 4, "bed": "California King", "sqft": 1100},
    ]

    rt_ids = {}
    for rt in room_types:
        amenities = json.dumps(["Free WiFi", "Air Conditioning", "Smart TV", "Mini Bar", "Room Service", "Safe", "Organic Toiletries"])
        features = json.dumps(["Modern Design", "Natural Light", "Premium Bedding"])
        images = json.dumps([f"https://images.unsplash.com/photo-{random.randint(1500000000000, 1600000000000)}?w=800"])

        cursor.execute("""
            INSERT INTO room_types (name, slug, category, description, short_description, base_price, max_guests,
                bed_type, size_sqft, amenities, features, images, rating, review_count, is_active, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """, (
            rt["name"], rt["slug"], rt["category"],
            f"Experience luxury in our {rt['name']}.",
            f"Luxurious {rt['sqft']} sq ft space",
            rt["price"], rt["max"], rt["bed"], rt["sqft"],
            amenities, features, images,
            round(random.uniform(4.5, 5.0), 1), random.randint(50, 200),
            room_types.index(rt) + 1, now, now
        ))
        rt_ids[rt["name"]] = cursor.lastrowid

    # Create rooms
    rooms = [
        ("101", "Minimalist Studio", 1, "available"), ("102", "Minimalist Studio", 1, "available"), ("103", "Minimalist Studio", 1, "occupied"),
        ("104", "Coastal Retreat", 1, "available"), ("105", "Coastal Retreat", 1, "cleaning"),
        ("201", "Coastal Retreat", 2, "available"), ("202", "Coastal Retreat", 2, "occupied"),
        ("203", "Urban Oasis", 2, "available"), ("204", "Urban Oasis", 2, "available"),
        ("301", "Urban Oasis", 3, "occupied"), ("302", "Urban Oasis", 3, "available"),
        ("303", "Sunset Vista", 3, "available"), ("304", "Sunset Vista", 3, "maintenance"),
        ("401", "Sunset Vista", 4, "occupied"), ("402", "Sunset Vista", 4, "available"),
        ("403", "Pacific Suite", 4, "available"), ("404", "Pacific Suite", 4, "occupied"),
        ("501", "Pacific Suite", 5, "available"), ("502", "Pacific Suite", 5, "occupied"),
        ("503", "Wellness Suite", 5, "available"), ("504", "Wellness Suite", 5, "available"),
        ("601", "Family Sanctuary", 6, "available"), ("602", "Family Sanctuary", 6, "occupied"),
        ("701", "Oceanfront Penthouse", 7, "available"), ("702", "Oceanfront Penthouse", 7, "occupied"),
    ]

    room_ids = {}
    for num, rt_name, floor, status in rooms:
        rt_id = rt_ids[rt_name]
        amenities = json.dumps(["Free WiFi", "Air Conditioning", "Smart TV", "Mini Bar"])
        cursor.execute("""
            INSERT INTO rooms (number, room_type_id, floor, status, bed_type, capacity, max_occupancy,
                amenities, is_smoking, is_accessible, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """, (num, rt_id, floor, status, "King", 2, 3, amenities, num in ["101", "201"], now, now))
        room_ids[num] = cursor.lastrowid
        print(f"    Created room: {num} ({rt_name})")

    return rt_ids, room_ids

def seed_rate_plans(cursor):
    """Seed rate plans"""
    print("\n[5/15] Seeding rate plans...")

    now = datetime.utcnow().isoformat()

    plans = [
        ("BAR", "Best Available Rate", "standard", 1.0),
        ("ADVANCE", "Advance Purchase (15% off)", "advance", 0.85),
        ("MEMBER", "Member Rate (10% off)", "loyalty", 0.90),
        ("WEEKEND", "Weekend Getaway", "package", 0.95),
        ("EXTENDED", "Extended Stay (7+ nights)", "extended", 0.80),
        ("CORPORATE", "Corporate Rate", "corporate", 0.88),
    ]

    plan_ids = {}
    for code, name, ptype, multiplier in plans:
        cursor.execute("""
            INSERT INTO rateplan (code, name, plan_type, base_price, currency, description, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'USD', ?, 1, ?, ?)
        """, (code, name, ptype, multiplier, f"{name} rate plan", now, now))
        plan_ids[code] = cursor.lastrowid
        print(f"    Created rate plan: {name}")

    return plan_ids

def seed_bookings(cursor, guest_ids, rt_ids, room_ids, plan_ids):
    """Seed comprehensive booking data"""
    print("\n[6/15] Seeding bookings...")

    now = datetime.utcnow().isoformat()
    today = date.today()

    bookings_data = [
        # Current in-house guests
        {"guest": "sarah.anderson@email.com", "room": "301", "rt": "Urban Oasis", "days_ago": 2, "nights": 4, "status": "checked_in", "payment": "paid", "source": "direct"},
        {"guest": "h.tanaka@tanaka-corp.jp", "room": "702", "rt": "Oceanfront Penthouse", "days_ago": 1, "nights": 5, "status": "checked_in", "payment": "paid", "source": "direct", "vip": True},
        {"guest": "maria.garcia@email.es", "room": "401", "rt": "Sunset Vista", "days_ago": 1, "nights": 3, "status": "checked_in", "payment": "paid", "source": "direct"},
        {"guest": "thompson.family@email.com", "room": "602", "rt": "Family Sanctuary", "days_ago": 3, "nights": 5, "status": "checked_in", "payment": "paid", "source": "booking.com"},
        {"guest": "michael.brown@email.com", "room": "502", "rt": "Pacific Suite", "days_ago": 1, "nights": 4, "status": "checked_in", "payment": "paid", "source": "direct"},
        {"guest": "v.blackwood@fortune500.com", "room": "701", "rt": "Oceanfront Penthouse", "days_ago": 0, "nights": 7, "status": "checked_in", "payment": "paid", "source": "direct", "vip": True},
        {"guest": "david.chen@email.cn", "room": "103", "rt": "Minimalist Studio", "days_ago": 1, "nights": 2, "status": "checked_in", "payment": "paid", "source": "expedia"},
        {"guest": "jp.dubois@luxurytravel.fr", "room": "404", "rt": "Pacific Suite", "days_ago": 2, "nights": 4, "status": "checked_in", "payment": "paid", "source": "direct", "vip": True},

        # Arriving today
        {"guest": "james.mitchell@email.co.uk", "room": "201", "rt": "Coastal Retreat", "days_ago": 0, "nights": 3, "status": "confirmed", "payment": "pending", "source": "booking.com"},
        {"guest": "emma.wilson@email.au", "room": "503", "rt": "Wellness Suite", "days_ago": 0, "nights": 5, "status": "confirmed", "payment": "paid", "source": "direct"},
        {"guest": "anna.mueller@email.de", "room": "102", "rt": "Minimalist Studio", "days_ago": 0, "nights": 2, "status": "confirmed", "payment": "pending", "source": "expedia"},

        # Future arrivals
        {"guest": "sophie.martin@email.fr", "room": "303", "rt": "Sunset Vista", "days_ago": -3, "nights": 4, "status": "confirmed", "payment": "partial", "source": "direct"},
        {"guest": "isabella.rossi@email.it", "room": "504", "rt": "Wellness Suite", "days_ago": -5, "nights": 6, "status": "confirmed", "payment": "pending", "source": "direct", "vip": True},
        {"guest": "robert.anderson@email.com", "room": "104", "rt": "Coastal Retreat", "days_ago": -7, "nights": 3, "status": "confirmed", "payment": "pending", "source": "booking.com"},
        {"guest": "al.rashid@emirates-holdings.ae", "room": "701", "rt": "Oceanfront Penthouse", "days_ago": -10, "nights": 14, "status": "confirmed", "payment": "paid", "source": "direct", "vip": True},
        {"guest": "priya.sharma@email.in", "room": "203", "rt": "Urban Oasis", "days_ago": -4, "nights": 4, "status": "confirmed", "payment": "partial", "source": "expedia"},
        {"guest": "carlos.mendez@email.mx", "room": "402", "rt": "Sunset Vista", "days_ago": -6, "nights": 5, "status": "confirmed", "payment": "pending", "source": "direct"},
        {"guest": "oliver.schmidt@email.de", "room": "204", "rt": "Urban Oasis", "days_ago": -2, "nights": 3, "status": "confirmed", "payment": "paid", "source": "booking.com"},

        # Past bookings (checked out)
        {"guest": "william.johnson@email.com", "room": "101", "rt": "Minimalist Studio", "days_ago": 5, "nights": 2, "status": "checked_out", "payment": "paid", "source": "expedia"},
        {"guest": "lucas.silva@email.br", "room": "202", "rt": "Coastal Retreat", "days_ago": 7, "nights": 3, "status": "checked_out", "payment": "paid", "source": "booking.com"},
        {"guest": "jennifer.taylor@email.com", "room": "101", "rt": "Minimalist Studio", "days_ago": 10, "nights": 2, "status": "checked_out", "payment": "paid", "source": "direct"},

        # Cancelled
        {"guest": "lisa.wang@email.com", "room": "105", "rt": "Coastal Retreat", "days_ago": -2, "nights": 3, "status": "cancelled", "payment": "refunded", "source": "booking.com"},
    ]

    room_type_prices = {"Minimalist Studio": 180, "Coastal Retreat": 185, "Urban Oasis": 245, "Sunset Vista": 315,
                        "Pacific Suite": 385, "Wellness Suite": 425, "Family Sanctuary": 485, "Oceanfront Penthouse": 750}

    booking_ids = {}
    for i, b in enumerate(bookings_data):
        guest_id = guest_ids.get(b["guest"])
        room_id = room_ids.get(b["room"])
        rt_id = rt_ids.get(b["rt"])

        if not guest_id or not room_id:
            continue

        arrival = today - timedelta(days=b["days_ago"])
        departure = arrival + timedelta(days=b["nights"])

        base_price = room_type_prices.get(b["rt"], 200) * b["nights"]
        taxes = base_price * 0.12
        service_fee = base_price * 0.05
        total = base_price + taxes + service_fee

        booking_num = f"BK-{datetime.now().year}-{str(i+1001).zfill(6)}"
        conf_code = f"GLM-{str(i+1001).zfill(6)}"

        cursor.execute("""
            INSERT INTO bookings (booking_number, confirmation_code, guest_id, room_type_id, room_id,
                arrival_date, departure_date, adults, children, infants, nights, status, payment_status,
                booking_source, base_price, taxes, service_fee, total_price, discount_amount,
                special_requests, vip_flag, is_group_booking, modification_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, 0, 0, ?, ?)
        """, (
            booking_num, conf_code, guest_id, rt_id, room_id,
            arrival.isoformat(), departure.isoformat(),
            random.randint(1, 2), random.randint(0, 1), 0, b["nights"],
            b["status"], b["payment"], b["source"],
            base_price, taxes, service_fee, total,
            "Late check-out requested" if random.random() > 0.7 else None,
            b.get("vip", False), now, now
        ))
        booking_ids[b["guest"]] = cursor.lastrowid
        print(f"    Created booking: {booking_num} ({b['status']})")

    return booking_ids

def seed_housekeeping(cursor, room_ids, staff_ids):
    """Seed housekeeping tasks"""
    print("\n[7/15] Seeding housekeeping tasks...")

    now = datetime.utcnow()
    today = date.today()

    # Get housekeeping staff
    hk_staff = [v for k, v in staff_ids.items() if 'glimmora.local' in k and k.split('@')[0] in ['maria', 'rosa', 'linda', 'carmen', 'anna']]

    tasks = []
    for room_num, room_id in room_ids.items():
        # Each room gets daily cleaning tasks
        for days_ago in range(7):
            task_date = today - timedelta(days=days_ago)
            status = "completed" if days_ago > 0 else random.choice(["pending", "in_progress", "completed"])

            if days_ago == 0 and status == "pending":
                scheduled = datetime.combine(today, time(10, 0))
            else:
                scheduled = datetime.combine(task_date, time(random.randint(8, 14), 0))

            assigned = random.choice(hk_staff) if hk_staff else None

            tasks.append({
                "room_id": room_id,
                "task_type": "cleaning",
                "priority": "high" if room_num in ["701", "702"] else "normal",
                "status": status,
                "assigned_to": assigned,
                "scheduled_for": scheduled.isoformat(),
                "completed_at": (scheduled + timedelta(minutes=random.randint(25, 45))).isoformat() if status == "completed" else None,
                "quality_score": random.randint(4, 5) if status == "completed" else None,
            })

    # Add some special tasks
    special_tasks = [
        {"room_id": room_ids["701"], "task_type": "deep_clean", "priority": "high", "status": "pending"},
        {"room_id": room_ids["602"], "task_type": "turndown", "priority": "normal", "status": "completed"},
        {"room_id": room_ids["304"], "task_type": "inspection", "priority": "high", "status": "in_progress"},
    ]
    tasks.extend(special_tasks)

    for t in tasks[:50]:  # Limit to 50 tasks for manageable data
        cursor.execute("""
            INSERT INTO housekeeping_tasks (room_id, task_type, priority, status, assigned_to,
                scheduled_for, completed_at, quality_score, force_assigned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
        """, (
            t["room_id"], t["task_type"], t["priority"], t["status"], t.get("assigned_to"),
            t.get("scheduled_for"), t.get("completed_at"), t.get("quality_score"),
            now.isoformat(), now.isoformat()
        ))

    print(f"    Created {min(len(tasks), 50)} housekeeping tasks")

def seed_maintenance(cursor, room_ids, staff_ids):
    """Seed maintenance requests"""
    print("\n[8/15] Seeding maintenance requests...")

    now = datetime.utcnow()

    # Get maintenance staff
    mt_staff = [v for k, v in staff_ids.items() if 'glimmora.local' in k and k.split('@')[0] in ['john', 'carlos', 'mike']]

    requests = [
        {"room": "304", "category": "hvac", "issue": "AC not cooling properly", "priority": "high", "status": "in_progress"},
        {"room": "202", "category": "plumbing", "issue": "Slow drain in bathroom sink", "priority": "medium", "status": "completed"},
        {"room": "105", "category": "electrical", "issue": "Flickering lights in bathroom", "priority": "medium", "status": "open"},
        {"room": "401", "category": "appliance", "issue": "Mini fridge making noise", "priority": "low", "status": "assigned"},
        {"room": "501", "category": "general", "issue": "Door lock difficult to open", "priority": "high", "status": "completed"},
        {"room": "601", "category": "plumbing", "issue": "Low water pressure in shower", "priority": "medium", "status": "in_progress"},
        {"room": "103", "category": "electrical", "issue": "TV remote not working", "priority": "low", "status": "completed"},
        {"room": "203", "category": "hvac", "issue": "Thermostat not responding", "priority": "high", "status": "open"},
        {"room": "303", "category": "carpentry", "issue": "Closet door off track", "priority": "low", "status": "assigned"},
        {"room": "702", "category": "appliance", "issue": "Coffee maker not heating", "priority": "medium", "status": "completed"},
        {"location": "Lobby", "category": "electrical", "issue": "Chandelier bulb replacement", "priority": "low", "status": "completed"},
        {"location": "Pool Area", "category": "general", "issue": "Pool chair repair needed", "priority": "low", "status": "open"},
        {"location": "Parking Garage", "category": "electrical", "issue": "Light fixture out on Level 2", "priority": "medium", "status": "assigned"},
        {"location": "Restaurant", "category": "plumbing", "issue": "Kitchen sink leak", "priority": "high", "status": "in_progress"},
        {"location": "Gym", "category": "appliance", "issue": "Treadmill #3 error code", "priority": "medium", "status": "open"},
    ]

    for i, r in enumerate(requests):
        work_order = f"WO-{datetime.now().year}-{str(i+1).zfill(6)}"
        room_id = room_ids.get(r.get("room")) if r.get("room") else None
        assigned = random.choice(mt_staff) if mt_staff and r["status"] in ["assigned", "in_progress", "completed"] else None

        completed_at = None
        if r["status"] == "completed":
            completed_at = (now - timedelta(hours=random.randint(1, 72))).isoformat()

        cursor.execute("""
            INSERT INTO maintenancerequest (work_order_id, room_id, room_number, location, title, category,
                priority, issue, status, assigned_to, reported_at, completed_at,
                is_out_of_order, requires_parts, parts_ordered, is_preventive, force_assigned,
                created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, ?, ?)
        """, (
            work_order, room_id, r.get("room"), r.get("location", f"Room {r.get('room')}"),
            r["issue"][:50], r["category"], r["priority"], r["issue"],
            r["status"], assigned, now.isoformat(), completed_at, now.isoformat(), now.isoformat()
        ))
        print(f"    Created maintenance: {work_order} ({r['status']})")

def seed_reviews(cursor, guest_ids, room_ids):
    """Seed reviews and ratings"""
    print("\n[9/15] Seeding reviews...")

    now = datetime.utcnow()

    reviews = [
        {"guest": "v.blackwood@fortune500.com", "rating": 5.0, "title": "Exceptional Experience",
         "comment": "The penthouse exceeded all expectations. Staff anticipated every need. Will definitely return.",
         "sentiment": "positive", "source": "direct"},
        {"guest": "h.tanaka@tanaka-corp.jp", "rating": 5.0, "title": "Perfect Business Stay",
         "comment": "Impeccable service, quiet rooms, excellent amenities. The attention to detail is remarkable.",
         "sentiment": "positive", "source": "google"},
        {"guest": "sarah.anderson@email.com", "rating": 4.5, "title": "Wonderful Getaway",
         "comment": "Beautiful rooms, great location, friendly staff. Only minor issue was slow room service one evening.",
         "sentiment": "positive", "source": "tripadvisor"},
        {"guest": "james.mitchell@email.co.uk", "rating": 4.0, "title": "Good Business Hotel",
         "comment": "Clean rooms, professional staff. WiFi could be faster. Good value for the area.",
         "sentiment": "positive", "source": "booking_com"},
        {"guest": "maria.garcia@email.es", "rating": 5.0, "title": "Anniversary Perfection",
         "comment": "They made our anniversary so special! Rose petals, champagne, amazing dinner recommendation.",
         "sentiment": "positive", "source": "direct"},
        {"guest": "emma.wilson@email.au", "rating": 4.5, "title": "Wellness Paradise",
         "comment": "The wellness suite is incredible. Loved the yoga mat and meditation space. Healthy breakfast options too!",
         "sentiment": "positive", "source": "expedia"},
        {"guest": "michael.brown@email.com", "rating": 4.0, "title": "Solid Choice",
         "comment": "Comfortable bed, quiet room, good breakfast. Check-in was a bit slow but otherwise great.",
         "sentiment": "positive", "source": "google"},
        {"guest": "thompson.family@email.com", "rating": 4.5, "title": "Family Friendly",
         "comment": "Kids loved the pool! Family suite was spacious. Staff were very accommodating with our children.",
         "sentiment": "positive", "source": "tripadvisor"},
        {"guest": "william.johnson@email.com", "rating": 3.5, "title": "Decent Stay",
         "comment": "Room was clean but smaller than expected. Nice location though. Fair price.",
         "sentiment": "neutral", "source": "booking_com"},
        {"guest": "david.chen@email.cn", "rating": 4.0, "title": "Good Value",
         "comment": "Nice hotel, friendly staff. Room was a bit warm but maintenance fixed it quickly.",
         "sentiment": "positive", "source": "expedia"},
        {"guest": "jp.dubois@luxurytravel.fr", "rating": 5.0, "title": "Magnifique!",
         "comment": "The wine selection is excellent. Sommelier gave wonderful recommendations. Suite was gorgeous.",
         "sentiment": "positive", "source": "google"},
        {"guest": "isabella.rossi@email.it", "rating": 4.5, "title": "Art Lover's Dream",
         "comment": "Beautiful decor, great local art. Concierge arranged an amazing private gallery tour.",
         "sentiment": "positive", "source": "tripadvisor"},
    ]

    for r in reviews:
        guest_id = guest_ids.get(r["guest"])
        if not guest_id:
            continue

        review_date = now - timedelta(days=random.randint(1, 90))

        cursor.execute("""
            INSERT INTO reviews (guest_id, source, overall_rating, cleanliness_rating, service_rating,
                location_rating, value_rating, amenities_rating, title, comment, sentiment,
                is_verified, is_public, is_featured, helpful_count, review_date, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, ?, ?, ?, ?, ?)
        """, (
            guest_id, r["source"], r["rating"],
            round(r["rating"] + random.uniform(-0.3, 0.3), 1),  # cleanliness
            round(r["rating"] + random.uniform(-0.2, 0.2), 1),  # service
            round(random.uniform(4.3, 5.0), 1),  # location
            round(r["rating"] + random.uniform(-0.3, 0.2), 1),  # value
            round(r["rating"] + random.uniform(-0.2, 0.3), 1),  # amenities
            r["title"], r["comment"], r["sentiment"],
            1 if r["rating"] >= 4.5 else 0,  # is_featured for high ratings
            random.randint(0, 25),
            review_date.isoformat(), now.isoformat(), now.isoformat()
        ))
        print(f"    Created review: {r['title']} ({r['rating']})")

def seed_runner_tasks(cursor, room_ids, guest_ids, staff_ids):
    """Seed runner/bell staff tasks"""
    print("\n[10/15] Seeding runner tasks...")

    now = datetime.utcnow()

    # Get runner staff
    runner_staff = [v for k, v in staff_ids.items() if 'glimmora.local' in k and k.split('@')[0] in ['alex', 'james', 'kevin', 'ryan']]

    # Delivery tasks
    deliveries = [
        {"room": "702", "guest": "h.tanaka@tanaka-corp.jp", "type": "room_service", "items": "Japanese Breakfast Set, Green Tea", "status": "delivered", "priority": "high"},
        {"room": "301", "guest": "sarah.anderson@email.com", "type": "room_service", "items": "Caesar Salad, Sparkling Water", "status": "in_transit", "priority": "normal"},
        {"room": "602", "guest": "thompson.family@email.com", "type": "amenity", "items": "Extra towels, Kids toiletries", "status": "delivered", "priority": "normal"},
        {"room": "401", "guest": "maria.garcia@email.es", "type": "room_service", "items": "Anniversary Cake, Champagne", "status": "delivered", "priority": "high"},
        {"room": "502", "guest": "michael.brown@email.com", "type": "room_service", "items": "Club Sandwich, Coffee", "status": "pending", "priority": "normal"},
        {"room": "701", "guest": "v.blackwood@fortune500.com", "type": "package", "items": "Fedex Package", "status": "delivered", "priority": "urgent"},
        {"room": "404", "guest": "jp.dubois@luxurytravel.fr", "type": "room_service", "items": "Wine Service - Chateau Margaux 2015", "status": "delivered", "priority": "high"},
        {"room": "103", "guest": "david.chen@email.cn", "type": "laundry", "items": "Express Laundry - 3 items", "status": "in_transit", "priority": "normal"},
    ]

    for i, d in enumerate(deliveries):
        delivery_num = f"DL-{datetime.now().year}-{str(i+1).zfill(6)}"
        room_id = room_ids.get(d["room"])
        guest_id = guest_ids.get(d["guest"])
        assigned = random.choice(runner_staff) if runner_staff else None

        cursor.execute("""
            INSERT INTO runner_deliveries (delivery_number, delivery_type, room_id, room_number, guest_id, guest_name,
                items_description, item_count, origin_location, destination_location, priority, status,
                assigned_to, signature_required, temperature_sensitive, fragile, delivery_confirmation,
                ordered_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            delivery_num, d["type"], room_id, d["room"], guest_id, d["guest"].split('@')[0].replace('.', ' ').title(),
            d["items"], random.randint(1, 3), "Kitchen" if d["type"] == "room_service" else "Front Desk",
            f"Room {d['room']}", d["priority"], d["status"],
            assigned if d["status"] != "pending" else None,
            1 if d["type"] == "package" else 0,  # signature_required for packages
            1 if d["type"] == "room_service" else 0,  # temperature_sensitive for room service
            0,  # fragile
            "none",  # delivery_confirmation
            now.isoformat(), now.isoformat(), now.isoformat()
        ))
        print(f"    Created delivery: {delivery_num}")

    # Pickup tasks
    pickups = [
        {"room": "702", "guest": "h.tanaka@tanaka-corp.jp", "type": "luggage", "items": "4 suitcases for storage", "status": "completed"},
        {"room": "602", "guest": "thompson.family@email.com", "type": "laundry", "items": "Laundry bag pickup", "status": "in_progress"},
        {"room": "301", "guest": "sarah.anderson@email.com", "type": "luggage", "items": "2 bags to lobby for checkout", "status": "pending"},
    ]

    for i, p in enumerate(pickups):
        pickup_num = f"PU-{datetime.now().year}-{str(i+1).zfill(6)}"
        room_id = room_ids.get(p["room"])
        guest_id = guest_ids.get(p["guest"])

        cursor.execute("""
            INSERT INTO runner_pickup_requests (request_number, room_id, room_number, guest_id, guest_name,
                pickup_type, items_description, item_count, pickup_location, destination, priority, status,
                signature_required, requested_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'normal', ?, 0, ?, ?, ?)
        """, (
            pickup_num, room_id, p["room"], guest_id, p["guest"].split('@')[0].replace('.', ' ').title(),
            p["type"], p["items"], random.randint(1, 4), f"Room {p['room']}", "Lobby" if p["type"] == "luggage" else "Laundry",
            p["status"], now.isoformat(), now.isoformat(), now.isoformat()
        ))
        print(f"    Created pickup: {pickup_num}")

def seed_crm_data(cursor, guest_ids, staff_ids):
    """Seed CRM activities and feedback"""
    print("\n[11/15] Seeding CRM data...")

    now = datetime.utcnow()

    # Guest activities
    activities = [
        {"guest": "v.blackwood@fortune500.com", "type": "check_in", "desc": "VIP check-in with welcome amenities", "sentiment": "positive"},
        {"guest": "v.blackwood@fortune500.com", "type": "upgrade", "desc": "Complimentary upgrade to Penthouse", "sentiment": "positive"},
        {"guest": "h.tanaka@tanaka-corp.jp", "type": "booking", "desc": "Direct booking via phone - returning guest", "sentiment": "positive"},
        {"guest": "sarah.anderson@email.com", "type": "inquiry", "desc": "Asked about spa services", "sentiment": "neutral"},
        {"guest": "thompson.family@email.com", "type": "check_in", "desc": "Family check-in, requested crib", "sentiment": "neutral"},
        {"guest": "maria.garcia@email.es", "type": "milestone", "desc": "Anniversary celebration - complimentary cake arranged", "sentiment": "positive"},
        {"guest": "james.mitchell@email.co.uk", "type": "complaint", "desc": "Reported slow WiFi in room", "sentiment": "negative"},
        {"guest": "jp.dubois@luxurytravel.fr", "type": "visit", "desc": "Wine tasting arranged with sommelier", "sentiment": "positive"},
    ]

    for a in activities:
        guest_id = guest_ids.get(a["guest"])
        if not guest_id:
            continue

        cursor.execute("""
            INSERT INTO crm_guest_activities (guest_id, activity_type, activity_category, description,
                sentiment, importance, timestamp, created_at)
            VALUES (?, ?, 'service', ?, ?, 'medium', ?, ?)
        """, (guest_id, a["type"], a["desc"], a["sentiment"], now.isoformat(), now.isoformat()))

    print(f"    Created {len(activities)} CRM activities")

    # Guest feedback
    feedbacks = [
        {"guest": "james.mitchell@email.co.uk", "type": "complaint", "category": "amenities", "subject": "WiFi Speed",
         "desc": "WiFi connection very slow in room 201. Had trouble with video calls.", "status": "resolved", "urgency": "medium"},
        {"guest": "sarah.anderson@email.com", "type": "compliment", "category": "staff", "subject": "Excellent Service",
         "desc": "Front desk staff Emily was incredibly helpful with restaurant recommendations.", "status": "closed", "urgency": "low"},
        {"guest": "thompson.family@email.com", "type": "suggestion", "category": "amenities", "subject": "Kids Menu",
         "desc": "Would love to see more healthy options on the kids menu.", "status": "open", "urgency": "low"},
        {"guest": "maria.garcia@email.es", "type": "compliment", "category": "service", "subject": "Anniversary Surprise",
         "desc": "Thank you for the beautiful anniversary setup! It made our celebration perfect.", "status": "closed", "urgency": "low"},
        {"guest": "david.chen@email.cn", "type": "concern", "category": "room", "subject": "Room Temperature",
         "desc": "Room was quite warm on arrival. Maintenance fixed it but took about an hour.", "status": "resolved", "urgency": "medium"},
    ]

    for i, f in enumerate(feedbacks):
        guest_id = guest_ids.get(f["guest"])
        if not guest_id:
            continue

        feedback_num = f"FB-{datetime.now().year}-{str(i+1).zfill(6)}"

        cursor.execute("""
            INSERT INTO guest_feedback (feedback_number, guest_id, feedback_type, category, subject,
                description, urgency, status, follow_up_required, is_public, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (feedback_num, guest_id, f["type"], f["category"], f["subject"],
              f["desc"], f["urgency"], f["status"],
              1 if f["status"] == "open" else 0,  # follow_up_required for open tickets
              1 if f["type"] == "compliment" else 0,  # is_public for compliments
              now.isoformat(), now.isoformat()))

    print(f"    Created {len(feedbacks)} guest feedbacks")

def seed_loyalty(cursor, guest_ids):
    """Seed loyalty tiers and transactions"""
    print("\n[12/15] Seeding loyalty program...")

    now = datetime.utcnow()

    # Loyalty tiers
    tiers = [
        {"name": "member", "min": 0, "max": 999, "discount": 0, "color": "#9CA3AF", "benefits": ["Member rates", "Free WiFi"]},
        {"name": "bronze", "min": 1000, "max": 4999, "discount": 5, "color": "#CD7F32", "benefits": ["5% discount", "Late checkout", "Welcome drink"]},
        {"name": "silver", "min": 5000, "max": 14999, "discount": 10, "color": "#C0C0C0", "benefits": ["10% discount", "Room upgrade (subject to availability)", "Breakfast included"]},
        {"name": "gold", "min": 15000, "max": 49999, "discount": 15, "color": "#FFD700", "benefits": ["15% discount", "Guaranteed upgrade", "Spa credit", "Airport transfer"]},
        {"name": "platinum", "min": 50000, "max": None, "discount": 20, "color": "#E5E4E2", "benefits": ["20% discount", "Suite upgrade", "Personal concierge", "Exclusive events"]},
    ]

    for i, t in enumerate(tiers):
        cursor.execute("""
            INSERT INTO loyalty_tiers (name, min_points, max_points, discount_percentage, color, benefits, sort_order, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
        """, (t["name"], t["min"], t["max"], t["discount"], t["color"], json.dumps(t["benefits"]), i+1, now.isoformat(), now.isoformat()))

    print(f"    Created {len(tiers)} loyalty tiers")

    # Sample transactions for top guests
    transactions = [
        {"guest": "v.blackwood@fortune500.com", "type": "earned", "points": 15600, "reason": "Stay points"},
        {"guest": "v.blackwood@fortune500.com", "type": "redeemed", "points": -5000, "reason": "Spa treatment redemption"},
        {"guest": "h.tanaka@tanaka-corp.jp", "type": "earned", "points": 14200, "reason": "Stay points"},
        {"guest": "h.tanaka@tanaka-corp.jp", "type": "earned", "points": 2000, "reason": "Referral bonus"},
        {"guest": "sarah.anderson@email.com", "type": "earned", "points": 3250, "reason": "Stay points"},
        {"guest": "jp.dubois@luxurytravel.fr", "type": "earned", "points": 2800, "reason": "Stay points"},
    ]

    for t in transactions:
        guest_id = guest_ids.get(t["guest"])
        if not guest_id:
            continue

        # Get current points
        cursor.execute("SELECT loyalty_points FROM guests WHERE id = ?", (guest_id,))
        current = cursor.fetchone()[0] or 0
        balance = current + t["points"]

        cursor.execute("""
            INSERT INTO loyalty_transactions (guest_id, transaction_type, points, balance_after, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (guest_id, t["type"], abs(t["points"]), balance, t["reason"], now.isoformat()))

    print(f"    Created {len(transactions)} loyalty transactions")

def seed_vendors(cursor):
    """Seed vendor data"""
    print("\n[13/15] Seeding vendors...")

    now = datetime.utcnow().isoformat()

    vendors = [
        {"code": "VND-001", "name": "Pacific HVAC Solutions", "category": "services", "specialty": "hvac", "rating": 4.8},
        {"code": "VND-002", "name": "Coastal Plumbing Co.", "category": "services", "specialty": "plumbing", "rating": 4.5},
        {"code": "VND-003", "name": "Elite Electric", "category": "services", "specialty": "electrical", "rating": 4.7},
        {"code": "VND-004", "name": "Premium Linens Supply", "category": "supplies", "specialty": "linens", "rating": 4.9},
        {"code": "VND-005", "name": "CleanPro Chemicals", "category": "supplies", "specialty": "cleaning", "rating": 4.3},
        {"code": "VND-006", "name": "TechFix Appliances", "category": "services", "specialty": "appliances", "rating": 4.6},
        {"code": "VND-007", "name": "Local Produce Farm", "category": "supplies", "specialty": "food", "rating": 4.8},
        {"code": "VND-008", "name": "Wine Imports Inc.", "category": "supplies", "specialty": "beverages", "rating": 4.9},
    ]

    for v in vendors:
        total_orders = random.randint(10, 100)
        cursor.execute("""
            INSERT INTO vendors (vendor_code, name, category, specialty, contact_name, email, phone,
                rating, total_orders, total_spent, is_active, is_preferred, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
        """, (
            v["code"], v["name"], v["category"], v["specialty"],
            f"Contact at {v['name']}", f"contact@{v['name'].lower().replace(' ', '')}.com",
            random_phone(), v["rating"], total_orders, total_orders * random.uniform(500, 2000),
            v["rating"] >= 4.7, now, now
        ))
        print(f"    Created vendor: {v['name']}")

def seed_revenue_data(cursor):
    """Seed revenue and channel performance data"""
    print("\n[14/15] Seeding revenue data...")

    now = datetime.utcnow()
    today = date.today()

    channels = ["direct", "booking.com", "expedia", "tripadvisor", "google"]

    # Channel performance for last 30 days
    for days_ago in range(30):
        perf_date = today - timedelta(days=days_ago)

        for channel in channels:
            base_bookings = random.randint(2, 8) if channel == "direct" else random.randint(1, 5)
            revenue = base_bookings * random.randint(200, 500)
            commission_rate = 0 if channel == "direct" else random.uniform(0.12, 0.18)

            cursor.execute("""
                INSERT INTO channel_performance (date, channel, bookings_count, cancellations_count,
                    revenue, commission_rate, commission_amount, net_revenue, avg_booking_value, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                perf_date.isoformat(), channel, base_bookings, random.randint(0, 1),
                revenue, commission_rate,
                revenue * commission_rate, revenue * (1 - commission_rate),
                revenue / base_bookings, now.isoformat()
            ))

    print(f"    Created {30 * len(channels)} channel performance records")

    # Forecast data
    for days_ahead in range(14):
        forecast_date = today + timedelta(days=days_ahead)

        cursor.execute("""
            INSERT INTO forecast_data (forecast_date, forecast_type, forecasted_value, confidence_level, created_at)
            VALUES (?, 'occupancy', ?, ?, ?)
        """, (forecast_date.isoformat(), random.uniform(65, 95), random.uniform(0.75, 0.95), now.isoformat()))

        cursor.execute("""
            INSERT INTO forecast_data (forecast_date, forecast_type, forecasted_value, confidence_level, created_at)
            VALUES (?, 'revenue', ?, ?, ?)
        """, (forecast_date.isoformat(), random.uniform(15000, 35000), random.uniform(0.70, 0.90), now.isoformat()))

    print(f"    Created 28 forecast records")

def seed_additional_data(cursor, staff_ids):
    """Seed additional operational data"""
    print("\n[15/15] Seeding additional operational data...")

    now = datetime.utcnow()
    today = date.today()

    # Staff schedules for next 7 days
    staff_list = list(staff_ids.values())
    shifts = ["morning", "afternoon", "evening", "night"]
    shift_times = {
        "morning": ("06:00", "14:00"),
        "afternoon": ("14:00", "22:00"),
        "evening": ("16:00", "00:00"),
        "night": ("22:00", "06:00"),
    }

    schedule_count = 0
    for staff_id in staff_list[:15]:  # Limit to first 15 staff
        for days_ahead in range(7):
            sched_date = today + timedelta(days=days_ahead)
            if random.random() > 0.2:  # 80% chance of being scheduled
                shift = random.choice(shifts)
                start, end = shift_times[shift]

                cursor.execute("""
                    INSERT INTO staff_schedules (staff_id, schedule_date, shift_type, start_time, end_time, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?)
                """, (staff_id, sched_date.isoformat(), shift, start, end, now.isoformat(), now.isoformat()))
                schedule_count += 1

    print(f"    Created {schedule_count} staff schedules")

    # Night audit records
    for days_ago in range(7):
        audit_date = today - timedelta(days=days_ago + 1)

        cursor.execute("""
            INSERT INTO nightaudit (audit_date, run_at, status, occupancy_rate, revenue,
                arrivals, departures, in_house, no_shows, walk_ins, completed_at)
            VALUES (?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            audit_date.isoformat(),
            datetime.combine(audit_date, time(23, 30)).isoformat(),
            random.uniform(70, 95),
            random.uniform(18000, 32000),
            random.randint(3, 8),
            random.randint(2, 6),
            random.randint(15, 22),
            random.randint(0, 2),
            random.randint(0, 3),  # walk_ins
            datetime.combine(audit_date + timedelta(days=1), time(0, 15)).isoformat()
        ))

    print(f"    Created 7 night audit records")

    # Lost and found
    lost_items = [
        ("Sunglasses - Ray-Ban", "Pool Area", "stored"),
        ("iPhone charger - white", "Room 301", "claimed"),
        ("Gold earring", "Restaurant", "stored"),
        ("Kindle e-reader", "Room 502", "stored"),
        ("Blue jacket - Nike", "Gym", "stored"),
    ]

    for item, location, status in lost_items:
        cursor.execute("""
            INSERT INTO lostfound (item_description, location_found, found_date, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (item, location, (today - timedelta(days=random.randint(1, 14))).isoformat(), status, now.isoformat(), now.isoformat()))

    print(f"    Created {len(lost_items)} lost and found items")

def main():
    print("=" * 70)
    print("   GLIMMORA COMPREHENSIVE DATABASE SEED")
    print("   Creating presentable demo data for client presentation")
    print("=" * 70)

    if not os.path.exists(DB_PATH):
        print(f"\nERROR: Database not found at {DB_PATH}")
        print("Please run the backend first to create the database.")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        print("\n[CLEARING] Removing existing data...")
        clear_all_tables(cursor)

        # Seed in order of dependencies
        user_ids = seed_users(cursor)
        staff_ids = seed_staff(cursor, user_ids)
        guest_ids = seed_guests(cursor)
        rt_ids, room_ids = seed_room_types_and_rooms(cursor)
        plan_ids = seed_rate_plans(cursor)
        booking_ids = seed_bookings(cursor, guest_ids, rt_ids, room_ids, plan_ids)
        seed_housekeeping(cursor, room_ids, staff_ids)
        seed_maintenance(cursor, room_ids, staff_ids)
        seed_reviews(cursor, guest_ids, room_ids)
        seed_runner_tasks(cursor, room_ids, guest_ids, staff_ids)
        seed_crm_data(cursor, guest_ids, staff_ids)
        seed_loyalty(cursor, guest_ids)
        seed_vendors(cursor)
        seed_revenue_data(cursor)
        seed_additional_data(cursor, staff_ids)

        conn.commit()

        print("\n" + "=" * 70)
        print("   DATABASE SEEDING COMPLETED SUCCESSFULLY!")
        print("=" * 70)
        print("\n LOGIN CREDENTIALS:")
        print("-" * 50)
        print("  ADMIN/MANAGEMENT:")
        print("    admin@glimmora.com / admin123")
        print("    gm@glimmora.com / password123")
        print("    manager@glimmora.com / password123")
        print("\n  FRONT DESK:")
        print("    frontdesk@glimmora.com / password123")
        print("    reception1@glimmora.com / password123")
        print("    nightaudit@glimmora.com / password123")
        print("\n  HOUSEKEEPING:")
        print("    maria@glimmora.local / 123456")
        print("    rosa@glimmora.local / 123456")
        print("    linda@glimmora.local / 123456")
        print("    housekeeping.sup@glimmora.com / password123")
        print("\n  MAINTENANCE:")
        print("    john@glimmora.local / 123456")
        print("    carlos@glimmora.local / 123456")
        print("    maintenance.sup@glimmora.com / password123")
        print("\n  RUNNERS:")
        print("    alex@glimmora.local / 123456")
        print("    james@glimmora.local / 123456")
        print("    kevin@glimmora.local / 123456")
        print("\n  FINANCE:")
        print("    finance@glimmora.com / password123")
        print("-" * 50)
        print("\n  DATA CREATED:")
        print(f"    - {len(user_ids)} users")
        print(f"    - {len(staff_ids)} staff records")
        print(f"    - {len(guest_ids)} guests (including VIPs)")
        print(f"    - {len(room_ids)} rooms across 8 room types")
        print(f"    - {len(booking_ids)} bookings")
        print("    - Housekeeping tasks, maintenance requests")
        print("    - Reviews, feedback, CRM activities")
        print("    - Runner deliveries and pickups")
        print("    - Loyalty program and transactions")
        print("    - Vendors, revenue data, forecasts")
        print("    - Staff schedules, night audits, lost & found")
        print("=" * 70)

    except Exception as e:
        print(f"\nERROR during seeding: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
