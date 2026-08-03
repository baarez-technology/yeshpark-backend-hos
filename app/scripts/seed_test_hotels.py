#!/usr/bin/env python3
"""
Seed test data for multi-tenant hotels.

Seeds data into Crown Plaza Kochi and Marriott Mumbai for testing.
"""
import asyncio
from datetime import datetime, date, timedelta
from app.db.tenant_manager import tenant_manager
from app.models.user import User
from app.models.inventory import RoomType, Room, RatePlan
from app.models.reservations import Guest, Reservation
from app.core.security import get_password_hash


async def seed_hotel(hotel_code: str, hotel_name: str, room_prefix: str):
    """Seed test data for a single hotel."""
    print(f"\n{'='*60}")
    print(f"Seeding data for: {hotel_name} ({hotel_code})")
    print(f"{'='*60}")

    async for session in tenant_manager.get_session(hotel_code):
        # 1. Create Admin User
        print("\n[1/4] Creating admin user...")
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

        # Create staff user
        staff = User(
            email=f"staff@{hotel_code.replace('_', '')}.com",
            hashed_password=get_password_hash("staff123"),
            full_name=f"{hotel_name} Staff",
            role="front_desk",
            is_superuser=False,
            hotel_code=hotel_code,
            is_active=True,
            email_verified=True,
        )
        session.add(staff)
        print(f"   Created: {admin.email}, {staff.email}")

        # 2. Create Room Types
        print("\n[2/4] Creating room types...")
        room_types = [
            RoomType(
                name="Standard Room",
                slug=f"{hotel_code}_standard",
                category="standard",
                description="Comfortable standard room with city view",
                base_price=3500.00,
                max_guests=2,
                bed_type="Queen",
                amenities=["WiFi", "TV", "AC", "Mini Bar"],
                is_active=True,
            ),
            RoomType(
                name="Deluxe Room",
                slug=f"{hotel_code}_deluxe",
                category="deluxe",
                description="Spacious deluxe room with premium amenities",
                base_price=5500.00,
                max_guests=3,
                bed_type="King",
                amenities=["WiFi", "TV", "AC", "Mini Bar", "Bathtub", "Balcony"],
                is_active=True,
            ),
            RoomType(
                name="Suite",
                slug=f"{hotel_code}_suite",
                category="suite",
                description="Luxury suite with separate living area",
                base_price=9000.00,
                max_guests=4,
                bed_type="King",
                amenities=["WiFi", "TV", "AC", "Mini Bar", "Bathtub", "Balcony", "Living Room", "Kitchen"],
                is_active=True,
            ),
        ]
        for rt in room_types:
            session.add(rt)
        await session.flush()  # Get IDs
        print(f"   Created: {[rt.name for rt in room_types]}")

        # 3. Create Rooms
        print("\n[3/4] Creating rooms...")
        rooms = []
        room_configs = [
            # (floor, count, room_type_index)
            (1, 5, 0),  # Floor 1: 5 Standard rooms
            (2, 5, 0),  # Floor 2: 5 Standard rooms
            (3, 4, 1),  # Floor 3: 4 Deluxe rooms
            (4, 3, 1),  # Floor 4: 3 Deluxe rooms
            (5, 2, 2),  # Floor 5: 2 Suites
        ]

        for floor, count, rt_idx in room_configs:
            for i in range(1, count + 1):
                room = Room(
                    number=f"{room_prefix}{floor}{i:02d}",
                    floor=floor,
                    room_type_id=room_types[rt_idx].id,
                    status="available",
                    is_smoking=False,
                    has_balcony=(rt_idx >= 1),
                    bed_type="King" if rt_idx >= 1 else "Queen",
                )
                session.add(room)
                rooms.append(room)

        await session.flush()
        print(f"   Created: {len(rooms)} rooms ({room_prefix}101 to {room_prefix}502)")

        # 4. Create Rate Plans
        print("\n[4/5] Creating rate plans...")
        rate_plan = RatePlan(
            code=f"{hotel_code}_BAR",
            name="Best Available Rate",
            description="Standard best available rate",
            plan_type="BAR",
            currency="INR",
            base_price=0.0,  # Uses room type base price
            is_active=True,
        )
        session.add(rate_plan)
        await session.flush()
        print(f"   Created: {rate_plan.name} ({rate_plan.code})")

        # 5. Create Guests and Reservations
        print("\n[5/5] Creating guests and reservations...")
        guests_data = [
            ("Rajesh", "Kumar", "rajesh.kumar@email.com", "+91-9876543210"),
            ("Priya", "Sharma", "priya.sharma@email.com", "+91-9876543211"),
            ("Amit", "Patel", "amit.patel@email.com", "+91-9876543212"),
            ("Sneha", "Reddy", "sneha.reddy@email.com", "+91-9876543213"),
        ]

        today = date.today()

        for idx, (first, last, email, phone) in enumerate(guests_data):
            # Create guest
            guest = Guest(
                first_name=first,
                last_name=last,
                email=f"{hotel_code}_{email}",  # Make email unique per hotel
                phone=phone,
                status="Active",
                member_since=datetime.utcnow(),
            )
            session.add(guest)
            await session.flush()

            # Create reservation for first 2 guests
            if idx < 2:
                arrival = today + timedelta(days=idx + 1)
                departure = arrival + timedelta(days=3)

                reservation = Reservation(
                    guest_id=guest.id,
                    room_id=rooms[idx].id,
                    room_type_id=room_types[0].id,
                    rate_plan_id=rate_plan.id,
                    arrival_date=arrival,
                    departure_date=departure,
                    adults=2,
                    children=0,
                    status="confirmed",
                    confirmation_code=f"{room_prefix}{today.strftime('%Y%m%d')}{idx+1:03d}",
                    total_amount=room_types[0].base_price * 3,
                    currency="INR",
                    booking_source="direct",
                )
                session.add(reservation)
                print(f"   Guest: {first} {last} -> Reservation {reservation.confirmation_code}")
            else:
                print(f"   Guest: {first} {last} (no reservation)")

        await session.commit()
        print(f"\nData seeded successfully for {hotel_name}!")


async def main():
    """Seed data for all test hotels."""
    print("\n" + "=" * 60)
    print("   MULTI-TENANT TEST DATA SEEDING")
    print("=" * 60)

    # Seed Crown Plaza Kochi
    await seed_hotel(
        hotel_code="crownplaza_kochi",
        hotel_name="Crown Plaza Kochi",
        room_prefix="CP"
    )

    # Seed Marriott Mumbai
    await seed_hotel(
        hotel_code="marriott_mumbai",
        hotel_name="Marriott Hotel Mumbai",
        room_prefix="MR"
    )

    print("\n" + "=" * 60)
    print("   SEEDING COMPLETE!")
    print("=" * 60)
    print("\nTest Credentials:")
    print("-" * 40)
    print("Crown Plaza Kochi:")
    print("  Admin: admin@crownplazakochi.com / admin123")
    print("  Staff: staff@crownplazakochi.com / staff123")
    print("\nMarriott Mumbai:")
    print("  Admin: admin@marriottmumbai.com / admin123")
    print("  Staff: staff@marriottmumbai.com / staff123")
    print("-" * 40)


if __name__ == "__main__":
    asyncio.run(main())
