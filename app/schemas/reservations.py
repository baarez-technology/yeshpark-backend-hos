from datetime import date, datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============== GUEST SCHEMAS ==============

class GuestCreate(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


class GuestRead(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


# ============== LEGACY RESERVATION SCHEMAS ==============

class ReservationCreate(BaseModel):
    guest: GuestCreate
    rate_plan_id: int
    arrival_date: date
    departure_date: date
    adults: int = 1
    children: int = 0
    special_requests: Optional[str] = None
    group_code: Optional[str] = None
    promo_code: Optional[str] = None
    room_id: Optional[int] = None  # For direct room assignment


class ReservationRead(BaseModel):
    id: int
    confirmation_code: str
    guest_id: int
    room_id: Optional[int] = None
    rate_plan_id: int
    arrival_date: date
    departure_date: date
    adults: int
    children: int
    status: str
    total_amount: float
    currency: str
    special_requests: Optional[str] = None
    group_code: Optional[str] = None


# ============== NEW BOOKING SCHEMAS (V2.0) ==============

class BookingBase(BaseModel):
    """Base booking schema with common fields"""
    room_type_id: int
    arrival_date: date
    departure_date: date
    adults: int = 1
    children: int = 0
    infants: int = 0
    special_requests: Optional[str] = None
    internal_notes: Optional[str] = None
    booking_source: Optional[str] = None
    channel: Optional[str] = None
    rate_plan_id: Optional[int] = None
    corporate_account_id: Optional[int] = None
    is_group_booking: bool = False
    group_booking_id: Optional[int] = None
    parent_booking_id: Optional[int] = None
    number_of_rooms: Optional[int] = None

    # VIP and guest tracking
    vip_flag: bool = False
    number_of_guests: Optional[int] = None

    # Upsells (JSONB)
    upsells: Optional[List[Dict[str, Any]]] = None

    # Discount tracking
    discount_code: Optional[str] = None
    discount_amount: float = 0.0

    # Commission and revenue tracking
    commission_rate: Optional[float] = None
    commission_amount: Optional[float] = None
    net_revenue: Optional[float] = None


class BookingCreate(BookingBase):
    """Schema for creating a new booking"""
    guest_id: int
    base_price: float
    taxes: float = 0.0
    service_fee: float = 0.0
    total_price: float
    deposit_amount: Optional[float] = None
    balance_due: Optional[float] = None
    room_id: Optional[int] = None


class BookingUpdate(BaseModel):
    """Schema for updating a booking - all fields optional"""
    room_id: Optional[int] = None
    room_type_id: Optional[int] = None
    arrival_date: Optional[date] = None
    departure_date: Optional[date] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    infants: Optional[int] = None
    status: Optional[str] = None
    payment_status: Optional[str] = None
    special_requests: Optional[str] = None
    internal_notes: Optional[str] = None
    base_price: Optional[float] = None
    taxes: Optional[float] = None
    service_fee: Optional[float] = None
    total_price: Optional[float] = None
    deposit_amount: Optional[float] = None
    balance_due: Optional[float] = None
    cancellation_reason: Optional[str] = None
    rate_plan_id: Optional[int] = None

    # VIP and guest tracking
    vip_flag: Optional[bool] = None
    number_of_guests: Optional[int] = None

    # Upsells (JSONB)
    upsells: Optional[List[Dict[str, Any]]] = None

    # Discount tracking
    discount_code: Optional[str] = None
    discount_amount: Optional[float] = None

    # Commission and revenue tracking
    commission_rate: Optional[float] = None
    commission_amount: Optional[float] = None
    net_revenue: Optional[float] = None


class BookingResponse(BaseModel):
    """Schema for booking API responses"""
    id: int
    booking_number: str
    confirmation_code: str
    user_id: Optional[int] = None
    guest_id: int
    room_type_id: int
    room_id: Optional[int] = None
    arrival_date: date
    departure_date: date
    check_in_date: Optional[datetime] = None
    check_out_date: Optional[datetime] = None
    adults: int
    children: int
    infants: int = 0
    nights: int
    status: str
    payment_status: str
    payment_method: Optional[str] = None
    booking_source: Optional[str] = None
    channel: Optional[str] = None
    base_price: float
    taxes: float
    service_fee: float
    total_price: float
    deposit_amount: Optional[float] = None
    balance_due: Optional[float] = None
    special_requests: Optional[str] = None
    internal_notes: Optional[str] = None
    cancellation_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    rate_plan_id: Optional[int] = None
    corporate_account_id: Optional[int] = None
    is_group_booking: bool = False
    group_booking_id: Optional[int] = None
    parent_booking_id: Optional[int] = None
    number_of_rooms: Optional[int] = None

    # VIP and guest tracking
    vip_flag: bool = False
    number_of_guests: Optional[int] = None

    # Upsells (JSONB)
    upsells: Optional[List[Dict[str, Any]]] = None

    # Discount tracking
    discount_code: Optional[str] = None
    discount_amount: float = 0.0

    # Commission and revenue tracking
    commission_rate: Optional[float] = None
    commission_amount: Optional[float] = None
    net_revenue: Optional[float] = None

    # Modification tracking
    modification_count: int = 0

    # Audit fields
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BookingListResponse(BaseModel):
    """Schema for paginated booking list responses"""
    items: List[BookingResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# ============== AVAILABILITY SCHEMAS ==============

class AvailabilityQuery(BaseModel):
    arrival_date: date
    departure_date: date
    adults: int = 1
    children: int = 0
    room_type: Optional[str] = None


class AvailableRoom(BaseModel):
    room_id: int
    number: str
    room_type: str
    price: float
    currency: str


class AvailabilityResponse(BaseModel):
    available_rooms: List[AvailableRoom] = Field(default_factory=list)


# ============== ROOM CHANGE HISTORY SCHEMAS ==============

class RoomChangeResponse(BaseModel):
    """Schema for a single room change record"""
    id: int
    reservation_id: int
    original_room_id: Optional[int] = None
    original_room_number: Optional[str] = None
    original_room_type_name: Optional[str] = None
    new_room_id: int
    new_room_number: str
    new_room_type_name: str
    change_type: str  # upgrade, downgrade, lateral, emergency_relocation
    reason_category: Optional[str] = None
    reason: Optional[str] = None
    price_adjustment: Optional[float] = None
    changed_by: Optional[int] = None
    changed_by_name: Optional[str] = None
    changed_at: datetime

    class Config:
        from_attributes = True


class BookingRoomChangesResponse(BaseModel):
    """Schema for all room changes of a specific booking"""
    booking_id: int
    confirmation_code: str
    total_room_changes: int
    room_changes: List[RoomChangeResponse]


class GuestRoomChangeHistoryResponse(BaseModel):
    """Schema for room change history across all guest bookings"""
    guest_id: int
    guest_name: str
    total_room_changes: int
    room_changes: List[RoomChangeResponse]


