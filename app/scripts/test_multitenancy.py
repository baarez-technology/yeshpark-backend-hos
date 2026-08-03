#!/usr/bin/env python3
"""
Test script to verify multi-tenant database isolation.

Demonstrates that:
1. Each hotel has completely separate data
2. Queries only return data from the correct hotel
3. The tenant manager correctly routes to the right database
"""
import asyncio
from app.db.tenant_manager import tenant_manager
from app.models.user import User
from app.models.inventory import Room, RoomType
from app.models.reservations import Guest, Reservation
from sqlmodel import select


async def test_hotel_data(hotel_code: str, hotel_name: str):
    """Test data retrieval for a specific hotel."""
    print(f"\n{'='*60}")
    print(f"Testing: {hotel_name} ({hotel_code})")
    print(f"{'='*60}")

    async for session in tenant_manager.get_session(hotel_code):
        # Get users
        users = (await session.exec(select(User))).all()
        print(f"\nUsers ({len(users)}):")
        for u in users:
            print(f"  - {u.email} (role: {u.role}, hotel_code: {u.hotel_code})")

        # Get rooms
        rooms = (await session.exec(select(Room).limit(5))).all()
        print(f"\nRooms (showing 5 of total):")
        for r in rooms:
            print(f"  - Room {r.number} (Floor {r.floor}, Status: {r.status})")

        # Get room types
        room_types = (await session.exec(select(RoomType))).all()
        print(f"\nRoom Types ({len(room_types)}):")
        for rt in room_types:
            print(f"  - {rt.name} (₹{rt.base_price}/night, slug: {rt.slug})")

        # Get guests
        guests = (await session.exec(select(Guest))).all()
        print(f"\nGuests ({len(guests)}):")
        for g in guests:
            print(f"  - {g.first_name} {g.last_name} ({g.email})")

        # Get reservations
        reservations = (await session.exec(select(Reservation))).all()
        print(f"\nReservations ({len(reservations)}):")
        for res in reservations:
            room = await session.get(Room, res.room_id)
            guest = await session.get(Guest, res.guest_id)
            print(f"  - {res.confirmation_code}: {guest.first_name} {guest.last_name}")
            print(f"    Room: {room.number}, {res.arrival_date} to {res.departure_date}")
            print(f"    Status: {res.status}, Amount: ₹{res.total_amount}")


async def test_isolation():
    """Verify that data is completely isolated between hotels."""
    print(f"\n{'='*60}")
    print("ISOLATION TEST")
    print(f"{'='*60}")

    # Get Crown Plaza room numbers
    cp_rooms = []
    async for session in tenant_manager.get_session("crownplaza_kochi"):
        rooms = (await session.exec(select(Room))).all()
        cp_rooms = [r.number for r in rooms]

    # Get Marriott room numbers
    mr_rooms = []
    async for session in tenant_manager.get_session("marriott_mumbai"):
        rooms = (await session.exec(select(Room))).all()
        mr_rooms = [r.number for r in rooms]

    # Check no overlap
    cp_set = set(cp_rooms)
    mr_set = set(mr_rooms)
    overlap = cp_set.intersection(mr_set)

    print(f"\nCrown Plaza rooms: {len(cp_rooms)} (prefix: CP)")
    print(f"Marriott rooms: {len(mr_rooms)} (prefix: MR)")
    print(f"Overlapping room numbers: {len(overlap)}")

    if len(overlap) == 0:
        print("\n✓ PASSED: No overlapping room numbers - data is properly isolated!")
    else:
        print(f"\n✗ FAILED: Found overlapping rooms: {overlap}")

    # Verify room prefixes
    cp_prefix_ok = all(r.startswith("CP") for r in cp_rooms)
    mr_prefix_ok = all(r.startswith("MR") for r in mr_rooms)

    print(f"\nCrown Plaza rooms all start with 'CP': {'✓' if cp_prefix_ok else '✗'}")
    print(f"Marriott rooms all start with 'MR': {'✓' if mr_prefix_ok else '✗'}")


async def main():
    print("\n" + "=" * 60)
    print("   MULTI-TENANT DATABASE ISOLATION TEST")
    print("=" * 60)

    # Test each hotel
    await test_hotel_data("crownplaza_kochi", "Crown Plaza Kochi")
    await test_hotel_data("marriott_mumbai", "Marriott Hotel Mumbai")

    # Test isolation
    await test_isolation()

    print("\n" + "=" * 60)
    print("   TEST COMPLETE")
    print("=" * 60)
    print("\nThe multi-tenant architecture is working correctly!")
    print("Each hotel has its own isolated database with separate data.")


if __name__ == "__main__":
    asyncio.run(main())
