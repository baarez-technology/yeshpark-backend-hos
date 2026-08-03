"""
Seed database with dummy data
"""
import asyncio
import json
import random
from datetime import date, datetime, timedelta
from sqlmodel import select
from app.db.session import async_session_maker, init_db
from app.core.security import get_password_hash
from app.models.user import User
from app.models.inventory import Room, RatePlan
from app.models.reservations import Guest, Reservation
from app.models.precheckin import PreCheckIn
from app.models.payment_method import PaymentMethod


async def seed_dummy_data():
    """Seed database with comprehensive dummy data"""
    print("=" * 60)
    print("SEEDING DATABASE WITH DUMMY DATA")
    print("=" * 60)
    
    # Initialize database (create all tables)
    print("\n[0/6] Initializing database...")
    await init_db()
    print("  ✓ Database initialized")
    
    async with async_session_maker() as session:
        # ========== USERS ==========
        print("\n[1/6] Creating users...")
        users_data = [
            {
                "email": "admin@glimmora.local",
                "full_name": "System Administrator",
                "password": "admin123",
                "role": "admin",
                "phone": "+1 (555) 100-0001",
                "is_superuser": True,
                "address": "123 Hotel Street",
                "city": "Santa Monica",
                "zip_code": "90401",
                "country": "United States",
            },
            {
                "email": "frontdesk@glimmora.local",
                "full_name": "Front Desk Manager",
                "password": "frontdesk123",
                "role": "front_desk",
                "phone": "+1 (555) 100-0002",
                "is_superuser": False,
            },
            {
                "email": "finance@glimmora.local",
                "full_name": "Finance Manager",
                "password": "finance123",
                "role": "finance",
                "phone": "+1 (555) 100-0003",
                "is_superuser": False,
            },
            {
                "email": "manager@glimmora.local",
                "full_name": "Hotel Manager",
                "password": "manager123",
                "role": "manager",
                "phone": "+1 (555) 100-0004",
                "is_superuser": False,
            },
            {
                "email": "ishanagrawal1201@gmail.com",
                "full_name": "Ishan Agrawal",
                "password": "Ishan@1201",
                "role": "staff",
                "phone": "+1 (555) 123-4567",
                "address": "1250 Ocean Boulevard",
                "city": "Santa Monica",
                "zip_code": "90401",
                "country": "United States",
                "preferences": json.dumps({
                    "floor": "high",
                    "view": "ocean",
                    "bedType": "king",
                    "quietness": "quiet",
                    "temperature": 72,
                    "pillowType": ["firm"],
                    "minibar": ["water", "soft-drinks"],
                    "dietary": ["vegetarian"]
                })
            },
        ]
        
        created_users = []
        for user_data in users_data:
            existing = (await session.exec(select(User).where(User.email == user_data["email"]))).first()
            if not existing:
                user = User(
                    email=user_data["email"],
                    full_name=user_data["full_name"],
                    hashed_password=get_password_hash(user_data["password"]),
                    role=user_data["role"],
                    is_superuser=user_data.get("is_superuser", False),
                    phone=user_data.get("phone"),
                    address=user_data.get("address"),
                    city=user_data.get("city"),
                    zip_code=user_data.get("zip_code"),
                    country=user_data.get("country"),
                    preferences=user_data.get("preferences"),
                )
                session.add(user)
                created_users.append(user)
                print(f"  ✓ Created user: {user.email} ({user.role})")
            else:
                print(f"  - User already exists: {user_data['email']}")
                created_users.append(existing)
        
        await session.commit()
        print(f"  Total users: {len(created_users)}")
        
        # ========== ROOMS ==========
        print("\n[2/6] Creating rooms...")
        room_types = ["king", "queen", "suite", "deluxe"]
        floors = [1, 2, 3, 4, 5]
        views = ["ocean", "city", "garden", "pool"]
        
        created_rooms = []
        for floor in floors:
            for room_num in range(1, 21):  # 20 rooms per floor
                room_number = f"{floor}{room_num:02d}"
                existing = (await session.exec(select(Room).where(Room.number == room_number))).first()
                if not existing:
                    room = Room(
                        number=room_number,
                        room_type=random.choice(room_types),
                        floor=floor,
                        status="clean",
                        capacity=random.choice([2, 3, 4]),
                        max_occupancy=random.choice([2, 3, 4]),
                        bed_type=random.choice(["king", "queen", "twin"]),
                        view_type=random.choice(views),
                        description=f"Comfortable {random.choice(room_types)} room with {random.choice(views)} view",
                        size_sqft=random.choice([300, 400, 500, 600]),
                    )
                    session.add(room)
                    created_rooms.append(room)
        
        await session.commit()
        print(f"  ✓ Created {len(created_rooms)} rooms")
        
        # ========== RATE PLANS ==========
        print("\n[3/6] Creating rate plans...")
        rate_plans_data = [
            {"code": "BAR", "name": "Best Available Rate", "base_price": 12500.0},
            {"code": "CORP", "name": "Corporate Rate", "base_price": 10700.0},
            {"code": "GRP", "name": "Group Rate", "base_price": 9900.0},
            {"code": "PKG", "name": "Package Rate", "base_price": 11500.0},
        ]
        
        for rp_data in rate_plans_data:
            existing = (await session.exec(select(RatePlan).where(RatePlan.code == rp_data["code"]))).first()
            if not existing:
                rp = RatePlan(**rp_data, currency="INR", is_active=True)
                session.add(rp)
                print(f"  ✓ Created rate plan: {rp_data['code']}")
        
        await session.commit()
        
        # ========== GUESTS ==========
        print("\n[4/6] Creating guests...")
        guest_names = [
            ("John", "Doe"), ("Jane", "Smith"), ("Michael", "Johnson"),
            ("Sarah", "Williams"), ("David", "Brown"), ("Emily", "Davis"),
            ("Robert", "Miller"), ("Lisa", "Wilson"), ("James", "Moore"),
            ("Maria", "Taylor"),
        ]
        
        created_guests = []
        for first, last in guest_names:
            email = f"{first.lower()}.{last.lower()}@example.com"
            existing = (await session.exec(select(Guest).where(Guest.email == email))).first()
            if not existing:
                guest = Guest(
                    first_name=first,
                    last_name=last,
                    email=email,
                    phone=f"+1 (555) {random.randint(200, 999)}-{random.randint(1000, 9999)}",
                )
                session.add(guest)
                created_guests.append(guest)
        
        await session.commit()
        print(f"  ✓ Created {len(created_guests)} guests")
        
        # ========== RESERVATIONS ==========
        print("\n[5/6] Creating reservations...")
        today = date.today()
        bar_rate = (await session.exec(select(RatePlan).where(RatePlan.code == "BAR"))).first()
        
        if bar_rate and created_rooms and created_guests:
            for i in range(min(10, len(created_guests))):
                guest = created_guests[i]
                room = random.choice(created_rooms)
                arrival = today + timedelta(days=random.randint(1, 30))
                departure = arrival + timedelta(days=random.randint(1, 7))
                
                reservation = Reservation(
                    confirmation_code=f"GLM{random.randint(100000, 999999)}",
                    guest_id=guest.id,
                    room_id=room.id,
                    rate_plan_id=bar_rate.id,
                    arrival_date=arrival,
                    departure_date=departure,
                    adults=random.randint(1, 2),
                    children=random.randint(0, 2),
                    status=random.choice(["booked", "checked_in", "checked_out"]),
                    total_amount=random.uniform(16500, 83000),
                    currency="INR",
                )
                session.add(reservation)
        
        await session.commit()
        print(f"  ✓ Created reservations")
        
        # ========== PAYMENT METHODS ==========
        print("\n[6/6] Creating payment methods...")
        if created_users:
            # Add payment methods for regular users (not admin)
            regular_users = [u for u in created_users if u.role != "admin"]
            for user in regular_users[:3]:  # First 3 regular users
                card_types = ["visa", "mastercard", "amex"]
                for i, card_type in enumerate(card_types[:2]):  # 2 cards per user
                    pm = PaymentMethod(
                        user_id=user.id,
                        card_type=card_type,
                        last4=str(random.randint(1000, 9999)),
                        expiry_month=random.randint(1, 12),
                        expiry_year=random.randint(2025, 2027),
                        cardholder_name=user.full_name,
                        is_default=(i == 0),
                        is_active=True,
                    )
                    session.add(pm)
                    print(f"  ✓ Added {card_type} card for {user.email}")
        
        await session.commit()
        
        print("\n" + "=" * 60)
        print("✓ DUMMY DATA SEEDING COMPLETE!")
        print("=" * 60)
        print("\nAdmin Credentials:")
        print("  Email: admin@glimmora.local")
        print("  Password: admin123")
        print("\nOther Users:")
        print("  - frontdesk@glimmora.local / frontdesk123")
        print("  - finance@glimmora.local / finance123")
        print("  - manager@glimmora.local / manager123")
        print("  - ishanagrawal1201@gmail.com / Ishan@1201")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed_dummy_data())

