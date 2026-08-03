"""
Initial Database Seed Script for Glimmora Hotel Management System
Creates all tables and seeds ONLY: Admin, Staff, and Rooms
"""
import asyncio
from datetime import datetime, date, time
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import engine, async_session_maker, init_db
from app.core.security import get_password_hash
from app.models.user import User
from app.models.inventory import RoomType, Room
from app.models.staff import Staff

# Import ALL models to ensure tables are created
from app.models import *


async def check_and_seed_admin(session: AsyncSession) -> User:
    """Create admin user if not exists"""
    result = await session.exec(select(User).where(User.email == "admin@glimmora.com"))
    admin = result.first()

    if admin:
        print("  [EXISTS] Admin user already exists")
        return admin

    admin = User(
        email="admin@glimmora.com",
        hashed_password=get_password_hash("admin123"),
        full_name="System Administrator",
        phone="+1-555-0100",
        role="admin",
        is_superuser=True,
        is_active=True,
        email_verified=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    session.add(admin)
    await session.commit()
    await session.refresh(admin)
    print(f"  [CREATED] Admin: {admin.email}")
    return admin


async def check_and_seed_staff(session: AsyncSession) -> list:
    """Create staff users and their staff records"""
    staff_data = [
        {
            "user": {
                "email": "manager@glimmora.com",
                "full_name": "Sarah Johnson",
                "phone": "+1-555-0101",
                "role": "manager",
            },
            "staff": {
                "employee_id": "EMP001",
                "department": "management",
                "role": "Hotel Manager",
                "specialty": None,
                "shift": "day"
            }
        },
        {
            "user": {
                "email": "frontdesk@glimmora.com",
                "full_name": "Michael Chen",
                "phone": "+1-555-0102",
                "role": "front_desk",
            },
            "staff": {
                "employee_id": "EMP002",
                "department": "frontdesk",
                "role": "Front Desk Agent",
                "specialty": "guest_services",
                "shift": "morning"
            }
        },
        {
            "user": {
                "email": "housekeeping@glimmora.com",
                "full_name": "Maria Garcia",
                "phone": "+1-555-0103",
                "role": "housekeeping",
            },
            "staff": {
                "employee_id": "EMP003",
                "department": "housekeeping",
                "role": "Housekeeping Supervisor",
                "specialty": "laundry",
                "shift": "morning"
            }
        },
        {
            "user": {
                "email": "maintenance@glimmora.com",
                "full_name": "James Wilson",
                "phone": "+1-555-0104",
                "role": "maintenance",
            },
            "staff": {
                "employee_id": "EMP004",
                "department": "maintenance",
                "role": "Maintenance Technician",
                "specialty": "electrical",
                "shift": "day"
            }
        },
        {
            "user": {
                "email": "runner@glimmora.com",
                "full_name": "David Kim",
                "phone": "+1-555-0105",
                "role": "runner",
            },
            "staff": {
                "employee_id": "EMP005",
                "department": "runner",
                "role": "Bell Staff",
                "specialty": None,
                "shift": "day"
            }
        }
    ]

    created_staff = []

    for data in staff_data:
        # Check if user exists
        result = await session.exec(select(User).where(User.email == data["user"]["email"]))
        user = result.first()

        if user:
            print(f"  [EXISTS] Staff: {data['user']['email']}")
            continue

        # Create user
        user = User(
            email=data["user"]["email"],
            hashed_password=get_password_hash("staff123"),
            full_name=data["user"]["full_name"],
            phone=data["user"]["phone"],
            role=data["user"]["role"],
            is_superuser=False,
            is_active=True,
            email_verified=True,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        # Create staff record
        staff = Staff(
            user_id=user.id,
            employee_id=data["staff"]["employee_id"],
            name=user.full_name,
            email=user.email,
            phone=user.phone,
            role=data["staff"]["role"],
            department=data["staff"]["department"],
            specialty=data["staff"]["specialty"],
            status="active",
            shift=data["staff"]["shift"],
            shift_start=time(8, 0) if data["staff"]["shift"] == "morning" else time(9, 0),
            shift_end=time(16, 0) if data["staff"]["shift"] == "morning" else time(17, 0),
            clocked_in=False,
            hire_date=date.today(),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(staff)
        await session.commit()
        await session.refresh(staff)

        created_staff.append(staff)
        print(f"  [CREATED] Staff: {user.full_name} ({data['staff']['department']})")

    return created_staff


async def check_and_seed_room_types(session: AsyncSession) -> list:
    """Create room types"""
    room_types_data = [
        {
            "name": "Minimalist Studio",
            "slug": "minimalist-studio",
            "category": "standard",
            "description": "Clean lines, natural materials, and purposeful design create a calm environment.",
            "short_description": "Elegant simplicity with modern comfort",
            "base_price": 180.00,
            "max_guests": 2,
            "bed_type": "Queen",
            "size_sqft": 280,
            "view_type": "Courtyard",
            "rating": 4.6,
            "sort_order": 1
        },
        {
            "name": "Coastal Retreat",
            "slug": "coastal-retreat",
            "category": "standard",
            "description": "Natural textures and modern comfort with organic materials and garden views.",
            "short_description": "Organic materials and garden views",
            "base_price": 185.00,
            "max_guests": 2,
            "bed_type": "Queen",
            "size_sqft": 320,
            "view_type": "Garden",
            "rating": 4.7,
            "sort_order": 2
        },
        {
            "name": "Urban Oasis",
            "slug": "urban-oasis",
            "category": "deluxe",
            "description": "Contemporary design meets California ease with natural wood accents.",
            "short_description": "Spacious elegance with city views",
            "base_price": 245.00,
            "max_guests": 3,
            "bed_type": "King",
            "size_sqft": 425,
            "view_type": "City",
            "rating": 4.8,
            "sort_order": 3
        },
        {
            "name": "Sunset Vista",
            "slug": "sunset-vista",
            "category": "deluxe",
            "description": "Westward-facing suite designed to capture California's legendary sunsets.",
            "short_description": "Stunning sunset views with private balcony",
            "base_price": 315.00,
            "max_guests": 3,
            "bed_type": "King",
            "size_sqft": 450,
            "view_type": "Ocean Sunset",
            "rating": 4.9,
            "sort_order": 4
        },
        {
            "name": "Pacific Suite",
            "slug": "pacific-suite",
            "category": "suite",
            "description": "Expansive retreat with separate living area and ocean views.",
            "short_description": "Luxury suite with living area",
            "base_price": 385.00,
            "max_guests": 4,
            "bed_type": "King",
            "size_sqft": 680,
            "view_type": "Ocean",
            "rating": 4.9,
            "sort_order": 5
        },
        {
            "name": "Wellness Suite",
            "slug": "wellness-suite",
            "category": "suite",
            "description": "Health-focused luxury with meditation space and wellness amenities.",
            "short_description": "Wellness-focused with meditation space",
            "base_price": 425.00,
            "max_guests": 2,
            "bed_type": "King",
            "size_sqft": 520,
            "view_type": "Ocean",
            "rating": 5.0,
            "sort_order": 6
        },
        {
            "name": "Family Sanctuary",
            "slug": "family-sanctuary",
            "category": "suite",
            "description": "Expansive suite with two bedrooms and spacious living areas.",
            "short_description": "Two bedrooms for families",
            "base_price": 485.00,
            "max_guests": 6,
            "bed_type": "1 King + 2 Twin",
            "size_sqft": 780,
            "view_type": "Garden & Ocean",
            "rating": 4.8,
            "sort_order": 7
        },
        {
            "name": "Oceanfront Penthouse",
            "slug": "oceanfront-penthouse",
            "category": "presidential",
            "description": "The pinnacle of luxury with panoramic ocean views and private terrace.",
            "short_description": "Ultimate luxury with panoramic views",
            "base_price": 750.00,
            "max_guests": 4,
            "bed_type": "California King",
            "size_sqft": 1100,
            "view_type": "Panoramic Ocean",
            "rating": 5.0,
            "sort_order": 8
        }
    ]

    created_types = []

    for data in room_types_data:
        result = await session.exec(select(RoomType).where(RoomType.slug == data["slug"]))
        room_type = result.first()

        if room_type:
            print(f"  [EXISTS] Room Type: {data['name']}")
            created_types.append(room_type)
            continue

        room_type = RoomType(
            name=data["name"],
            slug=data["slug"],
            category=data["category"],
            description=data["description"],
            short_description=data["short_description"],
            base_price=data["base_price"],
            max_guests=data["max_guests"],
            bed_type=data["bed_type"],
            size_sqft=data["size_sqft"],
            view_type=data["view_type"],
            rating=data["rating"],
            is_active=True,
            sort_order=data["sort_order"],
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(room_type)
        await session.commit()
        await session.refresh(room_type)

        created_types.append(room_type)
        print(f"  [CREATED] Room Type: {room_type.name} (${room_type.base_price})")

    return created_types


async def check_and_seed_rooms(session: AsyncSession, room_types: list) -> list:
    """Create physical rooms"""
    type_map = {rt.slug: rt for rt in room_types}

    rooms_data = [
        # Minimalist Studios (Floor 1)
        {"number": "101", "floor": 1, "room_type": "minimalist-studio", "view_type": "Courtyard"},
        {"number": "102", "floor": 1, "room_type": "minimalist-studio", "view_type": "Courtyard"},
        {"number": "103", "floor": 1, "room_type": "minimalist-studio", "view_type": "Courtyard"},

        # Coastal Retreats (Floor 1-2)
        {"number": "104", "floor": 1, "room_type": "coastal-retreat", "view_type": "Garden"},
        {"number": "201", "floor": 2, "room_type": "coastal-retreat", "view_type": "Garden"},
        {"number": "202", "floor": 2, "room_type": "coastal-retreat", "view_type": "Garden"},

        # Urban Oasis (Floor 2-3)
        {"number": "203", "floor": 2, "room_type": "urban-oasis", "view_type": "City"},
        {"number": "204", "floor": 2, "room_type": "urban-oasis", "view_type": "City"},
        {"number": "301", "floor": 3, "room_type": "urban-oasis", "view_type": "City"},
        {"number": "302", "floor": 3, "room_type": "urban-oasis", "view_type": "City"},

        # Sunset Vista (Floor 3-4)
        {"number": "303", "floor": 3, "room_type": "sunset-vista", "view_type": "Ocean Sunset"},
        {"number": "304", "floor": 3, "room_type": "sunset-vista", "view_type": "Ocean Sunset"},
        {"number": "401", "floor": 4, "room_type": "sunset-vista", "view_type": "Ocean Sunset"},
        {"number": "402", "floor": 4, "room_type": "sunset-vista", "view_type": "Ocean Sunset"},

        # Pacific Suite (Floor 4-5)
        {"number": "403", "floor": 4, "room_type": "pacific-suite", "view_type": "Ocean"},
        {"number": "501", "floor": 5, "room_type": "pacific-suite", "view_type": "Ocean"},
        {"number": "502", "floor": 5, "room_type": "pacific-suite", "view_type": "Ocean"},

        # Wellness Suite (Floor 5)
        {"number": "503", "floor": 5, "room_type": "wellness-suite", "view_type": "Ocean"},
        {"number": "504", "floor": 5, "room_type": "wellness-suite", "view_type": "Ocean"},

        # Family Sanctuary (Floor 6)
        {"number": "601", "floor": 6, "room_type": "family-sanctuary", "view_type": "Garden & Ocean"},
        {"number": "602", "floor": 6, "room_type": "family-sanctuary", "view_type": "Garden & Ocean"},

        # Oceanfront Penthouse (Floor 7)
        {"number": "701", "floor": 7, "room_type": "oceanfront-penthouse", "view_type": "Panoramic Ocean"},
        {"number": "702", "floor": 7, "room_type": "oceanfront-penthouse", "view_type": "Panoramic Ocean"},
    ]

    created_rooms = []

    for data in rooms_data:
        result = await session.exec(select(Room).where(Room.number == data["number"]))
        room = result.first()

        if room:
            print(f"  [EXISTS] Room: {data['number']}")
            continue

        room_type = type_map.get(data["room_type"])
        if not room_type:
            print(f"  [SKIP] Room {data['number']} - room type not found")
            continue

        room = Room(
            room_type_id=room_type.id,
            number=data["number"],
            floor=data["floor"],
            status="available",
            condition="excellent",
            capacity=room_type.max_guests,
            max_occupancy=room_type.max_guests,
            bed_type=room_type.bed_type,
            view_type=data["view_type"],
            size_sqft=room_type.size_sqft,
            is_smoking=False,
            is_accessible=(data["number"] in ["101", "201"]),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        session.add(room)
        await session.commit()
        await session.refresh(room)

        created_rooms.append(room)
        print(f"  [CREATED] Room: {room.number} ({room_type.name})")

    return created_rooms


async def main():
    """Main seeding function"""
    print("=" * 60)
    print("GLIMMORA - Initial Database Setup")
    print("=" * 60)

    # Initialize database (creates ALL tables)
    print("\n[1/5] Initializing database and creating tables...")
    await init_db()
    print("  Database initialized - all tables created.")

    async with async_session_maker() as session:
        # Seed admin
        print("\n[2/5] Setting up Admin User...")
        await check_and_seed_admin(session)

        # Seed staff
        print("\n[3/5] Setting up Staff Users...")
        await check_and_seed_staff(session)

        # Seed room types
        print("\n[4/5] Setting up Room Types...")
        room_types = await check_and_seed_room_types(session)

        # Seed rooms
        print("\n[5/5] Setting up Rooms...")
        await check_and_seed_rooms(session, room_types)

    print("\n" + "=" * 60)
    print("DATABASE SETUP COMPLETE!")
    print("=" * 60)
    print("\nLogin Credentials:")
    print("-" * 40)
    print("ADMIN:")
    print("  Email:    admin@glimmora.com")
    print("  Password: admin123")
    print("\nSTAFF (all use password 'staff123'):")
    print("  - manager@glimmora.com      (Hotel Manager)")
    print("  - frontdesk@glimmora.com    (Front Desk)")
    print("  - housekeeping@glimmora.com (Housekeeping)")
    print("  - maintenance@glimmora.com  (Maintenance)")
    print("  - runner@glimmora.com       (Bell Staff)")
    print("-" * 40)
    print("\nRooms: 23 rooms across 8 room types")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
