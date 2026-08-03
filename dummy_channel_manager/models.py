"""
Pydantic models for CRS Simulator API
"""
from datetime import date, datetime
from enum import Enum
from typing import Optional, List, Dict, Any, Union
from pydantic import BaseModel, Field, validator
from uuid import UUID, uuid4


class RatePlan(str, Enum):
    """Rate plan types similar to real CRS systems"""
    BAR = "BAR"  # Best Available Rate
    NON_REFUNDABLE = "NON_REFUNDABLE"
    CORPORATE = "CORPORATE"
    PROMOTIONAL = "PROMOTIONAL"
    LONG_STAY = "LONG_STAY"


class BookingStatus(str, Enum):
    """Reservation status"""
    CONFIRMED = "CONFIRMED"
    MODIFIED = "MODIFIED"
    CANCELLED = "CANCELLED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"


class DayOfWeek(str, Enum):
    """Days of the week for rate calculations"""
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


# Hotel & Room Models
class RoomTypeBase(BaseModel):
    """Base room type model"""
    name: str = Field(..., description="Room type name (e.g., 'Deluxe King', 'Standard Twin')")
    description: Optional[str] = Field(None, description="Room type description")
    max_occupancy: int = Field(..., gt=0, description="Maximum occupancy for this room type")
    base_capacity: int = Field(..., gt=0, description="Total number of rooms of this type")


class RoomTypeCreate(RoomTypeBase):
    """Room type creation request"""
    pass


class RoomType(RoomTypeBase):
    """Room type with ID"""
    id: UUID
    hotel_id: UUID

    class Config:
        from_attributes = True


class HotelBase(BaseModel):
    """Base hotel model"""
    name: str = Field(..., description="Hotel name")
    address: Optional[str] = Field(None, description="Hotel address")
    city: Optional[str] = Field(None, description="Hotel city")
    country: Optional[str] = Field(None, description="Hotel country")
    timezone: str = Field(default="UTC", description="Hotel timezone")


class HotelCreate(HotelBase):
    """Hotel creation request"""
    pass


class Hotel(HotelBase):
    """Hotel with ID"""
    id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


# Rate Models
class RateBase(BaseModel):
    """Base rate model"""
    rate_plan: RatePlan = Field(..., description="Type of rate plan")
    base_rate: float = Field(..., gt=0, description="Base rate per night")
    currency: str = Field(default="INR", description="Currency code")


class RateCreate(RateBase):
    """Rate creation request"""
    room_type_id: UUID
    start_date: Optional[date] = Field(None, description="Rate start date (None = applies to all dates)")
    end_date: Optional[date] = Field(None, description="Rate end date (None = applies to all dates)")
    weekday_multiplier: Optional[float] = Field(default=1.0, ge=0, description="Multiplier for weekdays")
    weekend_multiplier: Optional[float] = Field(default=1.2, ge=0, description="Multiplier for weekends")
    specific_dates: Optional[Dict[date, float]] = Field(None, description="Date-specific rates override")


class Rate(RateBase):
    """Rate with ID"""
    id: UUID
    room_type_id: UUID
    start_date: Optional[date]
    end_date: Optional[date]
    weekday_multiplier: float
    weekend_multiplier: float
    specific_dates: Dict[date, float]
    created_at: datetime

    class Config:
        from_attributes = True


# Inventory Models
class Inventory(BaseModel):
    """Inventory model"""
    room_type_id: UUID
    date: date
    available: int = Field(..., ge=0, description="Available rooms")
    total: int = Field(..., gt=0, description="Total rooms")
    booked: int = Field(..., ge=0, description="Booked rooms")

    class Config:
        from_attributes = True


# Guest Information Model
class GuestInfo(BaseModel):
    """Guest information structure"""
    first_name: str = Field(..., description="Guest first name")
    last_name: str = Field(..., description="Guest last name")
    email: str = Field(..., description="Guest email")
    phone: Optional[str] = Field(None, description="Guest phone")
    notes: Optional[str] = Field(None, description="Guest notes")


# Reservation Models
class ReservationBase(BaseModel):
    """Base reservation model"""
    hotel_id: UUID
    room_type_id: UUID
    check_in: date = Field(..., description="Check-in date")
    check_out: date = Field(..., description="Check-out date")
    guest_name: str = Field(..., description="Guest name")
    guest_email: Optional[str] = Field(None, description="Guest email")
    guest_phone: Optional[str] = Field(None, description="Guest phone")
    number_of_guests: int = Field(..., gt=0, description="Number of guests")
    rate_plan: RatePlan = Field(..., description="Rate plan used")
    total_amount: float = Field(..., gt=0, description="Total booking amount")
    currency: str = Field(default="INR", description="Currency code")
    special_requests: Optional[str] = Field(None, description="Special requests")


class ReservationCreate(ReservationBase):
    """Reservation creation request (original format)"""
    pass


# New Reservation Format (for external application integration)
class ReservationCreateV2(BaseModel):
    """Reservation creation request - new format matching external application"""
    guest: GuestInfo = Field(..., description="Guest information")
    rate_plan_id: Union[int, str, UUID] = Field(..., description="Rate plan ID (int: 0-4) or UUID")
    arrival_date: date = Field(..., description="Arrival date")
    departure_date: date = Field(..., description="Departure date")
    adults: int = Field(..., gt=0, description="Number of adults")
    children: int = Field(default=0, ge=0, description="Number of children")
    special_requests: Optional[str] = Field(None, description="Special requests")
    group_code: Optional[str] = Field(None, description="Group code")
    promo_code: Optional[str] = Field(None, description="Promo code")
    room_id: Union[int, str, UUID] = Field(..., description="Room ID (int or UUID mapping to room_type_id)")
    hotel_id: Optional[Union[UUID, str]] = Field(None, description="Hotel ID (optional, can be inferred from room_id)")
    
    @validator('departure_date')
    def departure_after_arrival(cls, v, values):
        if 'arrival_date' in values and v <= values['arrival_date']:
            raise ValueError('departure_date must be after arrival_date')
        return v
    
    @validator('rate_plan_id', pre=True)
    def parse_rate_plan_id(cls, v):
        """Accept int, UUID string, or UUID object"""
        if isinstance(v, int):
            return v
        if isinstance(v, UUID):
            # If UUID, we'll need to look it up - for now, treat as invalid
            raise ValueError(f"rate_plan_id must be an integer (0-4), not UUID: {v}")
        if isinstance(v, str):
            # Try to parse as int first
            try:
                return int(v)
            except ValueError:
                # If not an int, it might be a UUID string - not supported for rate_plan_id
                raise ValueError(f"rate_plan_id must be an integer (0-4), got: {v}")
        return v
    
    @validator('room_id', pre=True)
    def parse_room_id(cls, v):
        """Accept int or UUID (string or object)"""
        if isinstance(v, int):
            return v
        if isinstance(v, UUID):
            return str(v)  # Convert UUID to string for lookup
        if isinstance(v, str):
            # Check if it's a valid UUID string
            try:
                UUID(v)
                return v  # Valid UUID string
            except ValueError:
                # Try to parse as int
                try:
                    return int(v)
                except ValueError:
                    raise ValueError(f"room_id must be an integer or valid UUID, got: {v}")
        return v
    
    @validator('hotel_id', pre=True)
    def parse_hotel_id(cls, v):
        """Accept UUID string or UUID object"""
        if v is None:
            return None
        if isinstance(v, UUID):
            return v
        if isinstance(v, str):
            try:
                return UUID(v)
            except ValueError:
                raise ValueError(f"hotel_id must be a valid UUID, got: {v}")
        return v


class ReservationModify(BaseModel):
    """Reservation modification request"""
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    guest_name: Optional[str] = None
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None
    number_of_guests: Optional[int] = Field(None, gt=0)
    special_requests: Optional[str] = None


class Reservation(ReservationBase):
    """Reservation with ID and confirmation number"""
    id: UUID
    confirmation_number: str = Field(..., description="CRS-style confirmation number")
    status: BookingStatus
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Availability & Rate Query Models
class AvailabilityRequest(BaseModel):
    """Availability query request"""
    hotel_id: UUID
    check_in: date
    check_out: date
    room_type_id: Optional[UUID] = None  # None = all room types
    rate_plan: Optional[RatePlan] = None  # None = all rate plans

    @validator('check_out')
    def check_out_after_check_in(cls, v, values):
        if 'check_in' in values and v <= values['check_in']:
            raise ValueError('check_out must be after check_in')
        return v


class RoomAvailability(BaseModel):
    """Room availability response"""
    room_type_id: UUID
    room_type_name: str
    available: int
    total: int
    rates: List[Dict[str, Any]] = Field(..., description="Available rates for this room type")

    class Config:
        from_attributes = True


class AvailabilityResponse(BaseModel):
    """Availability response"""
    hotel_id: UUID
    hotel_name: str
    check_in: date
    check_out: date
    nights: int
    rooms: List[RoomAvailability]
    metadata: Dict[str, Any] = Field(default_factory=dict, description="AI-friendly metadata")

    class Config:
        from_attributes = True


# Rate Update Models
class RateUpdateRequest(BaseModel):
    """Rate update request"""
    room_type_id: UUID
    rate_plan: RatePlan
    dates: List[date]
    amount: float = Field(..., gt=0)
    currency: str = Field(default="INR")


class RateUpdateResponse(BaseModel):
    """Rate update response"""
    success: bool
    updated_dates: List[date]
    failed_dates: List[date]
    message: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


# Webhook Models
class WebhookEvent(str, Enum):
    """Webhook event types"""
    BOOKING_CREATED = "booking.created"
    BOOKING_MODIFIED = "booking.modified"
    BOOKING_CANCELLED = "booking.cancelled"
    AVAILABILITY_UPDATED = "availability.updated"
    RATES_UPDATED = "rates.updated"
    RESTRICTIONS_UPDATED = "restrictions.updated"
    SYNC_STATUS = "sync.status"


# Webhook Payload Models
class GuestInfo(BaseModel):
    """Guest information for webhooks"""
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    country: Optional[str] = None
    nationality: Optional[str] = None
    date_of_birth: Optional[date] = None
    passport_number: Optional[str] = None


class BookingPricing(BaseModel):
    """Pricing information for bookings"""
    base_price: float
    taxes: float = 0.0
    service_fee: float = 0.0
    total_price: float
    currency: str = "INR"
    commission_rate: Optional[float] = None
    commission_amount: Optional[float] = None
    net_revenue: Optional[float] = None


class BookingPayment(BaseModel):
    """Payment information for bookings"""
    payment_status: str = "pending"  # pending, paid, partial, failed, refunded
    payment_method: str = "card"  # card, pay_at_hotel
    deposit_amount: float = 0.0
    balance_due: float = 0.0


class BookingWebhookPayload(BaseModel):
    """Booking webhook payload"""
    guest: GuestInfo
    room_type_code: str
    rate_plan_code: str
    arrival_date: date
    departure_date: date
    adults: int = 1
    children: int = 0
    infants: int = 0
    special_requests: Optional[str] = None
    pricing: BookingPricing
    payment: BookingPayment


class BookingCreatedPayload(BaseModel):
    """Webhook payload for booking.created"""
    event_type: str = "booking.created"
    ota_connection_id: int
    ota_code: str  # BOOKING, EXPEDIA, AGODA, AIRBNB
    external_booking_id: str
    timestamp: datetime
    booking: BookingWebhookPayload


class BookingModifiedPayload(BaseModel):
    """Webhook payload for booking.modified"""
    event_type: str = "booking.modified"
    ota_connection_id: int
    external_booking_id: str
    timestamp: datetime
    changes: Optional[Dict[str, Any]] = None
    booking: BookingWebhookPayload


class BookingCancelledPayload(BaseModel):
    """Webhook payload for booking.cancelled"""
    event_type: str = "booking.cancelled"
    ota_connection_id: int
    external_booking_id: str
    timestamp: datetime
    cancellation_reason: Optional[str] = None
    refund_status: Optional[str] = None  # processed, pending, declined


class AvailabilityItem(BaseModel):
    """Availability item for availability.updated"""
    room_type_code: str
    date: date
    available: int
    sold: int
    blocked: int
    total: int


class AvailabilityUpdatedPayload(BaseModel):
    """Webhook payload for availability.updated"""
    event_type: str = "availability.updated"
    ota_connection_id: int
    timestamp: datetime
    availability: List[AvailabilityItem]


class RateItem(BaseModel):
    """Rate item for rates.updated"""
    room_type_code: str
    rate_plan_code: str
    date: date
    rate: float
    currency: str = "INR"


class RatesUpdatedPayload(BaseModel):
    """Webhook payload for rates.updated"""
    event_type: str = "rates.updated"
    ota_connection_id: int
    timestamp: datetime
    rates: List[RateItem]


class RestrictionItem(BaseModel):
    """Restriction item for restrictions.updated"""
    room_type_code: str
    date: date
    restriction_type: str  # stop_sell, CTA, CTD, min_stay, max_stay
    restriction_value: int


class RestrictionsUpdatedPayload(BaseModel):
    """Webhook payload for restrictions.updated"""
    event_type: str = "restrictions.updated"
    ota_connection_id: int
    timestamp: datetime
    restrictions: List[RestrictionItem]


class SyncStatusPayload(BaseModel):
    """Webhook payload for sync.status"""
    event_type: str = "sync.status"
    ota_connection_id: int
    timestamp: datetime
    status: Dict[str, Any]  # connection_status, last_sync_at, sync_type, records_processed, etc.


# Legacy WebhookPayload for backward compatibility
class WebhookPayload(BaseModel):
    """Legacy webhook payload structure (backward compatible)"""
    event: WebhookEvent
    timestamp: datetime
    reservation_id: UUID
    confirmation_number: str
    hotel_id: UUID
    room_type_id: UUID
    check_in: date
    check_out: date
    status: BookingStatus
    data: Dict[str, Any] = Field(default_factory=dict, description="Additional event data")

    class Config:
        from_attributes = True


# AI-Friendly Response Models
class AIResponse(BaseModel):
    """Base AI-friendly response"""
    success: bool
    data: Any
    metadata: Dict[str, Any] = Field(
        default_factory=lambda: {
            "source": "simulator",
            "confidence": "high",
            "timestamp": datetime.now().isoformat()
        }
    )
    message: Optional[str] = None
    errors: Optional[List[str]] = None

    class Config:
        from_attributes = True


# Error Models
class ErrorResponse(BaseModel):
    """Standard error response"""
    success: bool = False
    error_code: str
    error_message: str
    details: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(
        default_factory=lambda: {
            "source": "simulator",
            "timestamp": datetime.now().isoformat()
        }
    )
