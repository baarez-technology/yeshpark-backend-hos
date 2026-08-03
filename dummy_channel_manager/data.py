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
        name="Grand Plaza Hotel",
        address="123 Luxury Avenue",
        city="New York",
        country="USA",
        timezone="America/New_York",
        created_at=now
    )
    hotels_db[hotel1_id] = hotel1
    
    hotel2_id = uuid4()
    hotel2 = Hotel(
        id=hotel2_id,
        name="Oceanview Resort & Spa",
        address="456 Beach Boulevard",
        city="Miami",
        country="USA",
        timezone="America/New_York",
        created_at=now
    )
    hotels_db[hotel2_id] = hotel2
    
    hotel3_id = uuid4()
    hotel3 = Hotel(
        id=hotel3_id,
        name="Metropolitan Business Hotel",
        address="789 Downtown Street",
        city="San Francisco",
        country="USA",
        timezone="America/Los_Angeles",
        created_at=now
    )
    hotels_db[hotel3_id] = hotel3
    
    # Create Room Types for Hotel 1
    rt1_id = uuid4()
    rt1 = RoomType(
        id=rt1_id,
        hotel_id=hotel1_id,
        name="Standard King",
        description="Comfortable king-size bed with city view",
        max_occupancy=2,
        base_capacity=20
    )
    room_types_db[rt1_id] = rt1
    room_id_to_uuid_map[1] = rt1_id  # Map room_id 1 to this room type
    uuid_to_room_id_map[rt1_id] = 1
    
    rt2_id = uuid4()
    rt2 = RoomType(
        id=rt2_id,
        hotel_id=hotel1_id,
        name="Deluxe Suite",
        description="Spacious suite with living area and premium amenities",
        max_occupancy=4,
        base_capacity=10
    )
    room_types_db[rt2_id] = rt2
    room_id_to_uuid_map[2] = rt2_id
    uuid_to_room_id_map[rt2_id] = 2
    
    rt3_id = uuid4()
    rt3 = RoomType(
        id=rt3_id,
        hotel_id=hotel1_id,
        name="Executive King",
        description="Premium room with executive lounge access",
        max_occupancy=2,
        base_capacity=15
    )
    room_types_db[rt3_id] = rt3
    room_id_to_uuid_map[3] = rt3_id
    uuid_to_room_id_map[rt3_id] = 3
    
    # Create Room Types for Hotel 2
    rt4_id = uuid4()
    rt4 = RoomType(
        id=rt4_id,
        hotel_id=hotel2_id,
        name="Ocean View King",
        description="Stunning ocean view with balcony",
        max_occupancy=2,
        base_capacity=25
    )
    room_types_db[rt4_id] = rt4
    room_id_to_uuid_map[4] = rt4_id
    uuid_to_room_id_map[rt4_id] = 4
    
    rt5_id = uuid4()
    rt5 = RoomType(
        id=rt5_id,
        hotel_id=hotel2_id,
        name="Presidential Suite",
        description="Luxury suite with private terrace and butler service",
        max_occupancy=6,
        base_capacity=2
    )
    room_types_db[rt5_id] = rt5
    room_id_to_uuid_map[5] = rt5_id
    uuid_to_room_id_map[rt5_id] = 5
    
    # Create Room Types for Hotel 3
    rt6_id = uuid4()
    rt6 = RoomType(
        id=rt6_id,
        hotel_id=hotel3_id,
        name="Business Twin",
        description="Two twin beds with work desk and high-speed internet",
        max_occupancy=2,
        base_capacity=30
    )
    room_types_db[rt6_id] = rt6
    room_id_to_uuid_map[6] = rt6_id
    uuid_to_room_id_map[rt6_id] = 6
    
    # Create Rates
    # Hotel 1 - Standard King rates
    rate1_id = uuid4()
    rate1 = Rate(
        id=rate1_id,
        room_type_id=rt1_id,
        rate_plan=RatePlan.BAR,
        base_rate=12500.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.25,
        specific_dates={},
        created_at=now
    )
    rates_db[rate1_id] = rate1

    rate2_id = uuid4()
    rate2 = Rate(
        id=rate2_id,
        room_type_id=rt1_id,
        rate_plan=RatePlan.NON_REFUNDABLE,
        base_rate=10800.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.20,
        specific_dates={},
        created_at=now
    )
    rates_db[rate2_id] = rate2

    rate3_id = uuid4()
    rate3 = Rate(
        id=rate3_id,
        room_type_id=rt1_id,
        rate_plan=RatePlan.CORPORATE,
        base_rate=11600.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.0,
        specific_dates={},
        created_at=now
    )
    rates_db[rate3_id] = rate3

    # Hotel 1 - Deluxe Suite rates
    rate4_id = uuid4()
    rate4 = Rate(
        id=rate4_id,
        room_type_id=rt2_id,
        rate_plan=RatePlan.BAR,
        base_rate=29000.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.30,
        specific_dates={},
        created_at=now
    )
    rates_db[rate4_id] = rate4

    # Hotel 1 - Executive King rates
    rate5_id = uuid4()
    rate5 = Rate(
        id=rate5_id,
        room_type_id=rt3_id,
        rate_plan=RatePlan.BAR,
        base_rate=23000.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.25,
        specific_dates={},
        created_at=now
    )
    rates_db[rate5_id] = rate5

    # Hotel 2 - Ocean View King rates
    rate6_id = uuid4()
    rate6 = Rate(
        id=rate6_id,
        room_type_id=rt4_id,
        rate_plan=RatePlan.BAR,
        base_rate=20750.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.40,
        specific_dates={},
        created_at=now
    )
    rates_db[rate6_id] = rate6

    # Hotel 2 - Presidential Suite rates
    rate7_id = uuid4()
    rate7 = Rate(
        id=rate7_id,
        room_type_id=rt5_id,
        rate_plan=RatePlan.BAR,
        base_rate=99500.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.50,
        specific_dates={},
        created_at=now
    )
    rates_db[rate7_id] = rate7

    # Hotel 3 - Business Twin rates
    rate8_id = uuid4()
    rate8 = Rate(
        id=rate8_id,
        room_type_id=rt6_id,
        rate_plan=RatePlan.BAR,
        base_rate=15000.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.15,
        specific_dates={},
        created_at=now
    )
    rates_db[rate8_id] = rate8

    rate9_id = uuid4()
    rate9 = Rate(
        id=rate9_id,
        room_type_id=rt6_id,
        rate_plan=RatePlan.CORPORATE,
        base_rate=13300.0,
        currency="INR",
        start_date=None,
        end_date=None,
        weekday_multiplier=1.0,
        weekend_multiplier=1.0,
        specific_dates={},
        created_at=now
    )
    rates_db[rate9_id] = rate9
    
    # Initialize some inventory for next 90 days
    future_date = date.today() + timedelta(days=90)
    for room_type_id in [rt1_id, rt2_id, rt3_id, rt4_id, rt5_id, rt6_id]:
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
