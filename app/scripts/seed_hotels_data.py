#!/usr/bin/env python3
"""
Seed comprehensive test data for multi-tenant hotels.

Seeds Crown Plaza Kochi and Marriott Mumbai with distinct pricing
for easy testing and verification of multi-tenant isolation.

Usage:
    python -m app.scripts.seed_hotels_data
"""
import asyncio
import json
from datetime import datetime, date, timedelta
from sqlmodel import select, delete
from app.db.tenant_manager import tenant_manager
from app.models.user import User
from app.models.inventory import RoomType, Room, RatePlan
from app.models.reservations import Guest, Reservation
from app.models.staff import Staff
from app.core.security import get_password_hash


async def clear_hotel_data(session):
    """Clear existing data to allow fresh seeding."""
    print("   Clearing existing data...")

    # Import additional models that may have foreign keys
    from app.models.inventory import DailyAvailability, RoomHold, RoomBlock, DailyRate

    # Delete in order respecting foreign keys (children first)
    try:
        # Delete availability-related first
        await session.exec(delete(DailyAvailability))
        await session.exec(delete(DailyRate))
        await session.exec(delete(RoomHold))
        await session.exec(delete(RoomBlock))

        # Delete reservations and guests
        await session.exec(delete(Reservation))
        await session.exec(delete(Guest))

        # Delete rooms, then room types
        await session.exec(delete(Room))
        await session.exec(delete(RoomType))

        # Delete rate plans
        await session.exec(delete(RatePlan))

        # Delete staff
        await session.exec(delete(Staff))

        await session.commit()
        print("   Existing data cleared.")
    except Exception as e:
        await session.rollback()
        print(f"   Warning: Could not clear some data: {e}")
        # Try to continue anyway


async def seed_hotel(
    hotel_code: str,
    hotel_name: str,
    room_prefix: str,
    prices: dict,  # {"standard": 8500, "deluxe": 16500, "suite": 25000}
    currency: str = "INR"
):
    """Seed comprehensive test data for a single hotel."""
    print(f"\n{'='*60}")
    print(f"  SEEDING: {hotel_name} ({hotel_code})")
    print(f"  Prices: Standard=₹{prices['standard']}, Deluxe=₹{prices['deluxe']}, Suite=₹{prices['suite']}")
    print(f"{'='*60}")

    async for session in tenant_manager.get_session(hotel_code):
        # Clear existing data
        await clear_hotel_data(session)

        # 1. Create/Update Admin User
        print("\n[1/6] Setting up users...")

        # Check if admin exists
        result = await session.exec(
            select(User).where(User.email == f"admin@{hotel_code.replace('_', '')}.com")
        )
        admin = result.first()

        if not admin:
            admin = User(
                email=f"admin@{hotel_code.replace('_', '')}.com",
                hashed_password=get_password_hash("admin123"),
                full_name=f"{hotel_name} Admin",
                role="admin",
                is_superuser=True,
                hotel_code=hotel_code,
                is_active=True,
                email_verified=True,
            )
            session.add(admin)

        # Check if staff exists
        result = await session.exec(
            select(User).where(User.email == f"staff@{hotel_code.replace('_', '')}.com")
        )
        staff_user = result.first()

        if not staff_user:
            staff_user = User(
                email=f"staff@{hotel_code.replace('_', '')}.com",
                hashed_password=get_password_hash("staff123"),
                full_name=f"{hotel_name} Staff",
                role="front_desk",
                is_superuser=False,
                hotel_code=hotel_code,
                is_active=True,
                email_verified=True,
            )
            session.add(staff_user)

        await session.flush()
        print(f"   Admin: admin@{hotel_code.replace('_', '')}.com")
        print(f"   Staff: staff@{hotel_code.replace('_', '')}.com")

        # 2. Create Room Types with distinct pricing
        print("\n[2/6] Creating room types...")
        room_types = [
            RoomType(
                name="Standard Room",
                slug=f"{hotel_code}_standard",
                category="standard",
                description=f"Comfortable standard room at {hotel_name}. Perfect for business travelers.",
                short_description="Cozy room with essential amenities",
                base_price=float(prices["standard"]),
                max_guests=2,
                bed_type="Queen",
                size_sqft=280,
                view_type="city",
                amenities=json.dumps(["WiFi", "TV", "AC", "Mini Bar", "Coffee Maker"]),
                features=json.dumps(["Work Desk", "Blackout Curtains", "Iron & Board"]),
                images=json.dumps([
                    f"/images/rooms/{hotel_code}/standard_1.jpg",
                    f"/images/rooms/{hotel_code}/standard_2.jpg"
                ]),
                rating=4.2,
                review_count=45,
                is_active=True,
                sort_order=1,
            ),
            RoomType(
                name="Deluxe Room",
                slug=f"{hotel_code}_deluxe",
                category="deluxe",
                description=f"Spacious deluxe room at {hotel_name} with premium amenities and city views.",
                short_description="Upgraded room with balcony",
                base_price=float(prices["deluxe"]),
                max_guests=3,
                bed_type="King",
                size_sqft=380,
                view_type="city",
                amenities=json.dumps(["WiFi", "TV", "AC", "Mini Bar", "Coffee Maker", "Bathtub", "Balcony"]),
                features=json.dumps(["Work Desk", "Blackout Curtains", "Iron & Board", "Lounge Chair", "Premium Toiletries"]),
                images=json.dumps([
                    f"/images/rooms/{hotel_code}/deluxe_1.jpg",
                    f"/images/rooms/{hotel_code}/deluxe_2.jpg"
                ]),
                rating=4.5,
                review_count=78,
                is_active=True,
                sort_order=2,
            ),
            RoomType(
                name="Executive Suite",
                slug=f"{hotel_code}_suite",
                category="suite",
                description=f"Luxury suite at {hotel_name} with separate living area, premium amenities, and panoramic views.",
                short_description="Luxury suite with living room",
                base_price=float(prices["suite"]),
                max_guests=4,
                bed_type="King",
                size_sqft=550,
                view_type="ocean" if "kochi" in hotel_code else "city",
                amenities=json.dumps(["WiFi", "TV", "AC", "Mini Bar", "Coffee Maker", "Bathtub", "Balcony", "Living Room", "Kitchenette", "Jacuzzi"]),
                features=json.dumps(["Work Desk", "Blackout Curtains", "Iron & Board", "Lounge Chair", "Premium Toiletries", "Butler Service", "Dining Area"]),
                images=json.dumps([
                    f"/images/rooms/{hotel_code}/suite_1.jpg",
                    f"/images/rooms/{hotel_code}/suite_2.jpg"
                ]),
                rating=4.8,
                review_count=32,
                is_active=True,
                sort_order=3,
            ),
        ]

        for rt in room_types:
            session.add(rt)
        await session.flush()

        for rt in room_types:
            print(f"   {rt.name}: ₹{rt.base_price}/night")

        # 3. Create Rooms
        print("\n[3/6] Creating rooms...")
        rooms = []
        room_configs = [
            # (floor, count, room_type_index, view)
            (1, 4, 0, "city"),      # Floor 1: 4 Standard rooms
            (2, 4, 0, "city"),      # Floor 2: 4 Standard rooms
            (3, 3, 1, "city"),      # Floor 3: 3 Deluxe rooms
            (4, 3, 1, "pool"),      # Floor 4: 3 Deluxe rooms (pool view)
            (5, 2, 2, "ocean" if "kochi" in hotel_code else "city"),  # Floor 5: 2 Suites
        ]

        for floor, count, rt_idx, view in room_configs:
            for i in range(1, count + 1):
                room_number = f"{room_prefix}{floor}{i:02d}"
                room = Room(
                    number=room_number,
                    floor=floor,
                    room_type_id=room_types[rt_idx].id,
                    status="available",
                    condition="excellent",
                    capacity=room_types[rt_idx].max_guests,
                    max_occupancy=room_types[rt_idx].max_guests,
                    bed_type=room_types[rt_idx].bed_type,
                    view_type=view,
                    size_sqft=room_types[rt_idx].size_sqft,
                    is_smoking=False,
                    is_accessible=(i == 1 and floor == 1),  # First room on ground floor is accessible
                    price_per_night=None,  # Uses room type base price
                    last_cleaned=datetime.utcnow() - timedelta(hours=2),
                    last_inspection=datetime.utcnow() - timedelta(hours=1),
                )
                session.add(room)
                rooms.append(room)

        await session.flush()
        print(f"   Created {len(rooms)} rooms: {room_prefix}101 to {room_prefix}502")

        # Count by type
        standard_count = sum(1 for r in rooms if r.room_type_id == room_types[0].id)
        deluxe_count = sum(1 for r in rooms if r.room_type_id == room_types[1].id)
        suite_count = sum(1 for r in rooms if r.room_type_id == room_types[2].id)
        print(f"   Breakdown: {standard_count} Standard, {deluxe_count} Deluxe, {suite_count} Suite")

        # 4. Create Rate Plans
        print("\n[4/6] Creating rate plans...")
        rate_plans = [
            RatePlan(
                code=f"{hotel_code.upper()}_BAR",
                name="Best Available Rate",
                description="Standard best available rate - flexible cancellation",
                plan_type="BAR",
                currency=currency,
                base_price=0.0,
                is_active=True,
            ),
            RatePlan(
                code=f"{hotel_code.upper()}_CORP",
                name="Corporate Rate",
                description="Special rate for corporate guests",
                plan_type="corporate",
                currency=currency,
                base_price=0.0,
                is_active=True,
            ),
            RatePlan(
                code=f"{hotel_code.upper()}_PKG",
                name="Package Deal",
                description="Room + breakfast package",
                plan_type="package",
                currency=currency,
                base_price=0.0,
                is_active=True,
            ),
        ]

        for rp in rate_plans:
            session.add(rp)
        await session.flush()

        for rp in rate_plans:
            print(f"   {rp.name} ({rp.code})")

        # 5. Create Staff Members (linked to users)
        print("\n[5/6] Creating staff members...")

        # Create staff users first
        staff_users_data = [
            ("John Doe", f"housekeeping1@{hotel_code.replace('_', '')}.com", "housekeeping"),
            ("Jane Smith", f"housekeeping2@{hotel_code.replace('_', '')}.com", "housekeeping"),
            ("Mike Johnson", f"maintenance@{hotel_code.replace('_', '')}.com", "maintenance"),
            ("Sarah Williams", f"frontdesk2@{hotel_code.replace('_', '')}.com", "front_desk"),
        ]

        staff_users = []
        for name, email, role in staff_users_data:
            # Check if user exists
            result = await session.exec(select(User).where(User.email == email))
            user = result.first()
            if not user:
                user = User(
                    email=email,
                    hashed_password=get_password_hash("staff123"),
                    full_name=name,
                    role=role,
                    is_superuser=False,
                    hotel_code=hotel_code,
                    is_active=True,
                    email_verified=True,
                )
                session.add(user)
            staff_users.append((user, name, email, role))

        await session.flush()

        # Now create Staff records
        staff_records = []
        for idx, (user, name, email, dept) in enumerate(staff_users):
            staff = Staff(
                user_id=user.id,
                name=name,
                email=email,
                phone=f"+1-555-010{idx+1}",
                role=dept,
                department=dept,
                status="active",
                hire_date=date.today() - timedelta(days=(idx + 1) * 180),
            )
            session.add(staff)
            staff_records.append(staff)

        await session.flush()
        print(f"   Created {len(staff_records)} staff members")

        # 6. Create Guests and Reservations
        print("\n[6/6] Creating guests and sample reservations...")
        guests_data = [
            ("Michael", "Brown", "michael.brown@email.com", "+1-555-1001", "USA"),
            ("Emily", "Davis", "emily.davis@email.com", "+1-555-1002", "USA"),
            ("James", "Wilson", "james.wilson@email.com", "+44-20-7946-0958", "UK"),
            ("Sophia", "Garcia", "sophia.garcia@email.com", "+34-91-123-4567", "Spain"),
            ("Liam", "Martinez", "liam.martinez@email.com", "+1-555-1003", "USA"),
            ("Olivia", "Anderson", "olivia.anderson@email.com", "+61-2-9876-5432", "Australia"),
        ]

        today = date.today()
        guests = []

        for idx, (first, last, email, phone, country) in enumerate(guests_data):
            guest = Guest(
                first_name=first,
                last_name=last,
                email=f"{hotel_code}_{email}",
                phone=phone,
                nationality=country,
                status="Active",
                vip_status=(idx == 0),  # First guest is VIP
                loyalty_tier="gold" if idx == 0 else ("silver" if idx == 1 else None),
                member_since=datetime.utcnow() - timedelta(days=idx * 60),
                total_bookings=idx + 1,
                total_spent=float(prices["standard"]) * (idx + 1) * 2,
            )
            session.add(guest)
            guests.append(guest)

        await session.flush()

        # Create reservations with different scenarios
        reservations_data = [
            # (guest_idx, room_idx, days_from_now, nights, status)
            (0, 0, 1, 3, "confirmed"),      # Michael: arriving tomorrow, 3 nights
            (1, 1, 2, 2, "confirmed"),      # Emily: arriving in 2 days, 2 nights
            (2, 8, 0, 4, "checked_in"),     # James: checked in today (Deluxe room)
            (3, 9, -1, 2, "checked_in"),    # Sophia: checked in yesterday (Deluxe)
            (4, 14, 5, 3, "confirmed"),     # Liam: Suite booked for 5 days later
            (5, 2, 7, 2, "confirmed"),      # Olivia: Standard room, next week
        ]

        for guest_idx, room_idx, days_offset, nights, status in reservations_data:
            arrival = today + timedelta(days=days_offset)
            departure = arrival + timedelta(days=nights)
            room = rooms[room_idx]
            room_type = room_types[[0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 2, 2][room_idx]]

            total = room_type.base_price * nights

            reservation = Reservation(
                guest_id=guests[guest_idx].id,
                room_id=room.id,
                room_type_id=room_type.id,
                rate_plan_id=rate_plans[0].id,
                arrival_date=arrival,
                departure_date=departure,
                check_in_time=datetime.combine(arrival, datetime.min.time().replace(hour=14)) if status == "checked_in" else None,
                adults=2,
                children=0,
                status=status,
                confirmation_code=f"{room_prefix}{today.strftime('%m%d')}{guest_idx+1:03d}",
                total_amount=total,
                currency=currency,
                booking_source="direct" if guest_idx % 2 == 0 else "booking.com",
                special_requests="Early check-in requested" if guest_idx == 0 else None,
            )
            session.add(reservation)

            # Update room status for checked-in guests
            if status == "checked_in":
                room.status = "occupied"

            print(f"   {guests[guest_idx].first_name} {guests[guest_idx].last_name}: "
                  f"{room.number} ({room_type.name}) - {status} - ₹{total}")

        await session.commit()

        print(f"\n{'='*60}")
        print(f"  {hotel_name} seeded successfully!")
        print(f"{'='*60}")


async def main():
    """Seed data for all test hotels with distinct pricing."""
    print("\n" + "=" * 60)
    print("   MULTI-TENANT HOTEL DATA SEEDING")
    print("=" * 60)
    print("\nThis will seed test data with distinct pricing:")
    print("  - Crown Plaza Kochi: ₹8,500 / ₹16,500 / ₹25,000")
    print("  - Marriott Mumbai:   ₹12,500 / ₹21,000 / ₹29,000")

    # Seed Crown Plaza Kochi - Lower prices
    await seed_hotel(
        hotel_code="crownplaza_kochi",
        hotel_name="Crown Plaza Kochi",
        room_prefix="CP",
        prices={"standard": 8500, "deluxe": 16500, "suite": 25000},
        currency="INR"
    )

    # Seed Marriott Mumbai - Higher prices
    await seed_hotel(
        hotel_code="marriott_mumbai",
        hotel_name="Marriott Hotel Mumbai",
        room_prefix="MR",
        prices={"standard": 12500, "deluxe": 21000, "suite": 29000},
        currency="INR"
    )

    print("\n" + "=" * 60)
    print("   SEEDING COMPLETE!")
    print("=" * 60)
    print("\n" + "-" * 60)
    print("TEST CREDENTIALS:")
    print("-" * 60)
    print("\nCrown Plaza Kochi (Rooms: ₹8,500 / ₹16,500 / ₹25,000):")
    print("  Admin: admin@crownplazakochi.com / admin123")
    print("  Staff: staff@crownplazakochi.com / staff123")
    print("\nMarriott Mumbai (Rooms: ₹12,500 / ₹21,000 / ₹29,000):")
    print("  Admin: admin@marriottmumbai.com / admin123")
    print("  Staff: staff@marriottmumbai.com / staff123")
    print("-" * 60)
    print("\nROOM SUMMARY PER HOTEL:")
    print("-" * 60)
    print("  16 total rooms:")
    print("    - 8 Standard Rooms (Floors 1-2)")
    print("    - 6 Deluxe Rooms (Floors 3-4)")
    print("    - 2 Executive Suites (Floor 5)")
    print("-" * 60)


if __name__ == "__main__":
    asyncio.run(main())
