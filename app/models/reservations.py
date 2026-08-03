from datetime import datetime, date
from datetime import date as date_type
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import JSON
from app.models.base import TimestampedModel


class Guest(SQLModel, table=True):
    __tablename__ = "guests"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    first_name: str
    last_name: str
    email: Optional[str] = Field(default=None, index=True)
    phone: Optional[str] = None
    date_of_birth: Optional[date_type] = None
    nationality: Optional[str] = None
    passport_number: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None  # *** NEW: State/Province ***
    country: Optional[str] = Field(default=None, index=True)
    postal_code: Optional[str] = None
    avatar: Optional[str] = None  # *** NEW: Profile picture URL ***
    status: str = Field(default="Active", index=True)  # *** NEW: Active, Inactive, VIP, Blacklisted, vip, normal, review, blacklisted ***
    emotion: str = Field(default="neutral", index=True)  # *** NEW: happy, neutral, unhappy, positive, negative ***
    loyalty_points: int = Field(default=0)
    loyalty_tier: Optional[str] = Field(default=None, index=True)  # bronze, silver, gold, platinum, member
    total_bookings: int = Field(default=0)
    total_spent: float = Field(default=0.0)
    total_nights: int = Field(default=0)
    vip_status: bool = Field(default=False, index=True)
    vip_level: Optional[int] = Field(default=None, index=True)  # 1-5, None = not VIP
    profile_number: Optional[str] = Field(default=None, unique=True, index=True)  # Auto-generated GP-NNNNNN
    preferred_room_type: Optional[str] = Field(default=None, index=True)  # *** NEW: suite, deluxe, standard ***
    member_since: Optional[datetime] = None
    last_visit: Optional[datetime] = Field(default=None, index=True)
    preferences: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB: {bedType, floor, allergies, notes, roomType, temperature, pillow, minibar, etc.}
    notes: Optional[str] = Field(default=None, sa_column=Column(JSON))  # *** UPDATED: Array of note objects [{id, text, author, date}] instead of TEXT ***
    tags: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB: Array of tags (vip, corporate, leisure, family, frequent, long-stay, etc.)
    booking_source: Optional[str] = None
    id_type: Optional[str] = None  # passport, drivers_license, national_id
    id_number: Optional[str] = None
    id_verified: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# *** NEW: Booking model (replaces Reservation in V2.0 schema) ***
class Booking(SQLModel, table=True):
    """Main booking table - renamed from reservations in V2.0"""
    __tablename__ = "bookings"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    booking_number: str = Field(unique=True, nullable=False, index=True)
    confirmation_code: str = Field(index=True, unique=True, nullable=False)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id")
    guest_id: int = Field(foreign_key="guests.id", index=True, nullable=False)
    room_type_id: int = Field(foreign_key="room_types.id", nullable=False)
    room_id: Optional[int] = Field(default=None, foreign_key="rooms.id", index=True)
    arrival_date: date_type = Field(index=True, nullable=False)
    departure_date: date_type = Field(index=True, nullable=False)
    check_in_date: Optional[datetime] = None
    check_out_date: Optional[datetime] = None
    adults: int = Field(default=1, nullable=False)
    children: int = Field(default=0)
    infants: int = Field(default=0)
    nights: int = Field(nullable=False)
    status: str = Field(default="pending", index=True, nullable=False)  # pending, confirmed, checked_in, checked_out, cancelled, no_show
    payment_status: str = Field(default="pending", nullable=False)  # pending, paid, partial, failed, refunded
    payment_method: Optional[str] = Field(default="card")  # card, pay_at_hotel
    booking_source: Optional[str] = Field(default="Direct", index=True)  # Direct, Booking.com, Expedia, Walk-in, Corporate Portal, etc.
    channel: Optional[str] = None
    base_price: float = Field(nullable=False)
    nightly_rate: Optional[float] = Field(default=None)  # Per-night rate stored at booking time
    tax_rate: Optional[float] = Field(default=None)  # Tax rate applied (0.12 or 0.18)
    taxes: float = Field(nullable=False)
    service_fee: float = Field(nullable=False)
    total_price: float = Field(nullable=False)
    deposit_amount: Optional[float] = None
    balance_due: Optional[float] = None
    special_requests: Optional[str] = None
    internal_notes: Optional[str] = None
    cancellation_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    rate_plan_id: Optional[int] = None
    corporate_account_id: Optional[int] = None
    is_group_booking: bool = Field(default=False)
    group_booking_id: Optional[int] = None
    number_of_rooms: int = Field(default=1)  # Multi-room booking: N linked bookings
    parent_booking_id: Optional[int] = Field(default=None, foreign_key="bookings.id", index=True)

    # Central Booking System enhancements
    vip_flag: bool = Field(default=False, index=True)  # VIP guest indicator
    number_of_guests: Optional[int] = Field(default=None)  # Total guest count
    expected_arrival_time: Optional[str] = None  # HH:MM format (e.g. "14:00")
    expected_departure_time: Optional[str] = None  # HH:MM format (e.g. "11:00")
    accompanying_guests: Optional[str] = Field(default=None, sa_column=Column(JSON))  # [{name, relation, id_type, id_number}]

    # Upsells and add-ons (JSONB)
    # Format: [{"item": "breakfast", "price": 25.00, "quantity": 2}, {"item": "spa", "price": 150.00}]
    upsells: Optional[str] = Field(default=None, sa_column=Column(JSON))

    # Discount/Promo tracking
    discount_code: Optional[str] = Field(default=None, index=True)  # Applied promo code
    discount_amount: float = Field(default=0.0)  # Total discount applied

    # Commission and revenue tracking
    commission_rate: Optional[float] = Field(default=None)  # Channel commission percentage
    commission_amount: Optional[float] = Field(default=None)  # Calculated commission
    net_revenue: Optional[float] = Field(default=None)  # Revenue after commission

    # Modification tracking
    modification_count: int = Field(default=0)  # Number of modifications made

    # DNM (Do Not Move) — locks room assignment so other staff cannot change it
    do_not_move: bool = Field(default=False)
    dnm_set_by: Optional[int] = Field(default=None, foreign_key="users.id")
    dnm_set_at: Optional[datetime] = None

    # Audit fields
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True, nullable=False)
    updated_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


# *** OLD: Legacy Reservation model - kept for backward compatibility during migration ***
class Reservation(SQLModel, table=True):
    """LEGACY: Use Booking model instead. Kept for backward compatibility."""
    id: Optional[int] = Field(default=None, primary_key=True)
    confirmation_code: str = Field(index=True, unique=True)
    guest_id: int = Field(foreign_key="guests.id", index=True)
    room_id: Optional[int] = Field(default=None, foreign_key="rooms.id", index=True)
    room_type_id: Optional[int] = Field(default=None, foreign_key="room_types.id", index=True)
    rate_plan_id: int = Field(foreign_key="rateplan.id")
    arrival_date: date_type = Field(index=True)
    departure_date: date_type = Field(index=True)
    adults: int = 1
    children: int = 0
    status: str = Field(default="booked", index=True)  # booked, checked_in, checked_out, cancelled, no_show
    total_amount: float = 0.0
    currency: str = "INR"
    special_requests: Optional[str] = None
    group_code: Optional[str] = Field(default=None, index=True)
    overbooked_flag: bool = False
    waitlist_flag: bool = False
    promo_code: Optional[str] = None
    booking_source: str = "direct"  # direct, ota, phone, walk_in
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[int] = Field(default=None, foreign_key="users.id")
    cancellation_reason: Optional[str] = None


class ReservationHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    reservation_id: int = Field(foreign_key="reservation.id", index=True)
    action: str  # created, modified, cancelled, checked_in, checked_out, room_changed, rate_changed
    changed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class ReservationNote(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    reservation_id: int = Field(foreign_key="reservation.id", index=True)
    note: str
    note_type: str = "general"  # general, special_request, complaint, compliment, internal
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    is_internal: bool = False  # Internal notes not visible to guests
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class Waitlist(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True)
    arrival_date: date_type = Field(index=True)
    departure_date: date_type = Field(index=True)
    adults: int = 1
    children: int = 0
    room_type_preference: Optional[str] = None
    rate_plan_id: Optional[int] = Field(default=None, foreign_key="rateplan.id")
    status: str = Field(default="active", index=True)  # active, converted, cancelled
    priority: int = 0  # Higher number = higher priority
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    converted_at: Optional[datetime] = None
    converted_to_reservation_id: Optional[int] = Field(default=None, foreign_key="reservation.id")


class AccompanyingGuest(SQLModel, table=True):
    """Additional guests sharing a room (E-04/05/06)."""
    __tablename__ = "accompanyingguest"

    id: Optional[int] = Field(default=None, primary_key=True)
    booking_id: int = Field(foreign_key="bookings.id", index=True)
    guest_type: str = Field(default="adult")  # adult, child
    full_name: str
    relation: Optional[str] = None  # spouse, colleague, child, friend
    age: Optional[int] = None
    id_type: Optional[str] = None  # passport, drivers_license, national_id
    id_number: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GroupBooking(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    group_code: str = Field(index=True, unique=True)
    group_name: str
    contact_guest_id: int = Field(foreign_key="guests.id")
    arrival_date: date_type = Field(index=True)
    departure_date: date_type = Field(index=True)
    room_block: int = 0  # Number of rooms blocked
    rate_plan_id: int = Field(foreign_key="rateplan.id")
    total_amount: float = 0.0
    currency: str = "INR"
    status: str = Field(default="active", index=True)  # active, confirmed, cancelled
    notes: Optional[str] = None
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


