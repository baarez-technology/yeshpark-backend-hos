"""
In-memory data store for CRS Simulator
Includes seed data for immediate functionality
"""
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4
from typing import Dict, List, Optional, Any
from models import (
    Hotel, RoomType, Rate, Reservation, Inventory,
    BookingStatus, RatePlan
)

# Export mapping dictionaries
__all__ = [
    'hotels_db', 'room_types_db', 'rates_db', 'reservations_db', 'inventory_db', 'restrictions_db',
    'room_id_to_uuid_map', 'uuid_to_room_id_map',
    'get_hotel_room_types', 'get_room_type_rates', 'get_reservations_for_date_range',
    'get_inventory', 'update_inventory', 'initialize_inventory_for_date_range',
    'generate_confirmation_number', 'seed_data',
    'get_restrictions', 'add_restriction', 'remove_restriction', 'get_restrictions_for_room_type'
]


# In-memory data stores
hotels_db: Dict[UUID, Hotel] = {}
room_types_db: Dict[UUID, RoomType] = {}
rates_db: Dict[UUID, Rate] = {}
reservations_db: Dict[UUID, Reservation] = {}
inventory_db: Dict[tuple, Inventory] = {}  # Key: (room_type_id, date)
restrictions_db: Dict[tuple, Dict[str, Any]] = {}  # Key: (room_type_id, date, restriction_type)

# Mapping for external application format
# Maps room_id (int) to room_type_id (UUID) - index-based mapping
room_id_to_uuid_map: Dict[int, UUID] = {}
uuid_to_room_id_map: Dict[UUID, int] = {}


def get_hotel_room_types(hotel_id: UUID) -> List[RoomType]:
    """Get all room types for a hotel"""
    return [rt for rt in room_types_db.values() if rt.hotel_id == hotel_id]


def get_room_type_rates(room_type_id: UUID) -> List[Rate]:
    """Get all rates for a room type"""
    return [rate for rate in rates_db.values() if rate.room_type_id == room_type_id]


def get_reservations_for_date_range(
    room_type_id: UUID,
    check_in: date,
    check_out: date
) -> List[Reservation]:
    """Get all reservations for a room type in a date range"""
    reservations = []
    for res in reservations_db.values():
        if (res.room_type_id == room_type_id and
            res.status != BookingStatus.CANCELLED and
            res.check_in < check_out and
            res.check_out > check_in):
            reservations.append(res)
    return reservations


def get_inventory(room_type_id: UUID, target_date: date) -> Optional[Inventory]:
    """Get inventory for a room type on a specific date"""
    key = (room_type_id, target_date)
    return inventory_db.get(key)


def update_inventory(room_type_id: UUID, target_date: date, booked_delta: int) -> Inventory:
    """Update inventory by adjusting booked count"""
    key = (room_type_id, target_date)
    
    if key not in inventory_db:
        # Get room type to find total capacity
        room_type = room_types_db.get(room_type_id)
        if not room_type:
            raise ValueError(f"Room type {room_type_id} not found")
        
        inventory_db[key] = Inventory(
            room_type_id=room_type_id,
            date=target_date,
            available=room_type.base_capacity,
            total=room_type.base_capacity,
            booked=0
        )
    
    inventory = inventory_db[key]
    new_booked = max(0, min(inventory.total, inventory.booked + booked_delta))
    inventory.booked = new_booked
    inventory.available = inventory.total - new_booked
    
    return inventory


def initialize_inventory_for_date_range(
    room_type_id: UUID,
    start_date: date,
    end_date: date
):
    """Initialize inventory for a date range if not exists"""
    current_date = start_date
    while current_date < end_date:
        key = (room_type_id, current_date)
        if key not in inventory_db:
            room_type = room_types_db.get(room_type_id)
            if room_type:
                inventory_db[key] = Inventory(
                    room_type_id=room_type_id,
                    date=current_date,
                    available=room_type.base_capacity,
                    total=room_type.base_capacity,
                    booked=0
                )
        current_date += timedelta(days=1)


def generate_confirmation_number() -> str:
    """Generate CRS-style confirmation number (e.g., HRS-2024-A1B2C3)"""
    from random import choice
    import string
    
    year = datetime.now().year
    random_part = ''.join(choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"HRS-{year}-{random_part}"


def seed_data():
    """Seed the database with realistic dummy data"""
    now = datetime.now()
    
    # Create Hotels
    hotel1_id = uuid4()
    hotel1 = Hotel(
        id=hotel1_id,
        name="HOTEL YESH PARK",
        address="23/1184, SODHAN NAGAR RD, BESIDE RTC, SOASEKARA PURAM",
        city="NELLORE",
        country="India",
        timezone="Asia/Kolkata",
        created_at=now
    )
    hotels_db[hotel1_id] = hotel1
    
    # Create Room Types for HOTEL YESH PARK
    # 1) SUI - SUITE - 8 ROOMS
    rt1_id = uuid4()
    rt1 = RoomType(
        id=rt1_id,
        hotel_id=hotel1_id,
        name="Suite (SUI)",
        description="Luxury suite room with premium amenities",
        max_occupancy=3,
        base_capacity=8
    )
    room_types_db[rt1_id] = rt1
    room_id_to_uuid_map[1] = rt1_id  # Map room_id 1 to SUI
    uuid_to_room_id_map[rt1_id] = 1
    
    # 2) SUK - SUPERIOR KING - 24 ROOMS
    rt2_id = uuid4()
    rt2 = RoomType(
        id=rt2_id,
        hotel_id=hotel1_id,
        name="Superior King (SUK)",
        description="Superior king room with modern comfort",
        max_occupancy=3,
        base_capacity=24
    )
    room_types_db[rt2_id] = rt2
    room_id_to_uuid_map[2] = rt2_id  # Map room_id 2 to SUK
    uuid_to_room_id_map[rt2_id] = 2
    
    # 3) SUT - SUPERIOR TWIN - 8 ROOMS
    rt3_id = uuid4()
    rt3 = RoomType(
        id=rt3_id,
        hotel_id=hotel1_id,
        name="Superior Twin (SUT)",
        description="Superior twin room with twin beds",
        max_occupancy=3,
        base_capacity=8
    )
    room_types_db[rt3_id] = rt3
    room_id_to_uuid_map[3] = rt3_id  # Map room_id 3 to SUT
    uuid_to_room_id_map[rt3_id] = 3
    
    # Create Rates
    # Hotel 1 - Suite (SUI) rates (Single/Double: 4499, EXB: 500, Tax: 5%)
    rate1_id = uuid4()
    rate1 = Rate(
        id=rate1_id,
        room_type_id=rt1_id,
        rate_plan=RatePlan.BAR,
        base_rate=4499.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.0,
        specific_dates={},
        created_at=now
    )
    rates_db[rate1_id] = rate1

    # Hotel 1 - Superior King (SUK) rates (Single: 2499, Double: 2899, EXB: 500, Tax: 5%)
    rate2_id = uuid4()
    rate2 = Rate(
        id=rate2_id,
        room_type_id=rt2_id,
        rate_plan=RatePlan.BAR,
        base_rate=2899.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.0,
        specific_dates={},
        created_at=now
    )
    rates_db[rate2_id] = rate2

    # Hotel 1 - Superior Twin (SUT) rates (Single: 2499, Double: 2899, EXB: 500, Tax: 5%)
    rate3_id = uuid4()
    rate3 = Rate(
        id=rate3_id,
        room_type_id=rt3_id,
        rate_plan=RatePlan.BAR,
        base_rate=2899.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.0,
        specific_dates={},
        created_at=now
    )
    rates_db[rate3_id] = rate3
    
    # Initialize some inventory for next 90 days
    future_date = date.today() + timedelta(days=90)
    for room_type_id in [rt1_id, rt2_id, rt3_id]:
        initialize_inventory_for_date_range(room_type_id, date.today(), future_date)
    
    # Create a sample reservation
    sample_check_in = date.today() + timedelta(days=7)
    sample_check_out = date.today() + timedelta(days=9)
    reservation_id = uuid4()
    sample_reservation = Reservation(
        id=reservation_id,
        confirmation_number=generate_confirmation_number(),
        hotel_id=hotel1_id,
        room_type_id=rt1_id,
        check_in=sample_check_in,
        check_out=sample_check_out,
        guest_name="John Doe",
        guest_email="john.doe@example.com",
        guest_phone="+1-555-0100",
        number_of_guests=2,
        rate_plan=RatePlan.BAR,
        total_amount=31000.0,
        currency="INR",
        special_requests="Late check-in requested",
        status=BookingStatus.CONFIRMED,
        created_at=now,
        updated_at=now
    )
    reservations_db[reservation_id] = sample_reservation
    
    # Update inventory for sample reservation
    current_date = sample_check_in
    while current_date < sample_check_out:
        update_inventory(rt1_id, current_date, 1)
        current_date += timedelta(days=1)
    
    print(f"[OK] Seeded {len(hotels_db)} hotels")
    print(f"[OK] Seeded {len(room_types_db)} room types")
    print(f"[OK] Seeded {len(rates_db)} rates")
    print(f"[OK] Seeded {len(reservations_db)} reservations")
    print(f"[OK] Initialized inventory for {len(inventory_db)} date/room combinations")


def get_restrictions(room_type_id: Optional[UUID] = None, restriction_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """Get all restrictions, optionally filtered by room_type_id and/or date"""
    restrictions = []
    for key, restriction in restrictions_db.items():
        rt_id, res_date, res_type = key
        if room_type_id and rt_id != room_type_id:
            continue
        if restriction_date and res_date != restriction_date:
            continue
        restrictions.append(restriction)
    return restrictions


def get_restrictions_for_room_type(room_type_id: UUID, restriction_date: Optional[date] = None) -> List[Dict[str, Any]]:
    """Get restrictions for a specific room type"""
    return get_restrictions(room_type_id=room_type_id, restriction_date=restriction_date)


def add_restriction(room_type_id: UUID, restriction_date: date, restriction_type: str, restriction_value: int) -> Dict[str, Any]:
    """Add or update a restriction"""
    key = (room_type_id, restriction_date, restriction_type)
    restriction = {
        "room_type_id": room_type_id,
        "date": restriction_date,
        "restriction_type": restriction_type,
        "restriction_value": restriction_value
    }
    restrictions_db[key] = restriction
    return restriction


def remove_restriction(room_type_id: UUID, restriction_date: date, restriction_type: str) -> bool:
    """Remove a restriction"""
    key = (room_type_id, restriction_date, restriction_type)
    if key in restrictions_db:
        del restrictions_db[key]
        return True
    return False
