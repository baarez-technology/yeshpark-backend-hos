import json
import logging
from typing import Dict, List, Optional, Tuple, Union
import pytz

logger = logging.getLogger(__name__)
from datetime import date, datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks

# IST timezone for India
IST = pytz.timezone('Asia/Kolkata')

def get_ist_now() -> datetime:
    """Get current time in IST (India Standard Time)"""
    return datetime.now(IST).replace(tzinfo=None)  # Remove tzinfo for naive datetime storage

from sqlmodel import select, and_, func
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.api.v1.webhooks import broadcast_sse_event
from app.models.reservations import Reservation, Booking, Guest, ReservationHistory
from app.models.inventory import Room, RoomType, RatePlan
from app.models.user import User
from app.schemas.reservations import ReservationCreate
from app.services.reservation_service import (
    create_reservation, update_reservation, cancel_reservation,
    compute_total, create_guest
)
from app.core.business_date import get_business_date
from app.core.tax import apply_tax_to_line_item
from app.services.billing_engine import calculate_stay_charges, StayCharges


async def get_default_rate_plan_id(session: AsyncSession) -> int:
    """Get the default BAR (Best Available Rate) rate plan ID for the current tenant."""
    # Try to find BAR rate plan first
    result = await session.exec(
        select(RatePlan).where(
            and_(RatePlan.plan_type == "BAR", RatePlan.is_active == True)
        )
    )
    rate_plan = result.first()

    if rate_plan:
        return rate_plan.id

    # Fallback: get any active rate plan
    result = await session.exec(
        select(RatePlan).where(RatePlan.is_active == True)
    )
    rate_plan = result.first()

    if rate_plan:
        return rate_plan.id

    # No rate plans exist - this shouldn't happen in a properly seeded database
    raise HTTPException(
        status_code=500,
        detail="No rate plans configured. Please contact administrator."
    )
from app.services.admin_notification_service import (
    notify_new_booking, notify_booking_cancelled, notify_guest_checkin, notify_guest_checkout
)

router = APIRouter()

# Booking source display map - maps internal source codes to frontend display names.
# Keys should be lowercase; lookup is case-insensitive via .lower().
BOOKING_SOURCE_MAP = {
    "direct": "Direct",
    "website": "Website",
    "ota": "OTA",
    "phone": "Phone",
    "walk_in": "Walk-in",
    "walk-in": "Walk-in",
    "walkin": "Walk-in",
    "booking.com": "Booking.com",
    "booking_com": "Booking.com",
    "expedia": "Expedia",
    "agoda": "Agoda",
    "airbnb": "Airbnb",
    "makemytrip": "MakeMyTrip",
    "corporate portal": "Corporate Portal",
    "corporate_portal": "Corporate Portal",
    "dummy": "Dummy Channel Manager",
    "crs": "Dummy Channel Manager",
}


def resolve_booking_source(raw_source: Optional[str]) -> str:
    """Resolve a raw booking source string to its frontend display name."""
    key = (raw_source or "direct").lower()
    return BOOKING_SOURCE_MAP.get(key, raw_source or "Direct")


def deduplicate_bookings(all_bookings: List[Booking]) -> List[Booking]:
    """
    Single deduplication layer after processing: remove duplicate booking rows.
    Order: 1) by id, 2) by (external_booking_id, ota_connection_id), 3) by (guest_id, arrival, departure, total).
    """
    def _external_key(b: Booking) -> Optional[Tuple[str, int]]:
        if not b.internal_notes:
            return None
        try:
            data = json.loads(b.internal_notes) if isinstance(b.internal_notes, str) else b.internal_notes
            if not isinstance(data, dict):
                return None
            ext = data.get("external_booking_id")
            ota = data.get("ota_connection_id")
            if ext is not None and ota is not None:
                return (str(ext), int(ota))
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        return None

    def _content_key(b: Booking) -> Tuple[int, date, date, float, Optional[int]]:
        total = round(float(b.total_price or 0), 2)
        arr = b.arrival_date.date() if hasattr(b.arrival_date, "date") else b.arrival_date
        dep = b.departure_date.date() if hasattr(b.departure_date, "date") else b.departure_date
        # Include parent_booking_id to distinguish parent from child in group bookings
        return (b.guest_id, arr, dep, total, b.parent_booking_id)

    seen_ids: set = set()
    seen_external: set = set()
    seen_content: set = set()
    deduped = []
    for b in all_bookings:
        if b.id and b.id in seen_ids:
            continue
        if b.id:
            seen_ids.add(b.id)
        ext_key = _external_key(b)
        if ext_key and ext_key in seen_external:
            continue
        if ext_key:
            seen_external.add(ext_key)
        content_key = _content_key(b)
        if content_key in seen_content:
            continue
        seen_content.add(content_key)
        deduped.append(b)
    return deduped


class GuestInfo(BaseModel):
    firstName: str
    lastName: str
    email: str
    phone: str
    country: str
    specialRequests: Optional[str] = None

    class Config:
        # Allow validation even if some fields might be empty strings
        validate_assignment = True


class RoomSelection(BaseModel):
    """Room selection for multi-room bookings.
    Uses snake_case to match existing multi_room.py convention.
    """
    room_type_id: int
    adults: int = 1
    children: int = 0
    special_requests: Optional[str] = None
    # Pricing fields (optional - backend will calculate if not provided)
    rate_per_night: Optional[float] = None
    subtotal: Optional[float] = None
    taxes: Optional[float] = None
    total: Optional[float] = None


class CreateBookingRequest(BaseModel):
    roomId: Optional[str] = None  # Made optional for multi-room bookings
    checkIn: str
    checkOut: str
    guests: dict  # { adults: int, children: int, infants: int }
    guestInfo: GuestInfo
    paymentMethodId: Optional[str] = None
    saveCard: Optional[bool] = False
    paymentMethod: Optional[str] = "card"  # "card" or "pay_at_hotel"
    source: Optional[str] = None  # Booking source (Website, Walk-in, Booking.com, Dummy Channel Manager, etc.)
    channel: Optional[str] = None  # Channel name (e.g. "Dummy Channel Manager") - takes precedence over source
    # Sprint 6 fields
    roomTypeId: Optional[int] = None
    basePrice: Optional[float] = None
    taxes: Optional[float] = None  # GST amount
    serviceFee: Optional[float] = None  # Service fee amount
    totalPrice: Optional[float] = None  # Total price including all fees
    ratePerNight: Optional[float] = None  # Rate per night for display
    depositAmount: Optional[float] = None
    expectedArrivalTime: Optional[str] = None  # HH:MM
    expectedDepartureTime: Optional[str] = None  # HH:MM
    accompanyingGuests: Optional[list] = None  # [{name, relation, age, id_type, id_number}]
    corporateAccountId: Optional[int] = None  # Link booking to corporate account at creation
    vipStatus: Optional[bool] = None  # Mark guest as VIP at booking time
    ratePlan: Optional[str] = None  # Rate plan name (BAR, Corporate, OTA, Long Stay)
    # Multi-room booking support
    rooms: Optional[List[RoomSelection]] = None  # For multi-room bookings


class BookingResponse(BaseModel):
    id: str
    bookingNumber: str
    userId: str
    guestId: Optional[int] = None
    room: dict
    checkIn: str
    checkOut: str
    guests: dict
    guestInfo: GuestInfo
    nights: int
    basePrice: float
    taxes: float
    serviceFee: float
    totalPrice: float
    ratePerNight: Optional[float] = None  # For billing calculations
    status: str
    paymentStatus: str
    paymentMethod: str
    createdAt: str
    updatedAt: str
    vipStatus: bool = False
    bookingSource: str = "direct"
    doNotMove: bool = False
    dnmSetBy: Optional[int] = None
    dnmSetByName: Optional[str] = None
    dnmSetAt: Optional[str] = None
    amountPaid: float = 0.0
    balanceDue: float = 0.0
    depositAmount: Optional[float] = None  # Alias for amountPaid for frontend compat
    checkedInAt: Optional[str] = None
    checkedOutAt: Optional[str] = None
    # Sprint 6 fields
    expectedArrivalTime: Optional[str] = None
    expectedDepartureTime: Optional[str] = None
    accompanyingGuests: Optional[list] = None
    vipLevel: Optional[int] = None
    guestProfileNumber: Optional[str] = None
    arrivalDate: Optional[str] = None  # raw date for frontend filtering
    departureDate: Optional[str] = None
    roomNumber: Optional[str] = None
    roomId: Optional[int] = None  # Direct room ID for easy access
    roomType: Optional[str] = None
    roomTypeId: Optional[int] = None
    corporateAccountId: Optional[int] = None
    corporateAccountName: Optional[str] = None
    # Duplicate-email advisory (non-blocking)
    guestEmailDuplicateMessage: Optional[str] = None
    # Group booking fields
    isGroupBooking: bool = False
    groupBookingId: Optional[int] = None
    parentBookingId: Optional[int] = None
    numberOfRooms: Optional[int] = None

    class Config:
        from_attributes = True


class BookingListResponse(BaseModel):
    items: List[BookingResponse]
    total: int
    page: int
    pageSize: int
    totalPages: int


class MultiRoomBookingItem(BaseModel):
    """Individual booking in a multi-room response"""
    id: int
    bookingNumber: str
    roomTypeId: int
    roomTypeName: str
    isParent: bool
    adults: int
    children: int
    basePrice: float
    taxes: float
    totalPrice: float


class MultiRoomBookingResponse(BaseModel):
    """Response for multi-room booking creation"""
    message: str
    groupBookingId: int
    parentBookingId: int
    totalPrice: float
    bookings: List[MultiRoomBookingItem]


async def reservation_to_booking_response(reservation: Reservation, guest: Guest, room: Optional[Room] = None, session: Optional[AsyncSession] = None, room_type: Optional[RoomType] = None) -> BookingResponse:
    """Convert backend Reservation to frontend Booking format"""
    from app.core.tax import get_room_tax_rate

    nights = (reservation.departure_date - reservation.arrival_date).days

    # Calculate pricing - determine tax rate based on room type base price
    per_night_rate = 0.0
    if room_type:
        per_night_rate = room_type.base_price or 0.0
    elif reservation.room_type_id and session:
        rt = await session.get(RoomType, reservation.room_type_id)
        if rt:
            per_night_rate = rt.base_price or 0.0

    tax_rate = get_room_tax_rate(per_night_rate) if per_night_rate > 0 else 0.12
    total_markup = tax_rate  # tax only, no service fee

    base_price = reservation.total_amount / (1 + total_markup)
    taxes = base_price * tax_rate
    service_fee = 0.0  # Service fee removed
    total_price = reservation.total_amount

    # Get room type - try multiple sources in order of preference
    room_type_obj = room_type
    room_type_name = "Standard Room"

    if room_type_obj:
        room_type_name = room_type_obj.name
    elif reservation.room_type_id and session:
        # Get from room_type_id on reservation
        room_type_obj = await session.get(RoomType, reservation.room_type_id)
        if room_type_obj:
            room_type_name = room_type_obj.name
    elif room and session:
        # Get from room's room_type_id
        room_type_obj = await session.get(RoomType, room.room_type_id)
        if room_type_obj:
            room_type_name = room_type_obj.name

    # Calculate VIP status from guest's total spending
    vip_status = False
    if session:
        from sqlmodel import select
        try:
            guest_bookings_result = await session.exec(select(Reservation).where(Reservation.guest_id == guest.id))
            guest_bookings = guest_bookings_result.all()
            if guest_bookings:
                total_spent = sum(b.total_amount for b in guest_bookings)
                loyalty_points = int(total_spent * 0.1)  # 10% of spending
                vip_status = loyalty_points > 2000
        except Exception:
            vip_status = False
    
    booking_source = resolve_booking_source(reservation.booking_source)

    # Map status to frontend format
    status_map = {
        "booked": "confirmed",
        "confirmed": "confirmed",
        "checked_in": "checked-in",
        "checked_out": "checked-out",
        "completed": "checked-out",
        "cancelled": "cancelled",
        "no_show": "no-show"
    }
    frontend_status = status_map.get(reservation.status, "confirmed")
    
    # Room data - build from room if assigned, else from room_type
    import json
    room_data = {}

    if room:
        # Room is assigned - use room details
        amenities = []
        images = []

        if room.amenities:
            try:
                amenities = json.loads(room.amenities) if isinstance(room.amenities, str) else room.amenities
            except:
                amenities = room.amenities.split(',') if isinstance(room.amenities, str) else []

        if room.images:
            try:
                images = json.loads(room.images) if isinstance(room.images, str) else room.images
            except:
                images = [room.images] if isinstance(room.images, str) else []

        # Use room type slug for navigation (not combined with room number)
        # This ensures the frontend can fetch the room type correctly
        slug = room_type_name.lower().replace(' ', '-')

        room_data = {
            "id": str(room.id),
            "name": f"{room_type_name} {room.number}",
            "number": str(room.number),
            "slug": slug,
            "description": f"Beautiful {room_type_name} room",
            "price": base_price / nights if nights > 0 else base_price,
            "images": images,
            "amenities": amenities,
            "maxGuests": room.max_occupancy,
            "bedType": room.bed_type or "King",
            "size": room.size_sqft or 300,
            "view": room.view_type or "City"
        }
    elif room_type_obj:
        # No room assigned yet - use room type info
        amenities = []
        images = []

        if room_type_obj.amenities:
            try:
                amenities = json.loads(room_type_obj.amenities) if isinstance(room_type_obj.amenities, str) else room_type_obj.amenities
            except:
                amenities = []

        if room_type_obj.images:
            try:
                images = json.loads(room_type_obj.images) if isinstance(room_type_obj.images, str) else room_type_obj.images
            except:
                images = []

        slug = room_type_obj.slug if room_type_obj.slug else room_type_name.lower().replace(' ', '-')

        room_data = {
            "id": str(room_type_obj.id),
            "name": room_type_name,
            "number": None,  # No room number assigned yet
            "slug": slug,
            "description": room_type_obj.description or f"Beautiful {room_type_name}",
            "price": base_price / nights if nights > 0 else base_price,
            "images": images,
            "amenities": amenities,
            "maxGuests": room_type_obj.max_guests,
            "bedType": room_type_obj.bed_type or "King",
            "size": room_type_obj.size_sqft or 300,
            "view": room_type_obj.view_type or "City"
        }
    
    # Compute payment amounts — deposit_amount is the actual money received
    # (kept in sync with folio payments by folio.sync_booking_payment).
    # Payment status is derived from that money, never from the stay status:
    # a guest can be checked in and still owe the full balance.
    res_deposit = getattr(reservation, 'deposit_amount', None) or 0.0
    res_amount_paid = res_deposit
    res_balance_due = max(0.0, round(total_price - res_amount_paid, 2))
    if res_amount_paid <= 0.0:
        res_payment_status = "pending"
    elif res_balance_due <= 0.0:
        res_payment_status = "paid"
    else:
        res_payment_status = "partial"

    return BookingResponse(
        id=str(reservation.id),
        bookingNumber=reservation.confirmation_code,
        userId=str(reservation.created_by) if reservation.created_by else "",
        guestId=guest.id,
        room=room_data,
        checkIn=reservation.arrival_date.isoformat(),
        checkOut=reservation.departure_date.isoformat(),
        guests={
            "adults": reservation.adults,
            "children": reservation.children,
            "infants": 0  # Backend doesn't track infants separately
        },
        guestInfo=GuestInfo(
            firstName=guest.first_name,
            lastName=guest.last_name,
            email=guest.email or "",
            phone=guest.phone or "",
            country=guest.country or "",
            specialRequests=reservation.special_requests
        ),
        nights=nights,
        basePrice=base_price,
        taxes=taxes,
        serviceFee=service_fee,
        totalPrice=total_price,
        status=frontend_status,
        paymentStatus=res_payment_status,
        paymentMethod="card",
        createdAt=reservation.created_at.isoformat(),
        updatedAt=reservation.updated_at.isoformat(),
        vipStatus=vip_status,
        bookingSource=booking_source,
        doNotMove=False,
        dnmSetBy=None,
        amountPaid=res_amount_paid,
        balanceDue=res_balance_due,
        checkedInAt=reservation.check_in_date.isoformat() if reservation.check_in_date else None,
        checkedOutAt=reservation.check_out_date.isoformat() if reservation.check_out_date else None
    )


async def booking_to_response(booking: Booking, guest: Guest, room: Optional[Room] = None, session: Optional[AsyncSession] = None) -> BookingResponse:
    """Convert Booking model to frontend BookingResponse format"""
    import json

    nights = booking.nights or (booking.departure_date - booking.arrival_date).days

    # Booking model already has pricing breakdown
    base_price = booking.base_price or 0
    taxes = booking.taxes or 0
    service_fee = 0  # Service fee removed — always 0
    # Always derive total from components to prevent stale mismatches
    total_price = round(base_price + taxes, 2) if base_price > 0 else (booking.total_price or 0)

    # Get room type
    room_type_obj = None
    room_type_name = "Standard Room"

    if booking.room_type_id and session:
        room_type_obj = await session.get(RoomType, booking.room_type_id)
        if room_type_obj:
            room_type_name = room_type_obj.name

    # Check internal_notes first - webhook bookings store ota_code; if DUMMY/CRS, always use Dummy Channel Manager
    ota_code_from_notes = None
    if booking.internal_notes:
        try:
            data = json.loads(booking.internal_notes) if isinstance(booking.internal_notes, str) else booking.internal_notes
            if isinstance(data, dict):
                ota_code_from_notes = (data.get("ota_code") or data.get("otaCode") or "").upper()
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    if ota_code_from_notes in ("DUMMY", "CRS"):
        booking_source = "Dummy Channel Manager"
    else:
        # Use channel if available (e.g. from webhook), otherwise map the source
        booking_source = booking.channel or resolve_booking_source(booking.booking_source)

    # Map status to frontend format
    status_map = {
        "pending": "confirmed",
        "confirmed": "confirmed",
        "checked_in": "checked-in",
        "checked_out": "checked-out",
        "cancelled": "cancelled",
        "no_show": "no-show"
    }
    frontend_status = status_map.get(booking.status, "confirmed")

    # Room data
    room_data = {}
    if room:
        amenities = []
        images = []
        if room.amenities:
            try:
                amenities = json.loads(room.amenities) if isinstance(room.amenities, str) else room.amenities
            except:
                amenities = []
        if room.images:
            try:
                images = json.loads(room.images) if isinstance(room.images, str) else room.images
            except:
                images = []

        # Use room type slug for navigation (not combined with room number)
        # This ensures the frontend can fetch the room type correctly
        slug = room_type_name.lower().replace(' ', '-')
        room_data = {
            "id": str(room.id),
            "name": f"{room_type_name} {room.number}",
            "number": str(room.number),
            "slug": slug,
            "description": f"Beautiful {room_type_name} room",
            "price": base_price / nights if nights > 0 else base_price,
            "images": images,
            "amenities": amenities,
            "maxGuests": room.max_occupancy,
            "bedType": room.bed_type or "King",
            "size": room.size_sqft or 300,
            "view": room.view_type or "City"
        }
    elif room_type_obj:
        amenities = []
        images = []
        if room_type_obj.amenities:
            try:
                amenities = json.loads(room_type_obj.amenities) if isinstance(room_type_obj.amenities, str) else room_type_obj.amenities
            except:
                amenities = []
        if room_type_obj.images:
            try:
                images = json.loads(room_type_obj.images) if isinstance(room_type_obj.images, str) else room_type_obj.images
            except:
                images = []

        slug = room_type_obj.slug if room_type_obj.slug else room_type_name.lower().replace(' ', '-')
        room_data = {
            "id": str(room_type_obj.id),
            "name": room_type_name,
            "number": None,
            "slug": slug,
            "description": room_type_obj.description or f"Beautiful {room_type_name}",
            "price": base_price / nights if nights > 0 else base_price,
            "images": images,
            "amenities": amenities,
            "maxGuests": room_type_obj.max_guests,
            "bedType": room_type_obj.bed_type or "King",
            "size": room_type_obj.size_sqft or 300,
            "view": room_type_obj.view_type or "City"
        }

    # Compute payment amounts — use actual deposit, derive status from balance.
    # deposit_amount mirrors the folio's recorded payments (see
    # folio.sync_booking_payment), so zero money received means unpaid even if
    # a stale/legacy row still carries payment_status="paid".
    bk_deposit = booking.deposit_amount or 0.0
    bk_payment_status = booking.payment_status or "pending"
    bk_amount_paid = bk_deposit
    bk_balance_due = max(0.0, round(total_price - bk_amount_paid, 2))
    # Terminal payment states are preserved as-is; everything else is derived.
    if bk_payment_status not in ("refunded", "partially_refunded", "cancelled", "void"):
        if bk_amount_paid <= 0.0:
            bk_payment_status = "pending"
        elif bk_balance_due <= 0.0:
            bk_payment_status = "paid"
        else:
            bk_payment_status = "partial"

    # Look up DNM setter name
    dnm_set_by_name = None
    if booking.do_not_move and booking.dnm_set_by and session:
        dnm_setter = await session.get(User, booking.dnm_set_by)
        if dnm_setter:
            dnm_set_by_name = dnm_setter.full_name or dnm_setter.email

    # Calculate rate per night
    rate_per_night = base_price / nights if nights > 0 else base_price

    # Get corporate account name if linked
    corporate_account_name = None
    if booking.corporate_account_id and session:
        from app.models.bookings import CorporateAccounts
        corp = await session.get(CorporateAccounts, booking.corporate_account_id)
        if corp:
            corporate_account_name = corp.company_name

    return BookingResponse(
        id=str(booking.id),
        bookingNumber=booking.confirmation_code,
        userId=str(booking.created_by) if booking.created_by else "",
        guestId=guest.id,
        room=room_data,
        checkIn=booking.arrival_date.isoformat(),
        checkOut=booking.departure_date.isoformat(),
        guests={
            "adults": booking.adults,
            "children": booking.children,
            "infants": booking.infants or 0
        },
        guestInfo=GuestInfo(
            firstName=guest.first_name,
            lastName=guest.last_name,
            email=guest.email or "",
            phone=guest.phone or "",
            country=guest.country or "",
            specialRequests=booking.special_requests
        ),
        nights=nights,
        basePrice=base_price,
        taxes=taxes,
        serviceFee=service_fee,
        totalPrice=total_price,
        ratePerNight=rate_per_night,
        status=frontend_status,
        paymentStatus=bk_payment_status,
        paymentMethod=booking.payment_method or "card",
        createdAt=booking.created_at.isoformat(),
        updatedAt=booking.updated_at.isoformat(),
        vipStatus=booking.vip_flag or False,
        bookingSource=booking_source,
        doNotMove=booking.do_not_move or False,
        dnmSetBy=booking.dnm_set_by,
        dnmSetByName=dnm_set_by_name,
        dnmSetAt=booking.dnm_set_at.isoformat() if booking.dnm_set_at else None,
        amountPaid=bk_amount_paid,
        balanceDue=bk_balance_due,
        depositAmount=bk_amount_paid,  # Alias for frontend compatibility
        checkedInAt=booking.check_in_date.isoformat() if booking.check_in_date else None,
        checkedOutAt=booking.check_out_date.isoformat() if booking.check_out_date else None,
        expectedArrivalTime=getattr(booking, 'expected_arrival_time', None),
        expectedDepartureTime=getattr(booking, 'expected_departure_time', None),
        accompanyingGuests=json.loads(booking.accompanying_guests) if booking.accompanying_guests and isinstance(booking.accompanying_guests, str) else booking.accompanying_guests if booking.accompanying_guests else None,
        vipLevel=getattr(guest, 'vip_level', None) if hasattr(guest, 'vip_level') else None,
        guestProfileNumber=getattr(guest, 'profile_number', None) if hasattr(guest, 'profile_number') else None,
        arrivalDate=booking.arrival_date.isoformat() if booking.arrival_date else None,
        departureDate=booking.departure_date.isoformat() if booking.departure_date else None,
        roomNumber=room.number if room else None,
        roomId=booking.room_id,  # Direct room ID for frontend
        roomType=room_type_name,
        roomTypeId=booking.room_type_id,
        corporateAccountId=booking.corporate_account_id,
        corporateAccountName=corporate_account_name,
        # Group booking fields
        isGroupBooking=booking.is_group_booking or False,
        groupBookingId=booking.group_booking_id,
        parentBookingId=booking.parent_booking_id,
        numberOfRooms=booking.number_of_rooms,
    )


@router.get("", response_model=BookingListResponse)
async def list_bookings(
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=1000),
    page_size: int = Query(None, ge=1, le=1000, description="Alias for pageSize"),
    status: Optional[str] = Query(None),
    filter: Optional[str] = Query(None, description="Filter: arrivals_today, departures_today, overdue_arrivals"),
    dateFrom: Optional[str] = Query(None, description="Arrival date from (YYYY-MM-DD)"),
    dateTo: Optional[str] = Query(None, description="Arrival date to (YYYY-MM-DD)"),
    search: Optional[str] = Query(None, description="Search by guest name, booking number, or room number"),
    group_booking_id: Optional[int] = Query(None, description="Filter by group booking ID"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List bookings for current user - uses Booking model (bookings table)"""
    from app.core.roles import has_role_access

    # Handle page_size alias (snake_case)
    if page_size is not None:
        pageSize = page_size

    query = select(Booking)
    today = await get_business_date(session)

    # Filter by group_booking_id for group booking expansion
    if group_booking_id:
        query = query.where(Booking.group_booking_id == group_booking_id)

    # Filter by user's reservations (if user is not staff with booking access)
    # Staff roles with booking access: admin, general_manager, front_office_manager,
    # duty_manager, receptionist, reservation_manager, etc.
    if not current_user.is_superuser and not has_role_access(current_user.role, ["admin", "manager", "front_desk"]):
        # Find guest by user email
        guest = (await session.exec(
            select(Guest).where(Guest.email == current_user.email)
        )).first()

        if guest:
            query = query.where(Booking.guest_id == guest.id)
        else:
            # No guest found for this user, return empty list
            return BookingListResponse(
                items=[],
                total=0,
                page=page,
                pageSize=pageSize,
                totalPages=0
            )

    # Handle date-based filters (C-04, C-05)
    if filter == "arrivals_today":
        query = query.where(Booking.arrival_date == today)
    elif filter == "departures_today":
        query = query.where(Booking.departure_date == today)
    elif filter == "overdue_arrivals":
        # C-04: back-dated arrivals not yet checked in
        query = query.where(
            Booking.arrival_date < today,
            Booking.status.in_(["confirmed", "pending", "booked"])
        )

    # Date range filter (C-05)
    if dateFrom:
        try:
            query = query.where(Booking.arrival_date >= date.fromisoformat(dateFrom))
        except ValueError:
            pass
    if dateTo:
        try:
            query = query.where(Booking.arrival_date <= date.fromisoformat(dateTo))
        except ValueError:
            pass

    if status:
        status_map = {
            "upcoming": "pending",
            "confirmed": "confirmed",
            "past": "checked_out",
            "cancelled": "cancelled"
        }
        backend_status = status_map.get(status, status)
        query = query.where(Booking.status == backend_status)

    # Search filter (C-05: guest name, booking number, room number)
    if search:
        search_term = search.strip()
        # Pre-fetch matching guest IDs and room IDs for the search
        guest_ids = set()
        room_ids = set()
        # Search guests by name
        guest_results = await session.exec(
            select(Guest.id).where(
                (Guest.first_name.ilike(f"%{search_term}%")) |
                (Guest.last_name.ilike(f"%{search_term}%"))
            )
        )
        guest_ids.update(guest_results.all())
        # Search rooms by number
        room_results = await session.exec(
            select(Room.id).where(Room.number.ilike(f"%{search_term}%"))
        )
        room_ids.update(room_results.all())
        # Combine: match booking_number OR confirmation_code OR guest_id OR room_id
        from sqlalchemy import or_
        search_conditions = [
            Booking.booking_number.ilike(f"%{search_term}%"),
            Booking.confirmation_code.ilike(f"%{search_term}%"),
        ]
        if guest_ids:
            search_conditions.append(Booking.guest_id.in_(guest_ids))
        if room_ids:
            search_conditions.append(Booking.room_id.in_(room_ids))
        query = query.where(or_(*search_conditions))

    result = await session.exec(query.order_by(Booking.created_at.desc(), Booking.id.desc()))
    all_bookings = result.all()

    # Single deduplication layer after processing
    all_bookings = deduplicate_bookings(all_bookings)
    total = len(all_bookings)

    # Paginate
    offset = (page - 1) * pageSize
    paginated_bookings = all_bookings[offset:offset + pageSize]

    # Convert to frontend format (include placeholder guest if missing so webhook bookings show)
    bookings = []
    for booking in paginated_bookings:
        guest = await session.get(Guest, booking.guest_id)
        room = await session.get(Room, booking.room_id) if booking.room_id else None
        if not guest:
            class _PlaceholderGuest:
                first_name = "Guest"
                last_name = str(booking.id) if booking.id else ""
                email = ""
                phone = ""
                country = ""
            guest = _PlaceholderGuest()
        try:
            bookings.append(await booking_to_response(booking, guest, room, session))
        except Exception as e:
            logging.warning("list_bookings: skip booking id=%s: %s", booking.id, e)

    total_pages = (total + pageSize - 1) // pageSize

    return BookingListResponse(
        items=bookings,
        total=total,
        page=page,
        pageSize=pageSize,
        totalPages=total_pages
    )


class BookingPreviewRequest(BaseModel):
    """Request for booking preview/confirmation"""
    roomId: str
    checkIn: str
    checkOut: str
    guests: dict  # { adults: int, children: int, infants: int }
    guestInfo: GuestInfo
    ratePlan: Optional[str] = None


class BookingPreviewResponse(BaseModel):
    """Response with booking details for customer confirmation"""
    available: bool
    roomType: dict
    checkIn: str
    checkOut: str
    nights: int
    guests: dict
    guestInfo: dict
    pricing: dict
    policies: dict
    message: str


@router.post("/preview")
async def preview_booking(
    payload: BookingPreviewRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Preview booking details before confirmation.

    Returns pricing breakdown, room details, and policies for customer to review
    before confirming the booking.
    """
    # Validate required fields
    if not payload.guestInfo.firstName:
        raise HTTPException(status_code=400, detail="First name is required")
    if not payload.guestInfo.email:
        raise HTTPException(status_code=400, detail="Email is required")

    try:
        arrival = date.fromisoformat(payload.checkIn)
        departure = date.fromisoformat(payload.checkOut)

        # Validate dates
        if departure <= arrival:
            raise HTTPException(status_code=400, detail="Check-out date must be after check-in date")

        business_date = await get_business_date(session)
        if arrival < business_date:
            raise HTTPException(status_code=400, detail="Check-in date cannot be in the past")

        nights = (departure - arrival).days

        # Find room type
        from app.services.reservation_service import check_availability

        room_type_obj = None
        try:
            room_type_id_input = int(payload.roomId)
            room_type_obj = await session.get(RoomType, room_type_id_input)
        except ValueError:
            room_type_name = payload.roomId.replace('-', ' ').title()
            room_type_obj = (await session.exec(
                select(RoomType).where(RoomType.name == room_type_name)
            )).first()

            if not room_type_obj:
                room_type_obj = (await session.exec(
                    select(RoomType).where(RoomType.slug == payload.roomId)
                )).first()

        if not room_type_obj:
            raise HTTPException(status_code=404, detail="Room type not found")

        # Check availability
        adults = payload.guests.get("adults", 1)
        available_rooms = await check_availability(
            session=session,
            arrival_date=arrival,
            departure_date=departure,
            room_type=room_type_obj.name,
            adults=adults
        )

        if not available_rooms:
            return BookingPreviewResponse(
                available=False,
                roomType={
                    "id": room_type_obj.id,
                    "name": room_type_obj.name,
                    "description": room_type_obj.description,
                },
                checkIn=payload.checkIn,
                checkOut=payload.checkOut,
                nights=nights,
                guests=payload.guests,
                guestInfo=payload.guestInfo.dict(),
                pricing={},
                policies={},
                message=f"Sorry, {room_type_obj.name} is not available for the selected dates. Please choose different dates or room type."
            )

        # Calculate pricing using billing_engine (single source of truth)
        per_night_rate = float(room_type_obj.base_price)
        charges = calculate_stay_charges(per_night_rate, nights)
        base_price = float(charges.base_amount)
        taxes = float(charges.tax_amount)
        service_fee = 0  # Service fee removed
        total_price = float(charges.total_amount)
        tax_rate_pct = charges.tax.tax_rate_percent  # 12 or 18

        return BookingPreviewResponse(
            available=True,
            roomType={
                "id": room_type_obj.id,
                "name": room_type_obj.name,
                "description": room_type_obj.description,
                "amenities": room_type_obj.amenities or [],
                "maxGuests": room_type_obj.max_guests,
                "bedType": room_type_obj.bed_type,
                "size": room_type_obj.size_sqft,
            },
            checkIn=payload.checkIn,
            checkOut=payload.checkOut,
            nights=nights,
            guests=payload.guests,
            guestInfo=payload.guestInfo.dict(),
            pricing={
                "perNight": float(room_type_obj.base_price),
                "nights": nights,
                "basePrice": round(base_price, 2),
                "taxes": taxes,
                "taxRate": f"{int(tax_rate_pct)}%",
                "serviceFee": 0.0,
                "totalPrice": total_price,
                "currency": "INR",
                "currencySymbol": "₹",
            },
            policies={
                "checkInTime": "3:00 PM",
                "checkOutTime": "11:00 AM",
                "cancellation": "Free cancellation up to 24 hours before check-in",
                "payment": "Full payment required at booking",
            },
            message=f"Please review your booking details below. Click 'Confirm Booking' to proceed."
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {str(e)}")


# ─── MULTI-ROOM BOOKING HELPERS ─────────────────────────────────────────────────

async def _check_multi_room_idempotency(
    session: AsyncSession,
    guest_id: int,
    arrival: date,
    departure: date,
    room_type_ids: List[int]
) -> Optional[int]:
    """Check for duplicate multi-room booking within 120s window.

    Returns group_booking_id if duplicate found, None otherwise.
    """
    idempotency_window = datetime.utcnow() - timedelta(seconds=120)
    # Find any recent group booking with same guest and dates
    existing = (await session.exec(
        select(Booking).where(
            and_(
                Booking.guest_id == guest_id,
                Booking.arrival_date == arrival,
                Booking.departure_date == departure,
                Booking.is_group_booking == True,
                Booking.parent_booking_id == None,  # Only check parent bookings
                Booking.created_at >= idempotency_window,
                Booking.status.in_(["pending", "confirmed", "booked"]),
            )
        ).order_by(Booking.created_at.desc()).limit(1)
    )).first()

    if existing and existing.group_booking_id:
        # Verify same room types
        group_bookings = (await session.exec(
            select(Booking).where(Booking.group_booking_id == existing.group_booking_id)
        )).all()
        existing_types = sorted([b.room_type_id for b in group_bookings])
        if existing_types == sorted(room_type_ids):
            return existing.group_booking_id
    return None


async def _check_overlapping_booking(
    session: AsyncSession,
    email: str,
    room_type_id: int,
    arrival: date,
    departure: date
) -> Optional[str]:
    """Check for overlapping active booking for same guest email + room type.

    Returns error message if overlap found, None otherwise.
    """
    normalized_email = email.strip().lower()
    email_guest_ids_result = await session.exec(
        select(Guest.id).where(Guest.email == normalized_email)
    )
    email_guest_ids = list(email_guest_ids_result.all())

    if email_guest_ids:
        overlap_query = select(Booking).where(
            and_(
                Booking.guest_id.in_(email_guest_ids),
                Booking.room_type_id == room_type_id,
                Booking.status.notin_(["cancelled", "no_show", "checked_out"]),
                Booking.arrival_date < departure,
                Booking.departure_date > arrival,
            )
        )
        overlap_hit = (await session.exec(overlap_query)).first()
        if overlap_hit:
            return (
                f"An active booking already exists for {normalized_email} "
                f"in room type ID {room_type_id} from {overlap_hit.arrival_date} to "
                f"{overlap_hit.departure_date}."
            )
    return None


async def _create_multi_room_booking(
    payload: CreateBookingRequest,
    session: AsyncSession,
    current_user: User,
    background_tasks: BackgroundTasks
) -> MultiRoomBookingResponse:
    """Create a multi-room booking with parent + child bookings.

    All rooms are validated upfront. If any validation fails, the entire request fails.
    """
    import uuid
    from app.services.reservation_service import check_availability, create_guest
    from app.models.inventory import DailyAvailability

    arrival = date.fromisoformat(payload.checkIn)
    departure = date.fromisoformat(payload.checkOut)
    business_date = await get_business_date(session)

    # Validate dates
    if departure <= arrival:
        raise HTTPException(status_code=400, detail="Check-out must be after check-in")
    if arrival < business_date:
        raise HTTPException(status_code=400, detail="Check-in date cannot be in the past")

    nights = (departure - arrival).days
    if nights < 1:
        nights = 1

    # Create or find guest
    guest_dict = {
        "first_name": payload.guestInfo.firstName.strip(),
        "last_name": payload.guestInfo.lastName.strip(),
        "email": payload.guestInfo.email.strip().lower(),
        "phone": payload.guestInfo.phone.strip(),
        "country": payload.guestInfo.country.strip(),
        "notes": payload.guestInfo.specialRequests.strip() if payload.guestInfo.specialRequests else None,
    }
    guest, _ = await create_guest(session, guest_dict)

    # Collect room type IDs for idempotency check
    room_type_ids = [r.room_type_id for r in payload.rooms]

    # Check for duplicate multi-room booking
    existing_group_id = await _check_multi_room_idempotency(
        session, guest.id, arrival, departure, room_type_ids
    )
    if existing_group_id:
        # Return existing group booking
        existing_bookings = (await session.exec(
            select(Booking).where(Booking.group_booking_id == existing_group_id)
        )).all()
        parent = next((b for b in existing_bookings if b.parent_booking_id is None), existing_bookings[0])

        booking_items = []
        for b in existing_bookings:
            rt = await session.get(RoomType, b.room_type_id)
            booking_items.append(MultiRoomBookingItem(
                id=b.id,
                bookingNumber=b.booking_number,
                roomTypeId=b.room_type_id,
                roomTypeName=rt.name if rt else "Unknown",
                isParent=b.parent_booking_id is None,
                adults=b.adults,
                children=b.children,
                basePrice=b.base_price or 0,
                taxes=b.taxes or 0,
                totalPrice=b.total_price or 0,
            ))

        logger.info(f"Idempotent multi-room booking: returning existing group_id={existing_group_id}")
        return MultiRoomBookingResponse(
            message=f"Booking created: {len(existing_bookings)} room(s)",
            groupBookingId=existing_group_id,
            parentBookingId=parent.id,
            totalPrice=round(sum(b.total_price for b in existing_bookings), 2),
            bookings=booking_items,
        )

    # Validate ALL rooms upfront
    room_types_validated = {}
    for i, room_req in enumerate(payload.rooms):
        rt = await session.get(RoomType, room_req.room_type_id)
        if not rt:
            raise HTTPException(
                status_code=404,
                detail=f"Room type {room_req.room_type_id} not found (room #{i+1})"
            )

        # Check guest capacity
        if room_req.adults > rt.max_guests:
            raise HTTPException(
                status_code=400,
                detail=f"Adults ({room_req.adults}) exceeds capacity ({rt.max_guests}) for {rt.name} (room #{i+1})"
            )

        # Check availability
        available = await check_availability(
            session=session,
            arrival_date=arrival,
            departure_date=departure,
            room_type=rt.name,
            adults=room_req.adults
        )
        if not available:
            raise HTTPException(
                status_code=400,
                detail=f"No availability for {rt.name} on these dates (room #{i+1})"
            )

        # Check for overlapping bookings (same guest + room type)
        overlap_error = await _check_overlapping_booking(
            session, payload.guestInfo.email, rt.id, arrival, departure
        )
        if overlap_error:
            raise HTTPException(status_code=400, detail=overlap_error)

        room_types_validated[i] = rt

    # Generate group booking ID
    group_id = int(datetime.utcnow().timestamp() * 1000) % 1000000

    # Get default rate plan
    default_rate_plan_id = await get_default_rate_plan_id(session)

    # Look up dynamic rates from DailyAvailability
    dynamic_rates: dict = {}
    for rt_id in set(rt.id for rt in room_types_validated.values()):
        da_result = await session.exec(
            select(DailyAvailability).where(
                and_(
                    DailyAvailability.room_type_id == rt_id,
                    DailyAvailability.date == arrival,
                )
            ).limit(1)
        )
        da = da_result.first()
        if da and da.base_rate:
            dynamic_rates[rt_id] = da.base_rate

    created_bookings = []

    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 1: Calculate pricing for ALL rooms using billing_engine (single source of truth)
    # Each room is calculated independently, then aggregated for parent total
    # ═══════════════════════════════════════════════════════════════════════════════

    room_pricing_list = []  # Store pricing for each room

    for idx, room_req in enumerate(payload.rooms):
        rt = room_types_validated[idx]

        # Determine nightly rate for this room
        if room_req.rate_per_night is not None and room_req.rate_per_night > 0:
            nightly_rate = room_req.rate_per_night
        else:
            nightly_rate = dynamic_rates.get(rt.id, rt.base_price or 0)

        # Calculate using billing_engine (SINGLE SOURCE OF TRUTH)
        charges = calculate_stay_charges(nightly_rate, nights)

        room_pricing_list.append({
            "idx": idx,
            "room_type": rt,
            "room_req": room_req,
            "nightly_rate": float(charges.nightly_rate),
            "base_price": float(charges.base_amount),
            "taxes": float(charges.tax_amount),
            "tax_rate": float(charges.tax_rate),
            "total_price": float(charges.total_amount),
        })

    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 2: Calculate GROUP TOTAL by aggregating individual room calculations
    # Parent total = exact sum of all room totals (NO recalculation at parent level)
    # ═══════════════════════════════════════════════════════════════════════════════

    group_base_total = sum(r["base_price"] for r in room_pricing_list)
    group_tax_total = sum(r["taxes"] for r in room_pricing_list)
    group_total = sum(r["total_price"] for r in room_pricing_list)

    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 3: Create parent booking with AGGREGATED totals
    # ═══════════════════════════════════════════════════════════════════════════════

    first_pricing = room_pricing_list[0]
    first_rt = first_pricing["room_type"]
    first_req = first_pricing["room_req"]

    parent = Booking(
        booking_number=f"BK-{uuid.uuid4().hex[:8].upper()}",
        confirmation_code=f"GRP-{uuid.uuid4().hex[:6].upper()}",
        guest_id=guest.id,
        user_id=current_user.id,
        room_type_id=first_rt.id,
        arrival_date=arrival,
        departure_date=departure,
        nights=nights,
        adults=first_req.adults,
        children=first_req.children,
        status="confirmed",
        payment_status="pending",
        payment_method=payload.paymentMethod or "card",
        booking_source=payload.source or "Direct",
        channel=payload.channel,
        # Parent stores AGGREGATED totals for the entire group
        base_price=round(group_base_total, 2),
        nightly_rate=first_pricing["nightly_rate"],  # Store first room's rate for reference
        tax_rate=first_pricing["tax_rate"],  # Store first room's tax rate
        taxes=round(group_tax_total, 2),
        service_fee=0,
        total_price=round(group_total, 2),
        deposit_amount=0,
        balance_due=round(group_total, 2),
        is_group_booking=True,
        group_booking_id=group_id,
        number_of_rooms=len(payload.rooms),
        corporate_account_id=payload.corporateAccountId,
        special_requests=first_req.special_requests,
        rate_plan_id=default_rate_plan_id,
        created_by=current_user.id,
    )
    session.add(parent)
    await session.flush()
    await session.refresh(parent)
    created_bookings.append(parent)

    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 4: Create child bookings with INDIVIDUAL room pricing
    # Child bookings track room-level details but payments go through parent
    # ═══════════════════════════════════════════════════════════════════════════════

    for pricing_data in room_pricing_list[1:]:  # Skip first (parent's room)
        rt = pricing_data["room_type"]
        room_req = pricing_data["room_req"]

        child = Booking(
            booking_number=f"BK-{uuid.uuid4().hex[:8].upper()}",
            confirmation_code=f"GRP-{uuid.uuid4().hex[:6].upper()}",
            guest_id=guest.id,
            user_id=current_user.id,
            room_type_id=rt.id,
            arrival_date=arrival,
            departure_date=departure,
            nights=nights,
            adults=room_req.adults,
            children=room_req.children,
            status="confirmed",
            payment_status="pending",  # Child payment status follows parent
            payment_method=payload.paymentMethod or "card",
            booking_source=payload.source or "Direct",
            channel=payload.channel,
            # Child stores its OWN room charges (for tracking purposes)
            base_price=pricing_data["base_price"],
            nightly_rate=pricing_data["nightly_rate"],
            tax_rate=pricing_data["tax_rate"],
            taxes=pricing_data["taxes"],
            service_fee=0,
            total_price=pricing_data["total_price"],
            deposit_amount=0,  # NO deposit on child - payments on parent only
            balance_due=0,  # Child shows ₹0 balance - payment through parent
            is_group_booking=True,
            group_booking_id=group_id,
            number_of_rooms=len(payload.rooms),
            parent_booking_id=parent.id,
            corporate_account_id=payload.corporateAccountId,
            special_requests=room_req.special_requests,
            rate_plan_id=default_rate_plan_id,
            created_by=current_user.id,
        )
        session.add(child)
        await session.flush()
        await session.refresh(child)
        created_bookings.append(child)

    await session.commit()

    # ═══════════════════════════════════════════════════════════════════════════════
    # STEP 5: Create ONLY ONE consolidated folio on PARENT booking
    # All room charges will be posted to this single folio at check-in
    # Child bookings do NOT get separate folios (avoids duplicate charges)
    # ═══════════════════════════════════════════════════════════════════════════════

    from app.models.operations import Folio, FolioLineItem
    from app.api.v1.frontdesk import generate_folio_number

    # Create folio ONLY for parent booking - NO charges at booking time
    # Charges are posted at check-in with room-wise breakdown
    parent_folio = Folio(
        booking_id=parent.id,
        reservation_id=parent.id,  # Use booking_id as fallback
        folio_number=generate_folio_number(),
        window_label="A",
        folio_type="group_master",  # Mark as group master folio
        total_charges=0.0,  # Charges posted at check-in
        total_payments=0.0,
        balance=0.0,  # Will be updated when charges are posted
        status="open",
    )
    session.add(parent_folio)
    await session.flush()

    # NOTE: NO child folios created
    # Room charges will be posted with room-wise breakdown to parent folio at check-in

    await session.commit()
    logger.info(f"Created single consolidated folio for group booking {group_id} with {len(created_bookings)} rooms (total: ₹{group_total:.2f})")

    # Build response using room_pricing_list (consistent with billing_engine calculations)
    booking_items = []
    for idx, pricing_data in enumerate(room_pricing_list):
        bk = created_bookings[idx]
        rt = pricing_data["room_type"]
        booking_items.append(MultiRoomBookingItem(
            id=bk.id,
            bookingNumber=bk.booking_number,
            roomTypeId=rt.id,
            roomTypeName=rt.name,
            isParent=bk.parent_booking_id is None,
            adults=bk.adults,
            children=bk.children,
            basePrice=pricing_data["base_price"],
            taxes=pricing_data["taxes"],
            totalPrice=pricing_data["total_price"],
        ))

    # Broadcast SSE event
    sse_data = {
        "booking_id": parent.id,
        "group_booking_id": group_id,
        "booking_number": parent.booking_number,
        "guest_id": guest.id,
        "arrival_date": arrival.isoformat(),
        "departure_date": departure.isoformat(),
        "status": "confirmed",
        "number_of_rooms": len(created_bookings),
        "channel": payload.channel or payload.source or "direct",
        "total_price": round(group_total, 2),
    }
    background_tasks.add_task(broadcast_sse_event, "booking.created", sse_data)

    logger.info(f"Multi-room booking created: group_id={group_id}, {len(created_bookings)} rooms, total=₹{group_total:.2f}")

    # Return group_total (sum of all room totals) as totalPrice
    return MultiRoomBookingResponse(
        message=f"Booking created: {len(created_bookings)} room(s)",
        groupBookingId=group_id,
        parentBookingId=parent.id,
        totalPrice=round(group_total, 2),  # Exact sum of all room totals
        bookings=booking_items,
    )


@router.post("", status_code=201)
async def create_booking(
    payload: CreateBookingRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new booking (single or multi-room)"""
    # Validate required fields - firstName is required, lastName can be empty
    if not payload.guestInfo.firstName:
        raise HTTPException(status_code=400, detail="First name is required")
    if not payload.guestInfo.email:
        raise HTTPException(status_code=400, detail="Email is required")
    if not payload.guestInfo.phone:
        raise HTTPException(status_code=400, detail="Phone number is required")
    if not payload.guestInfo.country:
        raise HTTPException(status_code=400, detail="Country is required")

    # Check if this is a multi-room booking
    is_multi_room = payload.rooms and len(payload.rooms) > 1
    if is_multi_room:
        return await _create_multi_room_booking(payload, session, current_user, background_tasks)

    # Single room booking continues below
    # Validate that roomId or roomTypeId is provided for single room bookings
    if not payload.roomId and not payload.roomTypeId and not (payload.rooms and len(payload.rooms) == 1):
        raise HTTPException(status_code=400, detail="roomId or roomTypeId is required for single room bookings")

    # Handle single room from rooms[] array
    if payload.rooms and len(payload.rooms) == 1:
        single_room = payload.rooms[0]
        payload.roomTypeId = single_room.room_type_id
        payload.roomId = str(single_room.room_type_id)
        if not payload.guests:
            payload.guests = {"adults": single_room.adults, "children": single_room.children, "infants": 0}

    try:
        arrival = date.fromisoformat(payload.checkIn)
        departure = date.fromisoformat(payload.checkOut)

        # Validate dates
        if departure < arrival:
            raise HTTPException(status_code=400, detail="Check-out date cannot be before check-in date")
        if arrival < await get_business_date(session):
            raise HTTPException(status_code=400, detail="Check-in date cannot be in the past")

        # Room assignment strategy:
        # - At booking time: only store room_type_id (the category/type guest selected)
        # - Room assignment (room_id) happens at check-in or by admin/front desk
        from app.services.reservation_service import check_availability

        room_type_obj = None
        room = None  # No specific room assigned at booking time
        room_id = None

        # Check if roomId is a numeric room_type ID or a slug
        try:
            room_type_id_input = int(payload.roomId)
            # It's a numeric ID - could be room type ID
            room_type_obj = await session.get(RoomType, room_type_id_input)
            if not room_type_obj:
                raise HTTPException(status_code=404, detail="Room type not found")
        except ValueError:
            # It's a slug (room type), find the room type
            # Convert slug to room type name (e.g., "wellness-suite" -> "Wellness Suite")
            room_type_name = payload.roomId.replace('-', ' ').title()

            # Look up the room type by name
            room_type_obj = (await session.exec(
                select(RoomType).where(RoomType.name == room_type_name)
            )).first()

            if not room_type_obj:
                # Try by slug
                room_type_obj = (await session.exec(
                    select(RoomType).where(RoomType.slug == payload.roomId)
                )).first()

            if not room_type_obj:
                raise HTTPException(
                    status_code=404,
                    detail=f"Room type '{room_type_name}' not found. Please check the room type name."
                )

        # Get adults count for availability check
        adults = payload.guests.get("adults", 1)

        # Check availability for this room type (don't assign a specific room yet)
        available_rooms = await check_availability(
            session=session,
            arrival_date=arrival,
            departure_date=departure,
            room_type=room_type_obj.name,
            adults=adults
        )

        if not available_rooms:
            raise HTTPException(
                status_code=400,
                detail=f"No available {room_type_obj.name} rooms for the selected dates"
            )

        # Store room_type_id but NOT room_id (room assigned later at check-in)
        room_type_id = room_type_obj.id

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid date format or room ID: {str(e)}")
    except TypeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid parameters: {str(e)}")
    
    # Get adults and children from guests dict - ensure they are integers
    adults = int(payload.guests.get("adults", 1))
    children = int(payload.guests.get("children", 0))

    # Validate guests count against room type max guests
    # Note: Only adults count towards max_guests limit; children are allowed with adults
    if adults < 1:
        raise HTTPException(status_code=400, detail="At least one adult guest is required")
    if adults > room_type_obj.max_guests:
        raise HTTPException(status_code=400, detail=f"Number of adults ({adults}) exceeds room type maximum ({room_type_obj.max_guests})")

    # Room type name for price calculation
    room_type_name = room_type_obj.name

    # Get the default rate plan for this hotel
    default_rate_plan_id = await get_default_rate_plan_id(session)

    # Idempotency: prevent duplicate bookings when the same request is sent multiple times
    # (e.g. double-click submit, React Strict Mode, or multiple event handlers).
    guest_dict = {
        "first_name": payload.guestInfo.firstName.strip(),
        "last_name": payload.guestInfo.lastName.strip(),
        "email": payload.guestInfo.email.strip().lower(),
        "phone": payload.guestInfo.phone.strip(),
        "country": payload.guestInfo.country.strip(),
        "notes": payload.guestInfo.specialRequests.strip() if payload.guestInfo.specialRequests else None,
    }
    guest, guest_profile_count = await create_guest(session, guest_dict)
    idempotency_window = datetime.utcnow() - timedelta(seconds=120)
    existing_booking = (await session.exec(
        select(Booking).where(
            and_(
                Booking.guest_id == guest.id,
                Booking.arrival_date == arrival,
                Booking.departure_date == departure,
                Booking.room_type_id == room_type_id,
                Booking.created_at >= idempotency_window,
                Booking.status.in_(["pending", "confirmed", "booked"]),
            )
        ).order_by(Booking.created_at.desc()).limit(1)
    )).first()
    if existing_booking:
        await session.refresh(existing_booking)
        room = await session.get(Room, existing_booking.room_id) if existing_booking.room_id else None
        response = await booking_to_response(existing_booking, guest, room, session)
        logger.info(f"Idempotent create_booking: returning existing booking id={existing_booking.id} (confirmation_code={existing_booking.confirmation_code})")
        return response

    # ── Overlapping-stay guard ──────────────────────────────────────────
    # Reject if the same email already has an active booking for the same
    # room type with overlapping [arrival, departure).
    normalized_email = payload.guestInfo.email.strip().lower()
    # Find ALL guest IDs sharing this email (handles multiple guest rows)
    email_guest_ids_result = await session.exec(
        select(Guest.id).where(Guest.email == normalized_email)
    )
    email_guest_ids = list(email_guest_ids_result.all())
    if email_guest_ids:
        overlap_query = select(Booking).where(
            and_(
                Booking.guest_id.in_(email_guest_ids),
                Booking.room_type_id == room_type_id,
                Booking.status.notin_(["cancelled", "no_show", "checked_out"]),
                Booking.arrival_date < departure,
                Booking.departure_date > arrival,
            )
        )
        overlap_hit = (await session.exec(overlap_query)).first()
        if overlap_hit:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"An active booking already exists for {normalized_email} "
                    f"in this room type from {overlap_hit.arrival_date} to "
                    f"{overlap_hit.departure_date}. Please choose different "
                    f"dates or a different room type."
                ),
            )

    # Create reservation using backend service
    # Note: room_id is NOT passed - it will be assigned later at check-in
    reservation_data = ReservationCreate(
        guest={
            "first_name": payload.guestInfo.firstName.strip(),
            "last_name": payload.guestInfo.lastName.strip(),
            "email": payload.guestInfo.email.strip().lower(),
            "phone": payload.guestInfo.phone.strip(),
            "country": payload.guestInfo.country.strip(),
            "notes": payload.guestInfo.specialRequests.strip() if payload.guestInfo.specialRequests else None
        },
        rate_plan_id=default_rate_plan_id,
        arrival_date=arrival,
        departure_date=departure,
        adults=adults,
        children=children,
        special_requests=payload.guestInfo.specialRequests.strip() if payload.guestInfo.specialRequests else None,
        room_id=None  # Room assigned at check-in, not booking time
    )
    
    try:
        # Payment status at creation is ALWAYS "pending".
        # No money is collected by this endpoint — deposit_amount stays 0 and
        # actual payments are recorded through the folio / payment endpoints,
        # which then move the booking to "partial" or "paid". Deriving "paid"
        # from the selected payment method marked brand-new, unpaid bookings
        # as Paid in the Bookings list.
        payment_status = "pending"

        # Use frontend rate if provided (includes dynamic pricing, promotions)
        # Otherwise fall back to room type base price
        nights = (departure - arrival).days or 1
        if payload.ratePerNight and payload.ratePerNight > 0:
            effective_per_night_rate = payload.ratePerNight
        elif payload.basePrice and payload.basePrice > 0:
            effective_per_night_rate = payload.basePrice / nights
        elif room_type_obj and room_type_obj.base_price:
            effective_per_night_rate = room_type_obj.base_price
        else:
            effective_per_night_rate = 0

        # Pass room_type_id to create_reservation so Booking record is also created
        # Use frontend rate to ensure consistency between reservation and confirmed booking
        reservation = await create_reservation(
            session,
            reservation_data,
            user_id=current_user.id,
            allow_overbooking=False,
            room_type_id=room_type_id,
            base_price=effective_per_night_rate,  # Use frontend rate, not room_type.base_price
            payment_method=payload.paymentMethod or "card",
            payment_status=payment_status
        )

        # room_type_id is now set in create_reservation
        # No need to set it again: reservation.room_type_id = room_type_id

        # Calculate total with taxes using billing_engine (single source of truth)
        charges = calculate_stay_charges(effective_per_night_rate, nights)
        base_price = float(charges.base_amount)
        taxes = float(charges.tax_amount)
        service_fee = 0  # Service fee removed
        reservation.total_amount = float(charges.total_amount)
        reservation.currency = "INR"

        # Store the rate info for later use (extensions, refunds)
        stored_nightly_rate = float(charges.nightly_rate)
        stored_tax_rate = float(charges.tax_rate)

        # CRITICAL: Ensure room_id is NOT set at booking time
        reservation.room_id = None

        await session.commit()
        await session.refresh(reservation)

        # Get guest
        guest = await session.get(Guest, reservation.guest_id)
        if not guest:
            raise HTTPException(status_code=500, detail="Guest not found after creation")
        
        # Query for the Booking record that was created alongside the Reservation
        # This ensures we return the correct Booking ID (not Reservation ID)
        import logging
        logging.info(f"Looking for booking with confirmation_code: {reservation.confirmation_code}")

        booking_record = (await session.exec(
            select(Booking).where(Booking.confirmation_code == reservation.confirmation_code)
        )).first()

        # Confirm the booking. The selected payment method only records the
        # INTENDED method — it is not proof of payment, so the booking stays
        # unpaid until a payment is actually recorded against the folio.
        if booking_record:
            logging.info(f"Found booking record ID: {booking_record.id}, updating status...")
            booking_record.status = "confirmed"
            pm = payload.paymentMethod or "card"
            booking_record.payment_method = pm
            booking_record.payment_status = "pending"
            logging.info(f"Set payment_status=pending ({pm}) for booking {booking_record.id} — no payment recorded yet")

            # Update pricing components from frontend if provided
            if payload.basePrice and payload.basePrice > 0:
                booking_record.base_price = payload.basePrice
                logging.info(f"Set base_price={payload.basePrice} from frontend for booking {booking_record.id}")
            if payload.taxes and payload.taxes > 0:
                booking_record.taxes = payload.taxes
                logging.info(f"Set taxes={payload.taxes} from frontend for booking {booking_record.id}")
            # Service fee is always 0 (removed) — ignore frontend value to prevent mismatch
            booking_record.service_fee = 0

            # Store nightly rate and tax rate from billing_engine calculation
            booking_record.nightly_rate = stored_nightly_rate
            booking_record.tax_rate = stored_tax_rate

            # Always recalculate total_price from components to ensure consistency
            # This prevents mismatches between total, deposit, and folio charges
            booking_record.total_price = round(
                (booking_record.base_price or 0) +
                (booking_record.taxes or 0) +
                (booking_record.service_fee or 0), 2
            )
            logging.info(f"Calculated total_price={booking_record.total_price} for booking {booking_record.id}")

            # Do NOT auto-set deposit_amount at booking creation.
            # deposit_amount should only be set when actual payment is
            # recorded (via folio payment endpoint or check-in deposit).
            # Setting it here caused folios to show "already paid" before
            # any real payment was collected.
            booking_record.deposit_amount = 0
            booking_record.balance_due = booking_record.total_price or 0
            logging.info(f"Booking {booking_record.id}: deposit_amount=0, balance_due={booking_record.balance_due} (payment recorded at folio level)")

            # Set booking source and channel if provided (Dummy CM sends source="DUMMY", channel="Dummy Channel Manager")
            if payload.channel:
                booking_record.channel = payload.channel
                logging.info(f"Set channel={booking_record.channel} for booking {booking_record.id}")
            if payload.source:
                source_reverse_map = {
                    "Website": "direct",
                    "Walk-in": "walk_in",
                    "Booking.com": "booking_com",
                    "Expedia": "expedia",
                    "Airbnb": "airbnb",
                    "Phone": "phone",
                    "Email": "email",
                    "Travel Agent": "travel_agent",
                    "Corporate": "corporate",
                    "Corporate Portal": "corporate",
                    "Direct": "direct",
                    "OTA": "ota",
                    "Other": "other",
                    "Dummy Channel Manager": "dummy",
                    "DUMMY": "dummy",
                    "CRS": "crs",
                }
                booking_record.booking_source = source_reverse_map.get(payload.source, payload.source.lower().replace(" ", "_"))
                logging.info(f"Set booking_source={booking_record.booking_source} for booking {booking_record.id}")

            # Sprint 6: ETA/ETD + accompanying guests
            if payload.expectedArrivalTime:
                booking_record.expected_arrival_time = payload.expectedArrivalTime
            if payload.expectedDepartureTime:
                booking_record.expected_departure_time = payload.expectedDepartureTime
            if payload.accompanyingGuests:
                import json as _json
                booking_record.accompanying_guests = _json.dumps(payload.accompanyingGuests) if isinstance(payload.accompanyingGuests, list) else payload.accompanyingGuests

            # Corporate account linkage at booking creation
            if payload.corporateAccountId:
                booking_record.corporate_account_id = payload.corporateAccountId
                from app.models.bookings import CorporateAccounts
                corp = await session.get(CorporateAccounts, payload.corporateAccountId)
                if corp:
                    corp.total_bookings = (corp.total_bookings or 0) + 1

            # VIP flag at booking creation
            if payload.vipStatus:
                booking_record.vip_flag = True
                # Also mark the guest record as VIP
                if booking_record.guest_id:
                    guest_obj = await session.get(Guest, booking_record.guest_id)
                    if guest_obj:
                        guest_obj.vip_status = True

            # Rate plan override (find matching rate plan by name)
            if payload.ratePlan:
                try:
                    from sqlmodel import select as sel
                    from app.models.pricing import RatePlan
                    rp_stmt = sel(RatePlan).where(
                        (RatePlan.name == payload.ratePlan) | (RatePlan.code == payload.ratePlan)
                    )
                    rp = (await session.exec(rp_stmt)).first()
                    if rp:
                        booking_record.rate_plan_id = rp.id
                except Exception:
                    pass  # Non-critical — keep default rate plan

            await session.commit()
            await session.refresh(booking_record)
            logging.info(f"Booking {booking_record.id} updated: status={booking_record.status}, payment_status={booking_record.payment_status}")
        else:
            logging.warning(f"No booking record found for confirmation_code: {reservation.confirmation_code}")

        # Also update the legacy reservation status
        reservation.status = "confirmed"
        await session.commit()
        await session.refresh(reservation)

        # Send booking confirmation email with PDF
        if guest.email:
            try:
                from app.services.email_service import get_email_service
                from app.services.pdf_service import generate_booking_confirmation_pdf
                from app.core.config import settings
                from datetime import datetime as dt

                # Use booking_record ID if available for consistent URLs
                booking_id_for_url = booking_record.id if booking_record else reservation.id

                # Generate PDF
                pdf_data = {
                    'booking_number': reservation.confirmation_code,
                    'guest_name': f"{guest.first_name} {guest.last_name}",
                    'email': guest.email,
                    'phone': guest.phone or 'N/A',
                    'check_in': reservation.arrival_date.isoformat(),
                    'check_out': reservation.departure_date.isoformat(),
                    'nights': (reservation.departure_date - reservation.arrival_date).days,
                    'room_type': room_type_name,
                    'room_number': room.number if room else None,
                    'base_price': base_price,
                    'taxes': taxes,
                    'service_fee': service_fee,
                    'total_amount': reservation.total_amount,
                    'currency': '₹',
                }
                pdf_content = generate_booking_confirmation_pdf(pdf_data)

                # Generate pre-checkin URL using Booking ID for consistency
                precheckin_url = f"{settings.frontend_url}/pre-checkin?bookingId={booking_id_for_url}"

                # Format dates for email
                check_in_str = reservation.arrival_date.isoformat()
                check_out_str = reservation.departure_date.isoformat()

                # Send email in background - doesn't block response
                from app.services.background_email import send_booking_confirmation_email_bg
                background_tasks.add_task(
                    send_booking_confirmation_email_bg,
                    to_email=guest.email,
                    booking_number=booking_record.confirmation_code,
                    guest_name=f"{guest.first_name} {guest.last_name}",
                    check_in=check_in_str,
                    check_out=check_out_str,
                    room_type=room_type_name,
                    room_number=room.number if room else None,
                    total_amount=float(reservation.total_amount),
                    currency=booking_record.currency or "INR",
                    precheckin_url=precheckin_url,
                    pdf_content=pdf_content,
                )
            except Exception as e:
                # Log error but don't fail the booking
                import logging
                logging.error(f"Failed to send booking confirmation email: {str(e)}")

        # Snapshot SSE data before notification (which may rollback the session)
        if booking_record:
            sse_data = {
                "booking_id": booking_record.id,
                "booking_number": booking_record.booking_number,
                "confirmation_code": booking_record.confirmation_code,
                "guest_id": booking_record.guest_id,
                "room_type_id": booking_record.room_type_id,
                "arrival_date": booking_record.arrival_date.isoformat() if booking_record.arrival_date else None,
                "departure_date": booking_record.departure_date.isoformat() if booking_record.departure_date else None,
                "status": booking_record.status,
                "channel": booking_record.channel or booking_record.booking_source or "direct"
            }
        else:
            sse_data = {
                "booking_id": reservation.id,
                "booking_number": reservation.confirmation_code,
                "confirmation_code": reservation.confirmation_code,
                "guest_id": reservation.guest_id,
                "room_type_id": room.room_type_id if room else None,
                "arrival_date": reservation.arrival_date.isoformat() if reservation.arrival_date else None,
                "departure_date": reservation.departure_date.isoformat() if reservation.departure_date else None,
                "status": reservation.status,
                "channel": "direct"
            }

        # Build the response before notification (in case notification rolls back session)
        if booking_record:
            response = await booking_to_response(booking_record, guest, room, session)
        else:
            response = await reservation_to_booking_response(reservation, guest, room, session, room_type_obj)

        # Attach duplicate-email advisory when more than one guest profile shares this email
        if guest_profile_count > 1:
            response.guestEmailDuplicateMessage = (
                "Multiple guest profiles share this email address. "
                "Please verify the guest details are correct."
            )

        # Notify admins about the new booking
        try:
            await notify_new_booking(
                session=session,
                guest_name=f"{guest.first_name} {guest.last_name}",
                room_number=room.number if room else f"Type: {room_type_name}",
                check_in_date=reservation.arrival_date.isoformat(),
                check_out_date=reservation.departure_date.isoformat(),
                booking_id=booking_record.id if booking_record else reservation.id,
                total_amount=float(reservation.total_amount),
                guest_id=guest.id,
                room_id=room.id if room else None
            )
            await session.commit()
        except Exception as e:
            import logging
            logging.error(f"Failed to send admin notification: {str(e)}")
            # Rollback the failed transaction so the session remains usable
            await session.rollback()

        # Broadcast SSE event for real-time frontend updates
        background_tasks.add_task(broadcast_sse_event, "booking.created", sse_data)

        return response
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── RATE CHECK REPORT (B-17) ────────────────────────────────────────────────────
# NOTE: Must be above /{booking_id} routes so FastAPI doesn't match "rate-check-report" as a booking ID

@router.get("/rate-check-report")
async def rate_check_report(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """
    Rate check report: compare each checked-in booking's rate against the standard rate plan.
    Flags variance (discount / surcharge / match).
    """
    allowed_roles = ["admin", "front_desk", "manager", "revenue_manager", "general_manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Access denied")

    bookings_result = await session.exec(
        select(Booking).where(Booking.status == "checked_in")
    )
    active_bookings = bookings_result.all()

    # RoomType already imported at module level
    room_types = {}
    rt_result = await session.exec(select(RoomType))
    for rt in rt_result.all():
        room_types[rt.id] = rt

    report = []
    for b in active_bookings:
        nights = max(1, b.nights or 1)
        actual_rate = round((b.base_price or 0) / nights, 2)

        rt = room_types.get(b.room_type_id)

        standard_rate = rt.base_price if rt else 0
        variance = round(actual_rate - standard_rate, 2) if standard_rate else 0
        variance_pct = round(variance / standard_rate * 100, 1) if standard_rate else 0

        if abs(variance) < 0.01:
            flag = "match"
        elif variance < 0:
            flag = "discount"
        else:
            flag = "surcharge"

        guest = await session.get(Guest, b.guest_id)
        room = await session.get(Room, b.room_id) if b.room_id else None

        report.append({
            "booking_id": b.id,
            "booking_number": b.booking_number,
            "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "N/A",
            "room_number": room.number if room else "N/A",
            "room_type": rt.name if rt else "N/A",
            "nights": nights,
            "actual_rate": actual_rate,
            "standard_rate": standard_rate,
            "variance": variance,
            "variance_pct": variance_pct,
            "flag": flag,
            "arrival_date": b.arrival_date.isoformat() if b.arrival_date else None,
            "departure_date": b.departure_date.isoformat() if b.departure_date else None,
        })

    discounts = [r for r in report if r["flag"] == "discount"]
    surcharges = [r for r in report if r["flag"] == "surcharge"]

    return {
        "success": True,
        "report": report,
        "summary": {
            "total_checked_in": len(report),
            "matches": len(report) - len(discounts) - len(surcharges),
            "discounts": len(discounts),
            "surcharges": len(surcharges),
            "avg_variance_pct": round(sum(r["variance_pct"] for r in report) / len(report), 1) if report else 0,
        }
    }


# ─── GUEST EMAIL HINT (public, no JWT required) ───────────────────────────────
# Must be ABOVE /{booking_id} so FastAPI doesn't parse "guest-email-hint" as an ID


class GuestEmailHintResponse(BaseModel):
    message: Optional[str] = None
    profileCount: int = 0


@router.get("/guest-email-hint", response_model=GuestEmailHintResponse)
async def guest_email_hint(
    email: str = Query(..., min_length=3),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Return a non-PII hint when the email already has guest profiles.

    Used by the public booking form to show an inline warning *before*
    the booker submits.  No names or personal data are returned.
    """
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        return GuestEmailHintResponse(message=None, profileCount=0)

    count_result = await session.exec(
        select(func.count()).select_from(Guest).where(Guest.email == normalized)
    )
    count = count_result.one()

    if count >= 1:
        return GuestEmailHintResponse(
            message=(
                "This email is already associated with a guest profile. "
                "If you are a different person, your booking will be linked "
                "to a separate profile."
            ),
            profileCount=count,
        )
    return GuestEmailHintResponse(message=None, profileCount=0)


# ─── GUEST LAST STAY SUMMARY (public, no JWT required) ────────────────────────

async def _get_last_stay_summary(session: AsyncSession, normalized_email: str) -> dict:
    """Shared helper: build a one-line last-stay summary for a guest email.

    Returns {"summary": str|None, "hasStay": bool}.
    """
    guest_ids_result = await session.exec(
        select(Guest.id).where(Guest.email == normalized_email)
    )
    guest_ids = list(guest_ids_result.all())
    if not guest_ids:
        return {"summary": None, "hasStay": False}

    # Prefer checked-out bookings, fall back to any non-cancelled
    last_booking = (await session.exec(
        select(Booking).where(
            and_(
                Booking.guest_id.in_(guest_ids),
                Booking.status == "checked_out",
            )
        ).order_by(Booking.departure_date.desc()).limit(1)
    )).first()

    if not last_booking:
        last_booking = (await session.exec(
            select(Booking).where(
                and_(
                    Booking.guest_id.in_(guest_ids),
                    Booking.status.notin_(["cancelled", "no_show"]),
                )
            ).order_by(Booking.departure_date.desc()).limit(1)
        )).first()

    # Also check legacy Reservation table
    last_reservation = (await session.exec(
        select(Reservation).where(
            and_(
                Reservation.guest_id.in_(guest_ids),
                Reservation.status.notin_(["cancelled", "no_show"]),
            )
        ).order_by(Reservation.departure_date.desc()).limit(1)
    )).first()

    # Pick the more recent one
    stay = None
    if last_booking and last_reservation:
        stay = last_booking if last_booking.departure_date >= last_reservation.departure_date else last_reservation
    elif last_booking:
        stay = last_booking
    elif last_reservation:
        stay = last_reservation

    if not stay:
        return {"summary": None, "hasStay": False}

    # Build one-liner matching format:
    # "Last stay: 1 night | 30 Mar 2026 - 31 Mar 2026 | Minimalist Studio | INR 4,095"
    room_type_name = "Room"
    rt_id = getattr(stay, "room_type_id", None)
    if rt_id:
        rt = await session.get(RoomType, rt_id)
        if rt:
            room_type_name = rt.name

    arr = stay.arrival_date
    dep = stay.departure_date
    nights = (dep - arr).days if arr and dep else 0
    if nights < 1:
        nights = 1

    # Use f-string with .day to avoid platform-specific strftime (%-d fails on Windows)
    arr_str = f"{arr.day} {arr.strftime('%b %Y')}" if arr else "unknown"
    dep_str = f"{dep.day} {dep.strftime('%b %Y')}" if dep else "unknown"

    total = getattr(stay, "total_price", None) or getattr(stay, "total_amount", None) or 0
    total_str = f"INR {total:,.0f}" if total else ""

    parts = [
        f"Last stay: {nights} night{'s' if nights != 1 else ''}",
        f"{arr_str} - {dep_str}",
        room_type_name,
    ]
    if total_str:
        parts.append(total_str)

    summary = " | ".join(parts)

    return {"summary": summary, "hasStay": True}


# ─── GUEST PHONE LOOKUP (staff, requires JWT) ─────────────────────────────────

class GuestPhoneLookupResponse(BaseModel):
    found: bool = False
    guest: Optional[dict] = None


@router.get("/guest-phone-lookup")
async def guest_phone_lookup(
    phone: str = Query(..., min_length=6),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Look up a guest by phone number and return name + email for autofill.

    Strips non-digit characters for matching.  Returns the most recently
    updated guest when multiple rows share the same phone digits.
    """
    import re
    digits = re.sub(r'\D', '', phone.strip())
    if len(digits) < 6:
        return GuestPhoneLookupResponse(found=False)

    # Find guests whose stored phone contains these digits
    # (handles +91, spaces, dashes, etc.)
    all_guests = (await session.exec(
        select(Guest).order_by(Guest.updated_at.desc())
    )).all()

    matched = None
    for g in all_guests:
        if g.phone:
            stored_digits = re.sub(r'\D', '', g.phone)
            # Match if the last 10 digits are the same (handles country code differences)
            if len(stored_digits) >= 10 and len(digits) >= 10:
                if stored_digits[-10:] == digits[-10:]:
                    matched = g
                    break
            elif stored_digits == digits:
                matched = g
                break

    if not matched:
        return GuestPhoneLookupResponse(found=False)

    return GuestPhoneLookupResponse(
        found=True,
        guest={
            "id": matched.id,
            "fullName": f"{matched.first_name} {matched.last_name}".strip(),
            "firstName": matched.first_name,
            "lastName": matched.last_name,
            "email": matched.email,
            "phone": matched.phone,
        },
    )


class GuestLastStaySummaryResponse(BaseModel):
    summary: Optional[str] = None
    hasStay: bool = False


@router.get("/guest-last-stay-summary", response_model=GuestLastStaySummaryResponse)
async def guest_last_stay_summary(
    email: str = Query(..., min_length=3),
    session: AsyncSession = Depends(get_tenant_session),
):
    """Return a one-line last-stay summary for the given email.

    No PII is returned beyond the stay description.  Works without JWT
    (tenant resolved from X-Hotel-Code header).
    """
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        return GuestLastStaySummaryResponse()

    result = await _get_last_stay_summary(session, normalized)
    return GuestLastStaySummaryResponse(**result)


# ─── GUEST PROFILE SUMMARY (staff / admin) ────────────────────────────────────

class GuestProfileSummaryResponse(BaseModel):
    found: bool = False
    guest: Optional[dict] = None
    stats: Optional[dict] = None
    lastStay: Optional[dict] = None


@router.get("/guest-profile-summary", response_model=GuestProfileSummaryResponse)
async def guest_profile_summary(
    email: str = Query(..., min_length=3),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Return guest profile + stats + last-stay for staff use.

    Used by the admin booking modal to show returning-guest info and
    auto-fill name/phone.
    """
    normalized = email.strip().lower()
    if not normalized or "@" not in normalized:
        return GuestProfileSummaryResponse()

    # Find ALL guest rows sharing this email (multiple rows possible when
    # different names were used with the same email).
    all_guests = (await session.exec(
        select(Guest).where(Guest.email == normalized).order_by(Guest.updated_at.desc())
    )).all()

    if not all_guests:
        return GuestProfileSummaryResponse(found=False)

    # Use the most-recently-updated guest for profile display
    guest_obj = all_guests[0]
    all_guest_ids = [g.id for g in all_guests]

    # Count distinct stays across ALL guest IDs sharing this email.
    # Deduplicate by confirmation_code — the create_booking flow creates
    # both a Reservation and a Booking with the same confirmation_code,
    # and there can also be duplicate Booking rows. The guest profile
    # page uses the same deduplication approach.
    booking_rows = (await session.exec(
        select(Booking.confirmation_code).where(
            and_(
                Booking.guest_id.in_(all_guest_ids),
                Booking.status.notin_(["cancelled", "no_show"]),
            )
        )
    )).all()

    # Also check Reservation table for legacy stays not in Booking table
    reservation_rows = (await session.exec(
        select(Reservation.confirmation_code).where(
            and_(
                Reservation.guest_id.in_(all_guest_ids),
                Reservation.status.notin_(["cancelled", "no_show"]),
            )
        )
    )).all()

    # Unique confirmation codes = unique stays
    unique_codes = set()
    for code in booking_rows:
        if code:
            unique_codes.add(code)
    for code in reservation_rows:
        if code and code not in unique_codes:
            unique_codes.add(code)

    total_stays = len(unique_codes)

    last_stay = await _get_last_stay_summary(session, normalized)

    return GuestProfileSummaryResponse(
        found=True,
        guest={
            "id": guest_obj.id,
            "fullName": f"{guest_obj.first_name} {guest_obj.last_name}".strip(),
            "firstName": guest_obj.first_name,
            "lastName": guest_obj.last_name,
            "email": guest_obj.email,
            "phone": guest_obj.phone,
            "loyaltyTier": getattr(guest_obj, "loyalty_tier", None),
            "loyaltyPoints": getattr(guest_obj, "loyalty_points", None) or 0,
            "vipStatus": getattr(guest_obj, "vip_status", False),
            "lastVisit": guest_obj.last_visit.isoformat() if getattr(guest_obj, "last_visit", None) else None,
        },
        stats={"totalStays": total_stays},
        lastStay=last_stay,
    )


@router.get("/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get booking by ID"""
    import logging

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        logging.warning(f"Invalid booking ID format: {booking_id}")
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # Query the Booking table (not Reservation) to match list_bookings
    booking = await session.get(Booking, booking_id_int)
    if not booking:
        logging.warning(f"Booking not found: ID={booking_id_int}")
        raise HTTPException(status_code=404, detail="Booking not found")

    # Permission check - ensure user can only view their own bookings (unless admin)
    if not current_user.is_superuser and current_user.role != "admin":
        # Find guest by user email
        user_guest = (await session.exec(
            select(Guest).where(Guest.email == current_user.email)
        )).first()

        if not user_guest or booking.guest_id != user_guest.id:
            logging.warning(
                f"Unauthorized booking access: user={current_user.email}, "
                f"booking_id={booking_id_int}, booking_guest_id={booking.guest_id}"
            )
            raise HTTPException(status_code=403, detail="Not authorized to view this booking")

    guest = await session.get(Guest, booking.guest_id)
    if not guest:
        logging.error(f"Guest not found for booking: booking_id={booking_id_int}, guest_id={booking.guest_id}")
        raise HTTPException(status_code=404, detail="Guest not found")

    room = await session.get(Room, booking.room_id) if booking.room_id else None

    return await booking_to_response(booking, guest, room, session)


class UpdateBookingRequest(BaseModel):
    checkIn: Optional[str] = None
    checkOut: Optional[str] = None
    guests: Optional[dict] = None  # { adults: int, children: int }
    guestInfo: Optional[GuestInfo] = None
    roomId: Optional[str] = None
    specialRequests: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None  # Booking source (Website, Walk-in, Booking.com, Expedia, etc.)
    paymentStatus: Optional[str] = None
    paymentMethod: Optional[str] = None
    amountPaid: Optional[float] = None
    paymentNotes: Optional[str] = None
    # Sprint 6 fields
    expectedArrivalTime: Optional[str] = None
    expectedDepartureTime: Optional[str] = None
    accompanyingGuests: Optional[list] = None
    vipLevel: Optional[int] = None
    # Billing fields for frontend-calculated values
    basePrice: Optional[float] = None
    taxes: Optional[float] = None
    serviceFee: Optional[float] = None
    totalPrice: Optional[float] = None
    ratePerNight: Optional[float] = None
    balanceDue: Optional[float] = None
    corporateAccountId: Optional[int] = None


async def _sync_folio_on_date_change(
    session: AsyncSession,
    booking: Booking,
    current_user,
    original_departure: date,
):
    """Sync folio charges when booking dates change.

    When the checkout date is extended: add additional room charges for new nights
    When the checkout date is shortened: post credits for removed nights

    For GROUP BOOKINGS: applies credits/charges for ALL rooms in the group.
    """
    from app.services.billing_service import (
        get_effective_nightly_rate,
        create_room_charge_line_item,
    )
    from app.models.operations import Folio, FolioLineItem

    # Determine target booking for folio (parent for group bookings)
    target_booking_id = booking.id
    parent_booking = booking
    if booking.parent_booking_id:
        target_booking_id = booking.parent_booking_id
        parent_booking = await session.get(Booking, booking.parent_booking_id)
        if not parent_booking:
            parent_booking = booking

    # Find existing folio
    folio = (await session.exec(
        select(Folio).where(Folio.booking_id == target_booking_id)
    )).first()

    if not folio:
        logger.info(f"No folio found for booking {booking.id}, skipping sync")
        return

    # Get existing room charges (non-voided)
    existing_charges = (await session.exec(
        select(FolioLineItem).where(
            FolioLineItem.folio_id == folio.id,
            FolioLineItem.item_type == "room_charge",
            FolioLineItem.is_voided == False,
        )
    )).all()

    if not existing_charges:
        logger.info(f"No existing room charges in folio {folio.id}, skipping sync")
        return

    # Calculate original and new nights
    original_nights = max(1, (original_departure - booking.arrival_date).days)
    new_nights = booking.nights or max(1, (booking.departure_date - booking.arrival_date).days)

    if new_nights == original_nights:
        logger.info(f"No change in nights ({new_nights}), skipping sync")
        return

    # ─── GROUP BOOKING: Get all bookings in the group ────────────────────────────
    # For group bookings, we need to apply credits/charges for ALL rooms
    is_group = parent_booking.is_group_booking and parent_booking.group_booking_id
    bookings_to_sync = [booking]

    if is_group:
        group_bookings = (await session.exec(
            select(Booking).where(Booking.group_booking_id == parent_booking.group_booking_id)
        )).all()
        bookings_to_sync = group_bookings
        logger.info(f"Group booking date change: syncing {len(bookings_to_sync)} room(s)")

    # Track total credits for consolidated GST posting
    total_room_credit = 0.0
    total_room_charge = 0.0

    for bk in bookings_to_sync:
        # Get nightly rate for this specific booking
        nightly_rate = await get_effective_nightly_rate(session, bk)
        if nightly_rate <= 0 and bk.room_type_id:
            rt = await session.get(RoomType, bk.room_type_id)
            if rt and rt.base_price:
                nightly_rate = float(rt.base_price)
        if nightly_rate <= 0:
            nightly_rate = bk.base_price / max(1, original_nights) if bk.base_price else 1000.0

        # Get room info for description
        room_info = ""
        room_type_name = ""
        if bk.room_id:
            room_obj = await session.get(Room, bk.room_id)
            if room_obj:
                room_info = f"Room {room_obj.number} "
        if bk.room_type_id:
            rt = await session.get(RoomType, bk.room_type_id)
            if rt:
                room_type_name = rt.name

        room_label = f"{room_info}{room_type_name}".strip() or "Room"

        if new_nights > original_nights:
            # ─── EXTENSION: Add charges for additional nights ────────────────────
            additional_nights = new_nights - original_nights
            charge_amount = round(nightly_rate * additional_nights, 2)
            total_room_charge += charge_amount

            description = f"{room_label} – Extension {additional_nights} night(s) @ ₹{nightly_rate:.2f}/night"

            room_charge, tax_item = await create_room_charge_line_item(
                folio_id=folio.id,
                per_night_rate=nightly_rate,
                nights=additional_nights,
                posted_by=current_user.id,
                description=description,
                charge_date=booking.departure_date,
            )
            session.add(room_charge)
            session.add(tax_item)
            logger.info(f"Posted extension for {room_label}: ₹{charge_amount} + tax")

        else:
            # ─── SHORTENING: Post credits for removed nights ─────────────────────
            removed_nights = original_nights - new_nights
            credit_base = round(nightly_rate * removed_nights, 2)
            total_room_credit += credit_base

            # Post room credit (negative amount)
            room_credit = FolioLineItem(
                folio_id=folio.id,
                item_type="adjustment",
                description=f"{room_label} – Credit {removed_nights} night(s) @ ₹{nightly_rate:.2f}/night",
                quantity=removed_nights,
                unit_price=-nightly_rate,
                amount=-credit_base,
                posted_by=current_user.id,
                notes=f"Original checkout: {original_departure}, New checkout: {booking.departure_date}",
            )
            session.add(room_credit)
            logger.info(f"Posted credit for {room_label}: -₹{credit_base}")

    # Post consolidated GST credit/charge for the total
    if new_nights < original_nights and total_room_credit > 0:
        # Determine tax rate based on average nightly rate
        avg_rate = total_room_credit / (original_nights - new_nights) / len(bookings_to_sync) if bookings_to_sync else 3500
        tax_rate = 0.18 if avg_rate > 7500 else 0.12
        credit_tax = round(total_room_credit * tax_rate, 2)

        tax_credit = FolioLineItem(
            folio_id=folio.id,
            item_type="adjustment",
            description=f"GST credit @ {int(tax_rate * 100)}% on date change ({len(bookings_to_sync)} room(s))",
            quantity=1,
            unit_price=-credit_tax,
            amount=-credit_tax,
            posted_by=current_user.id,
            tax_rate_pct=tax_rate * 100,
            tax_amount=-credit_tax,
        )
        session.add(tax_credit)
        logger.info(f"Posted consolidated GST credit: -₹{credit_tax} for {len(bookings_to_sync)} room(s)")

    # Recalculate folio totals
    await session.flush()
    all_items = (await session.exec(
        select(FolioLineItem).where(
            FolioLineItem.folio_id == folio.id,
            FolioLineItem.is_voided == False,
        )
    )).all()

    # Gross charges (positive amounts)
    gross_charges = sum(li.amount for li in all_items if li.amount > 0)
    # Credits are negative adjustments that reduce the bill
    credits = sum(abs(li.amount) for li in all_items if li.amount < 0 and li.item_type == "adjustment")
    # Payments are actual money received
    payments = sum(abs(li.amount) for li in all_items if li.amount < 0 and li.item_type == "payment")

    # Net charges = gross - credits
    net_charges = gross_charges - credits

    folio.total_charges = round(net_charges, 2)
    folio.total_payments = round(payments, 2)
    folio.balance = round(net_charges - payments, 2)
    folio.updated_at = datetime.utcnow()

    await session.commit()
    logger.info(f"Folio {folio.id} synced: charges={folio.total_charges}, credits={folio.total_payments}, balance={folio.balance}")


@router.patch("/{booking_id}", response_model=BookingResponse)
async def update_booking(
    booking_id: str,
    payload: UpdateBookingRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a booking"""
    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # Query the Booking table (not Reservation) to match list_bookings
    booking = await session.get(Booking, booking_id_int)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Check permissions - only admin or the booking owner can update
    if not current_user.is_superuser and current_user.role != "admin":
        guest = (await session.exec(
            select(Guest).where(Guest.email == current_user.email)
        )).first()
        if not guest or booking.guest_id != guest.id:
            raise HTTPException(status_code=403, detail="Not authorized to update this booking")
    
    # Store original values for email notification
    original_arrival = booking.arrival_date
    original_departure = booking.departure_date
    original_total = booking.total_price or 0

    old_room_id = booking.room_id  # Capture before update for reassignment handling

    # Build update dict
    updates = {}

    if payload.checkIn:
        try:
            arrival = date.fromisoformat(payload.checkIn)
            if arrival < await get_business_date(session):
                raise HTTPException(status_code=400, detail="Check-in date cannot be in the past")
            updates["arrival_date"] = arrival
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid check-in date format")
    
    if payload.checkOut:
        try:
            departure = date.fromisoformat(payload.checkOut)
            if departure < (updates.get("arrival_date") or booking.arrival_date):
                raise HTTPException(status_code=400, detail="Check-out date cannot be before check-in date")
            updates["departure_date"] = departure
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid check-out date format")

    if payload.guests:
        adults = payload.guests.get("adults", booking.adults)
        children = payload.guests.get("children", booking.children)

        if adults < 1:
            raise HTTPException(status_code=400, detail="At least one adult guest is required")

        # Check room capacity if room is being updated
        room_id = booking.room_id
        if payload.roomId:
            try:
                room_id = int(payload.roomId)
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid room ID")
        
        # Note: Only adults count towards max_occupancy limit; children are allowed with adults
        if room_id:
            room = await session.get(Room, room_id)
            if room and adults > room.max_occupancy:
                raise HTTPException(
                    status_code=400,
                    detail=f"Number of adults ({adults}) exceeds room maximum occupancy ({room.max_occupancy})"
                )
        
        updates["adults"] = adults
        updates["children"] = children
    
    # Handle room assignment/unassignment
    # roomId can be: None (not provided), "null"/"" (unassign), or a valid room ID (assign)
    if payload.roomId is not None:
        # Check if this is an unassignment request (roomId is "null", "", or "0")
        if payload.roomId in ("null", "", "0", "none", "None"):
            # Allow unassignment for checked-in guests (room move scenario)
            if booking.status == "checked_in":
                logger.warning(f"Unassigning room from checked-in guest (booking {booking.id}) - room move in progress")
            # Unassign room from booking and update room status
            if booking.room_id:
                old_room = await session.get(Room, booking.room_id)
                if old_room:
                    # Set room to dirty/vacant when unassigned
                    old_room.status = "dirty"
                    old_room.occupancy_status = "vacant"
                    old_room.cleaning_status = "dirty"
                    old_room.updated_at = get_ist_now()
            updates["room_id"] = None
            logger.info(f"Room unassigned from booking {booking.id}")
        else:
            # DNM check: prevent room changes if booking is locked
            if booking.do_not_move and booking.room_id:
                # Allow the user who set DNM and admin/manager to override
                is_dnm_owner = booking.dnm_set_by == current_user.id
                is_manager = current_user.role in [
                    "admin", "manager", "general_manager", "front_office_manager",
                    "duty_manager", "reservation_manager",
                ] or current_user.is_superuser
                if not is_dnm_owner and not is_manager:
                    raise HTTPException(
                        status_code=403,
                        detail="Room assignment is locked (DNM - Do Not Move). Only the assigner or a manager can modify."
                    )

            # Date guard: cannot assign room to expired bookings
            today_date = await get_business_date(session)
            if booking.departure_date <= today_date:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot assign room to an expired booking (checkout date has passed)"
                )
            # Date guard: cannot assign room when arrival date is past and guest hasn't checked in
            if booking.arrival_date < today_date and booking.status not in ("checked_in",):
                raise HTTPException(
                    status_code=400,
                    detail="Cannot assign room to a past-date booking that has not been checked in"
                )

            try:
                room_id = int(payload.roomId)
                room = await session.get(Room, room_id)
                if not room:
                    raise HTTPException(status_code=404, detail="Room not found")

                # Validate room status - dirty/occupied rooms cannot be assigned
                if room.status not in ["available", "clean", "inspected"]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Room {room.number} is not available for assignment (status: {room.status}). "
                               f"Only rooms with status 'available', 'clean', or 'inspected' can be assigned."
                    )

                # Allow room type changes (upgrades/downgrades) with logging
                if booking.room_type_id and room.room_type_id != booking.room_type_id:
                    booked_type = await session.get(RoomType, booking.room_type_id)
                    assigned_type = await session.get(RoomType, room.room_type_id)
                    booked_name = booked_type.name if booked_type else "Unknown"
                    assigned_name = assigned_type.name if assigned_type else "Unknown"
                    logger.info(f"Room type change for booking {booking.id}: {booked_name} -> {assigned_name} (Room {room.number})")
                    # Update booking's room_type_id to match the assigned room
                    booking.room_type_id = room.room_type_id

                # 1) Room conflict: is this room already assigned to another active booking
                #    with overlapping dates?
                conflict = (await session.exec(
                    select(Booking).where(and_(
                        Booking.room_id == room_id,
                        Booking.id != booking.id,
                        Booking.status.in_(["booked", "confirmed", "checked_in", "pending"]),
                        Booking.arrival_date < booking.departure_date,
                        Booking.departure_date > booking.arrival_date,
                    ))
                )).first()
                if conflict:
                    conflict_guest = await session.get(Guest, conflict.guest_id)
                    guest_name = f"{conflict_guest.first_name} {conflict_guest.last_name}" if conflict_guest else "another guest"
                    raise HTTPException(
                        status_code=409,
                        detail=f"Room {room.number} is already assigned to {guest_name} "
                               f"({conflict.arrival_date} to {conflict.departure_date}). "
                               f"Please choose a different room or adjust the dates."
                    )

                # Guest-level conflict removed: same guest can have multiple reservations
                # with different rooms (e.g., booking for family, upgrades, etc.)
                # Room-level conflict check above already prevents double-booking the same room.

                updates["room_id"] = room_id
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid room ID")

    if payload.specialRequests is not None:
        updates["special_requests"] = payload.specialRequests.strip() if payload.specialRequests else None
    
    if payload.status:
        # Validate status transition
        valid_statuses = ["booked", "checked_in", "checked_out", "cancelled", "no_show"]
        if payload.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}")
        updates["status"] = payload.status

    # Handle booking source update
    if payload.source:
        # Map frontend source names to backend format
        source_reverse_map = {
            "Website": "direct",
            "Walk-in": "walk_in",
            "Booking.com": "booking_com",
            "Expedia": "expedia",
            "Airbnb": "airbnb",
            "Phone": "phone",
            "Email": "email",
            "Travel Agent": "travel_agent",
            "Corporate": "corporate",
            "Other": "other"
        }
        backend_source = source_reverse_map.get(payload.source, payload.source.lower().replace(" ", "_"))
        updates["booking_source"] = backend_source

    # Update guest info if provided
    if payload.guestInfo:
        guest = await session.get(Guest, booking.guest_id)
        if guest:
            if payload.guestInfo.firstName:
                guest.first_name = payload.guestInfo.firstName.strip()
            if payload.guestInfo.lastName:
                guest.last_name = payload.guestInfo.lastName.strip()
            if payload.guestInfo.email:
                guest.email = payload.guestInfo.email.strip().lower()
            if payload.guestInfo.phone:
                guest.phone = payload.guestInfo.phone.strip()
            if payload.guestInfo.country:
                guest.country = payload.guestInfo.country.strip()
            session.add(guest)

        # Also handle special requests from guestInfo
        if payload.guestInfo.specialRequests is not None:
            updates["special_requests"] = payload.guestInfo.specialRequests.strip() if payload.guestInfo.specialRequests else None

    # Handle payment fields — frontend sends camelCase, map to model fields
    if payload.amountPaid is not None:
        updates["deposit_amount"] = payload.amountPaid
        updates["balance_due"] = max(0, round((booking.total_price or 0) - payload.amountPaid, 2))
    if payload.paymentStatus is not None:
        updates["payment_status"] = payload.paymentStatus
    if payload.paymentMethod is not None:
        updates["payment_method"] = payload.paymentMethod
    # payment_notes: accepted from frontend but not persisted (no DB column)

    # Sprint 6: ETA/ETD + accompanying guests + VIP
    if payload.expectedArrivalTime is not None:
        updates["expected_arrival_time"] = payload.expectedArrivalTime
    if payload.expectedDepartureTime is not None:
        updates["expected_departure_time"] = payload.expectedDepartureTime
    if payload.accompanyingGuests is not None:
        import json as _json
        updates["accompanying_guests"] = _json.dumps(payload.accompanyingGuests) if isinstance(payload.accompanyingGuests, list) else payload.accompanyingGuests
    vip_changed = False
    if payload.vipLevel is not None:
        # Update guest VIP level
        guest_obj = await session.get(Guest, booking.guest_id)
        if guest_obj:
            guest_obj.vip_level = payload.vipLevel if payload.vipLevel > 0 else None
            guest_obj.vip_status = payload.vipLevel > 0
            booking.vip_flag = payload.vipLevel > 0
            vip_changed = True

    # Apply updates directly to the Booking model
    if updates or vip_changed:
        for key, value in updates.items():
            setattr(booking, key, value)

        # Recalculate nights if dates changed
        if "arrival_date" in updates or "departure_date" in updates:
            arrival = updates.get("arrival_date", booking.arrival_date)
            departure = updates.get("departure_date", booking.departure_date)
            booking.nights = max(1, (departure - arrival).days)  # Min 1 for day-use bookings

        # Recalculate total if dates changed OR room type changed (upgrade/downgrade)
        # Do NOT recalculate when just assigning a room of the same type — preserve original rate
        dates_changed = "arrival_date" in updates or "departure_date" in updates
        room_type_changed = False
        if "room_id" in updates and booking.room_id:
            new_room_obj = await session.get(Room, booking.room_id)
            if old_room_id:
                # Reassignment: check if old and new room have different types
                old_room_obj = await session.get(Room, old_room_id)
                room_type_changed = (
                    old_room_obj and new_room_obj and
                    old_room_obj.room_type_id != new_room_obj.room_type_id
                )
            else:
                # First assignment: check if assigned room type differs from booked type
                room_type_changed = (
                    new_room_obj and booking.room_type_id and
                    new_room_obj.room_type_id != booking.room_type_id
                )

        if dates_changed or room_type_changed:
            room = await session.get(Room, booking.room_id) if booking.room_id else None
            if room:
                rt = await session.get(RoomType, room.room_type_id)
                rt_name = rt.name if rt else "Standard Room"
                default_rp_id = await get_default_rate_plan_id(session)
                total, currency = await compute_total(
                    session,
                    rate_plan_id=default_rp_id,
                    arrival_date=booking.arrival_date,
                    departure_date=booking.departure_date,
                    room_type=rt_name
                )
                # Calculate taxes using billing_engine (single source of truth)
                per_night_rate = rt.base_price if rt else (total / max(1, booking.nights))
                charges = calculate_stay_charges(per_night_rate, booking.nights)
                booking.base_price = float(charges.base_amount)
                booking.nightly_rate = float(charges.nightly_rate)
                booking.tax_rate = float(charges.tax_rate)
                booking.taxes = float(charges.tax_amount)
                booking.service_fee = 0
                booking.total_price = float(charges.total_amount)
                # Recalculate balance_due and payment_status based on new total
                deposit = booking.deposit_amount or 0
                booking.balance_due = max(0, round(booking.total_price - deposit, 2))
                # Update payment_status if price changed and deposit no longer covers total
                if booking.balance_due > 0 and deposit > 0:
                    booking.payment_status = "partial"
                elif booking.balance_due > 0 and deposit == 0:
                    booking.payment_status = "pending"

        # Handle frontend-provided billing fields (override if explicitly provided)
        if payload.basePrice is not None:
            booking.base_price = payload.basePrice
        if payload.taxes is not None:
            booking.taxes = payload.taxes
        if payload.serviceFee is not None:
            booking.service_fee = payload.serviceFee
        if payload.totalPrice is not None:
            booking.total_price = payload.totalPrice
            # Recalculate balance_due when totalPrice changes
            deposit = booking.deposit_amount or 0
            booking.balance_due = max(0, round(booking.total_price - deposit, 2))
        if payload.balanceDue is not None:
            booking.balance_due = payload.balanceDue
        if payload.corporateAccountId is not None:
            booking.corporate_account_id = payload.corporateAccountId

        booking.updated_at = datetime.utcnow()
        session.add(booking)

        # CRITICAL: Sync room_id to Reservation table for consistency
        # Both Booking and Reservation tables need to have the same room_id
        if "room_id" in updates:
            # Find the corresponding Reservation record
            reservation_result = await session.exec(
                select(Reservation).where(
                    and_(
                        Reservation.guest_id == booking.guest_id,
                        Reservation.arrival_date == booking.arrival_date,
                        Reservation.departure_date == booking.departure_date
                    )
                )
            )
            reservation = reservation_result.first()
            if reservation:
                reservation.room_id = updates["room_id"]
                reservation.updated_at = datetime.utcnow()
                session.add(reservation)

        await session.commit()
        await session.refresh(booking)

        # Sync room status after commit
        if "room_id" in updates:
            new_room_id = updates["room_id"]
            assigned_room = await session.get(Room, new_room_id)
            if assigned_room:
                # Only set to "occupied" if guest is checked_in
                # For booked/confirmed status, set to "reserved" (guest hasn't arrived yet)
                if booking.status == "checked_in":
                    assigned_room.status = "occupied"
                    assigned_room.occupancy_status = "occupied"
                elif booking.status in ("booked", "confirmed", "pending"):
                    # Room is reserved but not yet occupied
                    assigned_room.occupancy_status = "reserved"
                    # Don't change room.status - keep it as available/clean/etc for housekeeping
                assigned_room.updated_at = datetime.utcnow()
                session.add(assigned_room)
            # Free old room on reassignment
            if old_room_id and old_room_id != new_room_id:
                old_room = await session.get(Room, old_room_id)
                if old_room and old_room.status == "occupied":
                    old_room.status = "dirty"
                    old_room.occupancy_status = "vacant"
                    old_room.cleaning_status = "dirty"
                    old_room.updated_at = datetime.utcnow()
                    session.add(old_room)
                elif old_room and old_room.occupancy_status == "reserved":
                    # Room was reserved but guest reassigned - free it
                    old_room.occupancy_status = "vacant"
                    old_room.updated_at = datetime.utcnow()
                    session.add(old_room)
            await session.commit()

    # Get updated guest and room
    guest = await session.get(Guest, booking.guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    room = await session.get(Room, booking.room_id) if booking.room_id else None

    # ─── SYNC FOLIO WHEN DATES CHANGE ─────────────────────────────────────────────
    # When check-in or check-out dates change, the folio charges must be adjusted
    # to match the new booking total. This ensures the folio is always accurate.
    if "arrival_date" in updates or "departure_date" in updates:
        logger.info(f"Dates changed for booking {booking.id}: syncing folio charges")
        await _sync_folio_on_date_change(session, booking, current_user, original_departure)

    # Send modification email if dates were changed (non-blocking)
    if ("arrival_date" in updates or "departure_date" in updates) and guest.email:
        # Get room type name before adding to background task
        room_type_name = "Standard Room"
        if booking.room_type_id:
            room_type_obj = await session.get(RoomType, booking.room_type_id)
            if room_type_obj:
                room_type_name = room_type_obj.name

        new_total = booking.total_price or 0
        balance_amount = new_total - original_total

        from app.services.background_email import send_booking_modification_email_bg
        background_tasks.add_task(
            send_booking_modification_email_bg,
            to_email=guest.email,
            guest_name=f"{guest.first_name} {guest.last_name}",
            booking_number=booking.confirmation_code,
            room_type=room_type_name,
            original_check_in=original_arrival.strftime("%B %d, %Y"),
            original_check_out=original_departure.strftime("%B %d, %Y"),
            new_check_in=booking.arrival_date.strftime("%B %d, %Y"),
            new_check_out=booking.departure_date.strftime("%B %d, %Y"),
            original_total=original_total,
            new_total=new_total,
            balance_amount=balance_amount,
            currency="INR"
        )

    return await booking_to_response(booking, guest, room, session)


class CancelBookingRequest(BaseModel):
    reason: Optional[str] = None
    notes: Optional[str] = None


@router.post("/{booking_id}/cancel", response_model=BookingResponse)
async def cancel_booking(
    booking_id: str,
    payload: CancelBookingRequest = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Cancel a booking with full cleanup:
    - Release Redis lock if held
    - Update room status (dirty if checked in, clear assignment otherwise)
    - Process refund if applicable
    - Auto-book first waitlist entry if available
    - Send cancellation notification to guest
    """
    import logging

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # First, find the Booking record (consistent with list_bookings and get_booking)
    booking_record = await session.get(Booking, booking_id_int)
    if not booking_record:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Handle child booking cancellation - update parent totals
    parent_booking = None
    if booking_record.parent_booking_id:
        parent_booking = await session.get(Booking, booking_record.parent_booking_id)
        if parent_booking:
            # Subtract child booking's charges from parent
            child_base = booking_record.base_price or 0
            child_taxes = booking_record.taxes or 0
            child_total = booking_record.total_price or 0

            parent_booking.base_price = round((parent_booking.base_price or 0) - child_base, 2)
            parent_booking.taxes = round((parent_booking.taxes or 0) - child_taxes, 2)
            parent_booking.total_price = round((parent_booking.total_price or 0) - child_total, 2)
            parent_booking.balance_due = round((parent_booking.balance_due or 0) - child_total, 2)
            parent_booking.updated_at = datetime.utcnow()

            logging.info(
                f"Child booking {booking_record.id} cancellation: updated parent {parent_booking.id} "
                f"totals by -₹{child_total}"
            )

            # Post cancellation credit to parent folio
            try:
                from app.models.operations import Folio, FolioLineItem
                parent_folio = (await session.exec(
                    select(Folio).where(
                        Folio.booking_id == parent_booking.id,
                        Folio.status == "open"
                    )
                )).first()

                if parent_folio and child_total > 0:
                    room_desc = ""
                    if booking_record.room_id:
                        room_obj = await session.get(Room, booking_record.room_id)
                        room_desc = f" (Room {room_obj.number})" if room_obj else ""

                    # Post credit for room cancellation
                    credit_item = FolioLineItem(
                        folio_id=parent_folio.id,
                        item_type="adjustment",
                        description=f"Room cancellation credit{room_desc} – Booking #{booking_record.booking_number}",
                        quantity=1,
                        unit_price=-child_base,
                        amount=-child_base,
                        posted_by=current_user.id if current_user else None,
                        notes=f"Cancelled room removed from group",
                    )
                    session.add(credit_item)

                    # Post tax credit
                    if child_taxes > 0:
                        tax_credit_item = FolioLineItem(
                            folio_id=parent_folio.id,
                            item_type="tax",
                            description=f"Tax credit for cancelled room{room_desc}",
                            quantity=1,
                            unit_price=-child_taxes,
                            amount=-child_taxes,
                            posted_by=current_user.id if current_user else None,
                        )
                        session.add(tax_credit_item)

                    logging.info(f"Posted cancellation credit ₹{child_total} to parent folio {parent_folio.id}")
            except Exception as e:
                logging.error(f"Failed to post cancellation credit to parent folio: {e}")

    # Check permissions - only admin or the booking owner can cancel
    if not current_user.is_superuser and current_user.role != "admin":
        guest = (await session.exec(
            select(Guest).where(Guest.email == current_user.email)
        )).first()
        if not guest or booking_record.guest_id != guest.id:
            raise HTTPException(status_code=403, detail="Not authorized to cancel this booking")

    # Find the corresponding Reservation record by confirmation_code
    # (The cancellation service operates on Reservation)
    reservation = (await session.exec(
        select(Reservation).where(Reservation.confirmation_code == booking_record.confirmation_code)
    )).first()

    if not reservation:
        # If no Reservation exists, update Booking directly
        logging.warning(f"No Reservation found for Booking {booking_id_int}, updating Booking directly")
        booking_record.status = "cancelled"
        booking_record.cancelled_at = datetime.utcnow()
        booking_record.cancellation_reason = payload.reason if payload else "guest_cancelled"
        await session.commit()
        await session.refresh(booking_record)

        guest = await session.get(Guest, booking_record.guest_id)
        if not guest:
            raise HTTPException(status_code=404, detail="Guest not found")

        room = await session.get(Room, booking_record.room_id) if booking_record.room_id else None
        return await booking_to_response(booking_record, guest, room, session)

    # Get cancellation reason from payload or use default
    cancellation_reason = "guest_cancelled"
    if payload and payload.reason:
        cancellation_reason = payload.reason

    # Use enhanced cancellation service with room release and waitlist processing
    # Note: The service expects Reservation.id, not Booking.id
    from app.services.cancellation_service import cancel_booking_with_release

    result = await cancel_booking_with_release(
        session=session,
        booking_id=reservation.id,  # Use Reservation ID for the cancellation service
        cancellation_reason=cancellation_reason,
        refund_percentage=None,  # Uses config default (50%)
        notify_guest=True,
        process_waitlist=True
    )

    if result["success"]:
        reservation = result["reservation"]

        # Store cancellation notes if provided
        if payload and payload.notes:
            existing_notes = reservation.special_requests or ""
            reservation.special_requests = f"{existing_notes}\n[Cancellation notes]: {payload.notes}".strip()
            await session.commit()
            await session.refresh(reservation)

        # Log cancellation details
        logging.info(
            f"Booking {booking_id_int} cancelled: "
            f"room_released={result['room_released']}, "
            f"lock_released={result['lock_released']}, "
            f"refund={result['refund'] is not None}, "
            f"waitlist_converted={result['waitlist_converted']}"
        )

        # If waitlist was converted, log it
        if result["waitlist_converted"]:
            logging.info(f"Waitlist entry converted to reservation {result['waitlist_converted']}")
    else:
        # Reservation-level cancellation failed (already cancelled, checked out, or service error).
        # Fall back to directly updating the Reservation record.
        logging.warning(
            f"cancel_booking_with_release failed for Booking {booking_id_int} / Reservation {reservation.id}. "
            f"Falling back to direct update."
        )
        if reservation.status not in ("cancelled", "checked_out"):
            reservation.status = "cancelled"
            reservation.cancelled_at = datetime.utcnow()
            reservation.cancellation_reason = cancellation_reason
        if payload and payload.notes:
            existing_notes = reservation.special_requests or ""
            reservation.special_requests = f"{existing_notes}\n[Cancellation notes]: {payload.notes}".strip()

    # Always update the Booking record to keep it in sync
    booking_record.status = "cancelled"
    booking_record.cancelled_at = datetime.utcnow()
    booking_record.cancellation_reason = cancellation_reason
    if payload and payload.notes:
        existing_notes = booking_record.special_requests or ""
        booking_record.special_requests = f"{existing_notes}\n[Cancellation notes]: {payload.notes}".strip()
    await session.commit()
    await session.refresh(booking_record)

    guest = await session.get(Guest, booking_record.guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    # Room is already released and set to None in cancellation service
    room = None

    # Notify admins about the cancellation
    try:
        await notify_booking_cancelled(
            session=session,
            guest_name=f"{guest.first_name} {guest.last_name}",
            room_number="N/A",
            booking_id=booking_record.id,
            reason=cancellation_reason,
            guest_id=guest.id
        )
        await session.commit()
    except Exception as e:
        import logging
        logging.error(f"Failed to send cancellation notification: {str(e)}")

    # Return using booking_to_response for consistent ID format
    return await booking_to_response(booking_record, guest, room, session)


# ============== CHECK-IN / CHECK-OUT ENDPOINTS ==============

class CheckInRequest(BaseModel):
    room_id: Optional[int] = None  # Override assigned room (single room)
    room_ids: Optional[List[int]] = None  # For group bookings: list of room IDs to assign (deprecated)
    room_assignments: Optional[Dict[str, int]] = None  # For group bookings: {booking_id: room_id} mapping
    payment_confirmed: bool = True
    notes: Optional[str] = None
    id_type: Optional[str] = None          # passport, aadhaar, drivers_license, national_id
    id_number: Optional[str] = None
    id_verified: Optional[bool] = None
    id_verification_confidence: Optional[float] = None


class CheckOutRequest(BaseModel):
    early_checkout: bool = False
    late_checkout: bool = False
    force_checkout: bool = False
    notes: Optional[str] = None
    send_feedback_request: bool = True


def _send_checkin_email_background(
    guest_email: str,
    guest_name: str,
    booking_number: str,
    room_number: str,
    room_type: str,
    check_in_date: str,
    check_out_date: str,
    nights: int
):
    """Background task to send check-in welcome email (non-blocking)"""
    try:
        from app.services.email_service import get_email_service
        email_service = get_email_service()
        email_service.send_checkin_welcome_email(
            to_email=guest_email,
            guest_name=guest_name,
            booking_number=booking_number,
            room_number=room_number,
            room_type=room_type,
            check_in_date=check_in_date,
            check_out_date=check_out_date,
            nights=nights,
        )
        import logging
        logging.info(f"Sent check-in welcome email to {guest_email}")
    except Exception as e:
        import logging
        logging.error(f"Failed to send check-in welcome email: {e}")


@router.post("/{booking_id}/checkin", response_model=BookingResponse)
async def checkin_booking(
    booking_id: str,
    background_tasks: BackgroundTasks,
    payload: CheckInRequest = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Process check-in for a booking"""
    # Only staff/admin can check in guests
    allowed_roles = ["admin", "front_desk", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only front desk staff can process check-ins")

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # Use Booking model (not legacy Reservation) for consistency with list_bookings
    booking = await session.get(Booking, booking_id_int)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Also get legacy Reservation if it exists (for backward compatibility)
    reservation_result = await session.exec(
        select(Reservation).where(Reservation.confirmation_code == booking.confirmation_code)
    )
    reservation = reservation_result.first()

    # Validate status
    if booking.status == "checked_in":
        raise HTTPException(status_code=400, detail="Guest is already checked in")
    if booking.status in ["checked_out", "cancelled", "no_show"]:
        raise HTTPException(status_code=400, detail=f"Cannot check in - booking is {booking.status}")

    # Validate date (allow check-in on arrival date).
    # Always use the real calendar date — never the business date — so that a
    # drifted business date (e.g. after test audit runs) cannot unlock early check-ins.
    today = date.today()
    if booking.arrival_date > today:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot check in before arrival date. "
                   f"Arrival is on {booking.arrival_date}, today is {today}."
        )
    if booking.departure_date <= today:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot check in - booking has expired (checkout was {booking.departure_date}). Mark as No Show instead."
        )

    # ============== GROUP BOOKING CHECK-IN ==============
    # If this is a group booking, check-in all bookings in the group
    all_bookings_to_checkin = [booking]
    if booking.is_group_booking and booking.group_booking_id:
        # Get all bookings in this group
        group_bookings_result = await session.exec(
            select(Booking).where(
                and_(
                    Booking.group_booking_id == booking.group_booking_id,
                    Booking.id != booking.id,
                    Booking.status.notin_(["checked_in", "checked_out", "cancelled", "no_show"])
                )
            )
        )
        group_bookings = list(group_bookings_result.all())
        all_bookings_to_checkin.extend(group_bookings)
        logger.info(f"Group check-in: {len(all_bookings_to_checkin)} bookings in group {booking.group_booking_id}")

    # Validate room assignments for group bookings
    # Prefer room_assignments dict (booking_id -> room_id) over room_ids array for correct mapping
    room_assignments_map: Dict[int, int] = {}
    if payload and payload.room_assignments:
        # Use explicit booking_id -> room_id mapping (preferred)
        room_assignments_map = {int(k): v for k, v in payload.room_assignments.items()}
        logger.info(f"Group check-in using room_assignments: {room_assignments_map}")
    elif payload and payload.room_ids and len(payload.room_ids) > 0:
        # Legacy: array-based assignment (order-dependent, may cause issues)
        if len(payload.room_ids) != len(all_bookings_to_checkin):
            raise HTTPException(
                status_code=400,
                detail=f"Number of rooms ({len(payload.room_ids)}) must match number of bookings ({len(all_bookings_to_checkin)})"
            )
        for idx, bk in enumerate(all_bookings_to_checkin):
            room_assignments_map[bk.id] = payload.room_ids[idx]
        logger.info(f"Group check-in using legacy room_ids (converted): {room_assignments_map}")

    if room_assignments_map:
        # Validate all rooms upfront
        group_room_ids = [bk.room_id for bk in all_bookings_to_checkin if bk.room_id]
        group_booking_ids = [bk.id for bk in all_bookings_to_checkin]
        rooms_by_booking: Dict[int, Room] = {}

        for bk in all_bookings_to_checkin:
            room_id = room_assignments_map.get(bk.id)
            if not room_id:
                # Use existing room_id if not in assignments
                room_id = bk.room_id
            if not room_id:
                raise HTTPException(status_code=400, detail=f"No room assigned for booking {bk.id}")

            room = await session.get(Room, room_id)
            if not room:
                raise HTTPException(status_code=404, detail=f"Room ID {room_id} not found")
            # Skip room status check if room is already assigned to this group
            if room_id not in group_room_ids:
                if room.status not in ["available", "clean", "inspected"]:
                    raise HTTPException(status_code=400, detail=f"Room {room.number} is not available (status: {room.status})")

            # Check for booking conflicts (exclude bookings from same group)
            conflict = (await session.exec(
                select(Booking).where(and_(
                    Booking.room_id == room_id,
                    Booking.id != bk.id,
                    Booking.id.notin_(group_booking_ids),  # Exclude all bookings in this group
                    Booking.status.in_(["booked", "confirmed", "checked_in", "pending"]),
                    Booking.arrival_date < bk.departure_date,
                    Booking.departure_date > bk.arrival_date,
                ))
            )).first()
            if conflict:
                conflict_guest = await session.get(Guest, conflict.guest_id)
                guest_name = f"{conflict_guest.first_name} {conflict_guest.last_name}" if conflict_guest else "another guest"
                raise HTTPException(
                    status_code=409,
                    detail=f"Room {room.number} is already assigned to {guest_name} "
                           f"({conflict.arrival_date} to {conflict.departure_date})"
                )
            rooms_by_booking[bk.id] = room

        # Assign rooms and update statuses
        for bk in all_bookings_to_checkin:
            room = rooms_by_booking[bk.id]
            # Log room type changes
            if bk.room_type_id and room.room_type_id != bk.room_type_id:
                booked_type = await session.get(RoomType, bk.room_type_id)
                room_type_obj = await session.get(RoomType, room.room_type_id)
                logger.info(f"Room type change at check-in for booking {bk.id}: "
                           f"{booked_type.name if booked_type else 'Unknown'} -> {room_type_obj.name if room_type_obj else 'Unknown'} (Room {room.number})")
                bk.room_type_id = room.room_type_id

            bk.room_id = room.id
            bk.status = "checked_in"
            bk.check_in_date = get_ist_now()
            bk.updated_at = get_ist_now()

            room.status = "occupied"
            room.occupancy_status = "occupied"
            room.cleaning_status = "clean"
            room.updated_at = get_ist_now()

            logger.info(f"Group check-in: Booking {bk.id} assigned to room {room.number}")

    elif payload and payload.room_id:
        # Single room assignment (original logic)
        room = await session.get(Room, payload.room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Room not found")
        if room.status not in ["available", "clean", "inspected"]:
            raise HTTPException(status_code=400, detail=f"Room is not available (status: {room.status})")
        # Allow room type changes at check-in (upgrades/downgrades) with logging
        if booking.room_type_id and room.room_type_id != booking.room_type_id:
            booked_type = await session.get(RoomType, booking.room_type_id)
            room_type_obj = await session.get(RoomType, room.room_type_id)
            logger.info(f"Room type change at check-in for booking {booking.id}: "
                       f"{booked_type.name if booked_type else 'Unknown'} -> {room_type_obj.name if room_type_obj else 'Unknown'} (Room {room.number})")
            booking.room_type_id = room.room_type_id
        # Check for booking conflicts on the room (exclude bookings from same group)
        group_booking_ids = [bk.id for bk in all_bookings_to_checkin]
        conflict = (await session.exec(
            select(Booking).where(and_(
                Booking.room_id == payload.room_id,
                Booking.id != booking.id,
                Booking.id.notin_(group_booking_ids),  # Exclude all bookings in this group
                Booking.status.in_(["booked", "confirmed", "checked_in", "pending"]),
                Booking.arrival_date < booking.departure_date,
                Booking.departure_date > booking.arrival_date,
            ))
        )).first()
        if conflict:
            conflict_guest = await session.get(Guest, conflict.guest_id)
            guest_name = f"{conflict_guest.first_name} {conflict_guest.last_name}" if conflict_guest else "another guest"
            raise HTTPException(
                status_code=409,
                detail=f"Room {room.number} is already assigned to {guest_name} "
                       f"({conflict.arrival_date} to {conflict.departure_date})"
            )
        booking.room_id = payload.room_id

        # Update room status to occupied
        room.status = "occupied"
        room.occupancy_status = "occupied"
        room.cleaning_status = "clean"
        room.updated_at = get_ist_now()

        # Update booking status
        booking.status = "checked_in"
        booking.check_in_date = get_ist_now()

    else:
        # No room IDs provided - check if rooms are already assigned
        for bk in all_bookings_to_checkin:
            if not bk.room_id:
                raise HTTPException(status_code=400, detail=f"No room assigned to booking {bk.booking_number}")

            # Update room status
            room = await session.get(Room, bk.room_id)
            if room:
                room.status = "occupied"
                room.occupancy_status = "occupied"
                room.cleaning_status = "clean"
                room.updated_at = get_ist_now()

            bk.status = "checked_in"
            bk.check_in_date = get_ist_now()
            bk.updated_at = get_ist_now()

    # DNM is opt-in only — staff must explicitly set it via the DNM toggle.
    # Do NOT auto-enable on check-in; it blocks all room moves.
    if reservation:
        reservation.status = "checked_in"
        if hasattr(reservation, 'check_in_date'):
            reservation.check_in_date = get_ist_now()
        reservation.room_id = booking.room_id
        reservation.updated_at = get_ist_now()
    booking.updated_at = get_ist_now()

    if payload and payload.notes:
        existing_notes = booking.special_requests or ""
        booking.special_requests = f"{existing_notes}\n[Check-in note]: {payload.notes}".strip()

    # Get guest and update last visit
    guest = await session.get(Guest, booking.guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    guest.last_visit = get_ist_now()

    # Save ID verification data from check-in
    if payload and payload.id_type:
        guest.id_type = payload.id_type
    if payload and payload.id_number:
        guest.id_number = payload.id_number
    if payload and payload.id_verified is not None:
        guest.id_verified = payload.id_verified

    # Log check-in in history
    if reservation:
        history = ReservationHistory(
            reservation_id=reservation.id,
            action="checked_in",
            changed_by=current_user.id,
            old_value="booked",
            new_value="checked_in",
            notes=f"Checked in by {current_user.email}"
        )
        session.add(history)

    await session.commit()
    await session.refresh(booking)

    # ============== FOLIO & CHARGE POSTING ==============
    # For group bookings: ONE parent folio with ALL room charges
    # For single bookings: Standard single folio
    try:
        from app.models.operations import Folio, FolioLineItem, Payment
        from app.api.v1.folio import generate_folio_number, recalculate_folio
        from app.services.billing_service import (
            get_effective_nightly_rate,
            create_room_charge_line_item,
        )

        is_group = len(all_bookings_to_checkin) > 1

        # Determine parent booking (for groups, it's the main booking with is_group_booking=True)
        parent_booking = booking  # The booking being checked in is always the parent

        # Find or create the PARENT folio only
        existing_folio = (await session.exec(
            select(Folio).where(Folio.booking_id == parent_booking.id)
        )).first()

        existing_charges = []  # Initialize for scope
        if existing_folio:
            parent_folio = existing_folio
            # Check if charges already posted to this folio
            existing_charges = (await session.exec(
                select(FolioLineItem).where(
                    FolioLineItem.folio_id == parent_folio.id,
                    FolioLineItem.item_type == "room_charge",
                    FolioLineItem.is_voided == False,
                )
            )).all()
            if existing_charges:
                logger.info(f"Folio {parent_folio.id} already has {len(existing_charges)} charge(s), skipping charge posting")
        else:
            # Create new folio for PARENT booking only
            parent_folio = Folio(
                booking_id=parent_booking.id,
                reservation_id=reservation.id if reservation else None,
                folio_number=generate_folio_number(),
                window_label="A",
                folio_type="group_master" if is_group else "guest",
            )
            session.add(parent_folio)
            await session.flush()

        # If folio didn't already have charges, post them now
        if not existing_folio or not existing_charges:
            # Post ALL nights' room charges for ALL rooms to the PARENT folio
            check_in_date = parent_booking.check_in_date.date() if parent_booking.check_in_date else parent_booking.arrival_date
            charge_date_str = check_in_date.isoformat()

            for room_idx, bk in enumerate(all_bookings_to_checkin, start=1):
                # Get nightly rate for this specific booking
                nightly_rate = await get_effective_nightly_rate(session, bk)

                # Fallback rate logic
                if nightly_rate <= 0 and bk.room_type_id:
                    rt = await session.get(RoomType, bk.room_type_id)
                    if rt and rt.base_price:
                        nightly_rate = float(rt.base_price)

                if nightly_rate <= 0 and bk.room_id:
                    room_obj = await session.get(Room, bk.room_id)
                    if room_obj and room_obj.room_type_id:
                        rt = await session.get(RoomType, room_obj.room_type_id)
                        if rt and rt.base_price:
                            nightly_rate = float(rt.base_price)

                if nightly_rate <= 0:
                    nightly_rate = 1000.0  # Emergency fallback

                # Get total nights for this booking
                booking_nights = bk.nights or max(1, (bk.departure_date - bk.arrival_date).days)

                # Get room number and type for description
                room_number = "TBA"
                room_type_name = ""
                if bk.room_id:
                    room_obj = await session.get(Room, bk.room_id)
                    if room_obj:
                        room_number = room_obj.number
                        if room_obj.room_type_id:
                            rt_obj = await session.get(RoomType, room_obj.room_type_id)
                            room_type_name = rt_obj.name if rt_obj else ""
                elif bk.room_type_id:
                    rt_obj = await session.get(RoomType, bk.room_type_id)
                    room_type_name = rt_obj.name if rt_obj else ""

                # Build description - post ALL nights at check-in for consistency with booking total
                if is_group:
                    desc = f"Room {room_idx} ({room_number}) – {room_type_name} – {booking_nights} night(s) @ ₹{nightly_rate:.2f}/night"
                else:
                    desc = f"Room charges – {booking_nights} night(s) @ ₹{nightly_rate:.2f}/night ({bk.arrival_date} to {bk.departure_date})"

                # Post ALL nights charge to PARENT folio (matches booking total)
                room_charge, tax_item = await create_room_charge_line_item(
                    folio_id=parent_folio.id,
                    per_night_rate=nightly_rate,
                    nights=booking_nights,
                    posted_by=current_user.id,
                    description=desc,
                    charge_date=check_in_date,
                )
                session.add(room_charge)
                session.add(tax_item)
                logger.info(f"Posted {booking_nights} night(s) charge to parent folio {parent_folio.id}: {desc}")

            # Record deposit/payment on PARENT folio only (group total deposit)
            deposit_amt = parent_booking.deposit_amount or 0
            if deposit_amt and deposit_amt > 0:
                payment = Payment(
                    folio_id=parent_folio.id,
                    amount=deposit_amt,
                    method=parent_booking.payment_method or "card",
                    payment_type="deposit",
                    status="captured",
                    processed_by=current_user.id,
                )
                session.add(payment)
                await session.flush()

                session.add(FolioLineItem(
                    folio_id=parent_folio.id,
                    item_type="payment",
                    description=f"Deposit via {parent_booking.payment_method or 'card'}",
                    quantity=1,
                    unit_price=-deposit_amt,
                    amount=-deposit_amt,
                    posted_by=current_user.id,
                    reference_id=payment.id,
                ))
                logger.info(f"Recorded deposit ₹{deposit_amt} on parent folio {parent_folio.id}")

            await recalculate_folio(session, parent_folio)

        await session.commit()
        logger.info(f"Group check-in: Posted charges for {len(all_bookings_to_checkin)} room(s) to parent folio {parent_folio.id}")
    except Exception as e:
        import logging
        logging.error(f"Failed to auto-create folio on check-in: {str(e)}")

    # Auto-create pre-authorization hold at check-in
    try:
        from app.models.operations import AuthorizationHold, HotelConfig
        config = (await session.exec(select(HotelConfig))).first()
        hold_pct = config.incidental_hold_pct if config else 20.0
        nights = max(1, booking.nights or (booking.departure_date - booking.arrival_date).days)
        nightly_rate = (booking.base_price or 0) / nights if nights > 0 else 0
        hold_amount = round(nightly_rate * nights * hold_pct / 100, 2)

        if hold_amount > 0:
            import secrets as _secrets
            # Get primary folio
            primary_folio = (await session.exec(
                select(Folio).where(Folio.booking_id == booking.id).order_by(Folio.window_label)
            )).first()
            hold = AuthorizationHold(
                booking_id=booking.id,
                folio_id=primary_folio.id if primary_folio else None,
                hold_amount=hold_amount,
                card_last4=getattr(payload, 'card_last4', None) if payload else None,
                card_brand=getattr(payload, 'card_brand', None) if payload else None,
                authorization_code=f"AUTH-{_secrets.token_hex(4).upper()}",
                status="authorized",
                authorized_by=current_user.id,
                expires_at=datetime.utcnow() + timedelta(days=7),
                notes=f"Auto pre-auth at check-in ({hold_pct}% of room charges)",
            )
            session.add(hold)
            await session.commit()
    except Exception as e:
        import logging
        logging.error(f"Failed to create pre-auth hold at check-in: {str(e)}")

    # Notify admins about check-in
    try:
        await notify_guest_checkin(
            session=session,
            guest_name=f"{guest.first_name} {guest.last_name}",
            room_number=room.number if room else "N/A",
            booking_id=booking.id,
            guest_id=guest.id,
            room_id=room.id if room else None
        )
        await session.commit()
    except Exception as e:
        import logging
        logging.error(f"Failed to send check-in notification: {str(e)}")

    # Send welcome email to guest on check-in (non-blocking background task)
    if guest.email:
        # Get room type name before adding to background task
        room_type_name = "Standard Room"
        if booking.room_type_id:
            room_type_obj = await session.get(RoomType, booking.room_type_id)
            if room_type_obj:
                room_type_name = room_type_obj.name

        nights = max(1, (booking.departure_date - booking.arrival_date).days)

        # Queue email to be sent in background - doesn't block response
        background_tasks.add_task(
            _send_checkin_email_background,
            guest_email=guest.email,
            guest_name=f"{guest.first_name} {guest.last_name}",
            booking_number=booking.confirmation_code,
            room_number=room.number if room else "N/A",
            room_type=room_type_name,
            check_in_date=booking.arrival_date.strftime("%B %d, %Y"),
            check_out_date=booking.departure_date.strftime("%B %d, %Y"),
            nights=nights,
        )

    # Refresh objects that may have been expired by intermediate commits
    await session.refresh(booking)
    await session.refresh(guest)
    if room:
        await session.refresh(room)

    return await booking_to_response(booking, guest, room, session)


@router.post("/{booking_id}/checkout", response_model=BookingResponse)
async def checkout_booking(
    booking_id: str,
    background_tasks: BackgroundTasks,
    payload: CheckOutRequest = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Process check-out for a booking"""
    # Only staff/admin can check out guests
    allowed_roles = ["admin", "front_desk", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only front desk staff can process check-outs")

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # Use Booking model (not legacy Reservation) for consistency with list_bookings
    booking = await session.get(Booking, booking_id_int)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Also get legacy Reservation if it exists (for backward compatibility)
    reservation_result = await session.exec(
        select(Reservation).where(Reservation.confirmation_code == booking.confirmation_code)
    )
    reservation = reservation_result.first()

    # Validate status - make checkout idempotent (return success if already checked out)
    if booking.status == "checked_out":
        # Already checked out - return current state instead of error (idempotent)
        guest = await session.get(Guest, booking.guest_id)
        room = await session.get(Room, booking.room_id) if booking.room_id else None
        return await booking_to_response(booking, guest, room, session)
    if booking.status != "checked_in":
        raise HTTPException(status_code=400, detail=f"Cannot check out - guest is not checked in (status: {booking.status})")

    # Check if this is a child booking (part of multi-room group)
    from app.services.billing_service import is_child_booking, is_parent_booking, get_group_bookings

    is_child = is_child_booking(booking)
    is_parent = is_parent_booking(booking)

    # Payment validation — folio-level: all open folio windows must have balance = $0
    # Exceptions:
    # 1. Company folios linked to a corporate account (auto-routed to AR on checkout)
    # 2. Child bookings in a multi-room group (charges consolidated to parent)
    force_checkout = payload.force_checkout if payload else False

    # Child bookings skip payment validation - their charges are on the parent's folio
    if is_child:
        logger.info(f"Checkout: Booking {booking.id} is a child booking - skipping payment validation (charges on parent)")

    if not force_checkout and not is_child:
        from app.models.operations import Folio as FolioModel
        from app.services.billing_service import get_group_total_charges

        # For parent/group bookings, validate consolidated group balance
        if is_parent:
            group_totals = await get_group_total_charges(session, booking)
            group_balance = group_totals.get("total_balance", 0)

            if group_balance > 0:
                # Get breakdown by room for detailed error message
                group_bookings = await get_group_bookings(session, booking)
                room_balances = []
                for grp_booking in group_bookings:
                    grp_folios = (await session.exec(
                        select(FolioModel).where(
                            FolioModel.booking_id == grp_booking.id,
                            FolioModel.status == "open"
                        )
                    )).all()
                    room_balance = sum(f.balance or 0 for f in grp_folios)
                    if room_balance > 0:
                        room_balances.append({
                            "booking_id": grp_booking.id,
                            "booking_number": grp_booking.booking_number,
                            "room_number": grp_booking.room_number or "Unassigned",
                            "balance": round(room_balance, 2),
                        })

                raise HTTPException(
                    status_code=402,
                    detail={
                        "message": f"Group booking has outstanding balance of ₹{round(group_balance, 2)}",
                        "total_unsettled": round(group_balance, 2),
                        "room_count": group_totals.get("booking_count", 1),
                        "room_balances": room_balances,
                        "booking_id": booking.id,
                        "is_group": True,
                    }
                )
        else:
            # Regular (non-group) booking - check individual folio windows
            checkout_folios = (await session.exec(
                select(FolioModel).where(
                    FolioModel.booking_id == booking.id,
                    FolioModel.status == "open"
                )
            )).all()

            # Check for early checkout - calculate adjusted balance
            from datetime import date
            from app.services.billing_service import calculate_early_checkout_adjustment

            today = date.today()
            check_in_dt = booking.check_in_date.date() if booking.check_in_date else booking.arrival_date
            original_nights = booking.nights or max(1, (booking.departure_date - booking.arrival_date).days)
            actual_nights = max(1, (today - check_in_dt).days)
            is_early_checkout = actual_nights < original_nights

            # Calculate early checkout credit if applicable
            early_checkout_credit = 0.0
            if is_early_checkout:
                try:
                    adjustment = await calculate_early_checkout_adjustment(session, booking, today)
                    early_checkout_credit = adjustment.get("refund_amount", 0)
                    logger.info(f"Early checkout validation: {actual_nights}/{original_nights} nights, credit: ₹{early_checkout_credit}")
                except Exception as e:
                    logger.warning(f"Could not calculate early checkout credit: {e}")

            unsettled_windows = []
            total_unsettled = 0.0
            for f in checkout_folios:
                if f.balance <= 0:
                    continue
                # Company folios with a corporate account are exempt — they'll be routed to AR
                if f.folio_type == "company" and booking.corporate_account_id:
                    continue
                unsettled_windows.append({
                    "folio_id": f.id,
                    "window_label": f.window_label,
                    "folio_type": f.folio_type,
                    "balance": round(f.balance, 2),
                })
                total_unsettled += f.balance

            # For early checkout, reduce the unsettled amount by the credit that will be applied
            adjusted_unsettled = max(0, total_unsettled - early_checkout_credit)

            # Only block checkout if adjusted balance is positive
            if adjusted_unsettled > 0 and unsettled_windows:
                raise HTTPException(
                    status_code=402,
                    detail={
                        "message": "All folio windows must be settled before checkout",
                        "total_unsettled": round(adjusted_unsettled, 2),
                        "original_unsettled": round(total_unsettled, 2),
                        "early_checkout_credit": round(early_checkout_credit, 2) if is_early_checkout else 0,
                        "is_early_checkout": is_early_checkout,
                        "unsettled_windows": unsettled_windows,
                        "booking_id": booking.id,
                    }
                )

            # If early checkout credit covers the balance, log it
            if is_early_checkout and early_checkout_credit > 0 and total_unsettled > 0:
                logger.info(
                    f"Checkout allowed: Early checkout credit (₹{early_checkout_credit}) "
                    f"covers unsettled balance (₹{total_unsettled})"
                )

    # Update room status to dirty
    room = await session.get(Room, booking.room_id) if booking.room_id else None
    if room:
        room.status = "dirty"
        room.occupancy_status = "vacant"
        room.cleaning_status = "dirty"
        room.updated_at = get_ist_now()

        # Create housekeeping task
        try:
            from app.models.operations import HousekeepingTask
            task = HousekeepingTask(
                room_id=room.id,
                task_type="checkout_clean",
                priority="high",
                status="pending",
                notes=f"Checkout cleaning for room {room.number}",
            )
            session.add(task)
        except Exception as e:
            import logging
            logging.error(f"Failed to create housekeeping task: {e}")

    # Update booking status (and sync to legacy reservation if exists)
    booking.status = "checked_out"
    booking.check_out_date = get_ist_now()
    booking.updated_at = get_ist_now()

    # ============== EARLY CHECKOUT BILLING ADJUSTMENT ==============
    # Use unified billing service for consistent pricing across the system
    from app.services.billing_service import (
        calculate_billable_nights,
        calculate_early_checkout_adjustment,
        adjust_folio_for_early_checkout,
        get_effective_nightly_rate,
        calculate_room_charges,
    )

    check_in_date = booking.check_in_date.date() if booking.check_in_date else booking.arrival_date
    check_out_date = get_ist_now().date()
    original_nights = booking.nights or (booking.departure_date - booking.arrival_date).days
    original_departure = booking.departure_date

    # Calculate billable nights (minimum 1 night for same-day checkout)
    actual_nights, is_early_checkout = calculate_billable_nights(
        check_in_date, check_out_date, original_nights
    )

    if is_early_checkout:
        logger.info(f"Early checkout: Booking #{booking.id} stayed {actual_nights} of {original_nights} nights")

        # Get effective nightly rate BEFORE modifying booking
        nightly_rate = await get_effective_nightly_rate(session, booking)
        charges = calculate_room_charges(nightly_rate, actual_nights)

        # ============== APPLY FOLIO CREDITS FIRST (before modifying booking) ==============
        # This is critical: adjust_folio_for_early_checkout needs the ORIGINAL booking data
        # to correctly calculate the credit amount
        try:
            from app.models.operations import Folio, FolioLineItem
            from app.services.billing_service import recalculate_folio_totals

            # Determine target booking for folio lookup (parent for child bookings)
            target_booking_id = booking.id
            parent_booking = None
            if booking.parent_booking_id:
                parent_booking = await session.get(Booking, booking.parent_booking_id)
                if parent_booking:
                    target_booking_id = parent_booking.id
                    logger.info(f"Early checkout for child booking {booking.id}: adjustments go to parent booking {parent_booking.id}")

            # Find folios by target booking_id
            open_folios = list((await session.exec(
                select(Folio).where(
                    Folio.booking_id == target_booking_id,
                    Folio.status == "open"
                )
            )).all())

            # Also check via legacy reservation_id (same confirmation_code)
            if not open_folios and booking.confirmation_code:
                legacy_res = (await session.exec(
                    select(Reservation).where(
                        Reservation.confirmation_code == booking.confirmation_code
                    )
                )).first()
                if legacy_res:
                    open_folios = list((await session.exec(
                        select(Folio).where(
                            Folio.reservation_id == legacy_res.id,
                            Folio.status == "open"
                        )
                    )).all())

            # Calculate credit amounts directly here (don't rely on adjust_folio_for_early_checkout)
            unused_nights = original_nights - actual_nights
            credit_base = round(nightly_rate * unused_nights, 2)
            tax_rate = 0.18 if nightly_rate > 7500 else 0.12
            credit_tax = round(credit_base * tax_rate, 2)
            credit_total = round(credit_base + credit_tax, 2)

            logger.info(f"Early checkout credit: {unused_nights} nights × ₹{nightly_rate} = ₹{credit_base} + ₹{credit_tax} tax = ₹{credit_total}")

            for folio in open_folios:
                # Post CREDIT line item for unused room charges (negative amount)
                credit_description = (
                    f"Early checkout credit – {unused_nights} unused night(s) @ ₹{nightly_rate:.2f}/night "
                    f"(departed {check_out_date}, originally {original_departure})"
                )

                room_credit = FolioLineItem(
                    folio_id=folio.id,
                    item_type="adjustment",
                    description=credit_description,
                    quantity=unused_nights,
                    unit_price=-nightly_rate,
                    amount=-credit_base,  # Negative = credit
                    tax_rate_pct=tax_rate * 100,
                    tax_amount=-credit_tax,
                    tax_component_1_name="CGST",
                    tax_component_1_amount=round(-credit_tax / 2, 2),
                    tax_component_2_name="SGST",
                    tax_component_2_amount=round(-credit_tax / 2, 2),
                    posted_by=current_user.id,
                    notes=f"Early checkout: {original_nights} → {actual_nights} nights",
                )
                session.add(room_credit)

                # Post tax credit line item (negative amount)
                tax_credit = FolioLineItem(
                    folio_id=folio.id,
                    item_type="tax",
                    description=f"GST credit @ {tax_rate * 100:.0f}% – Early checkout adjustment",
                    quantity=1,
                    unit_price=-credit_tax,
                    amount=-credit_tax,  # Negative = credit
                    posted_by=current_user.id,
                )
                session.add(tax_credit)

                await session.flush()
                await recalculate_folio_totals(session, folio)

                logger.info(
                    f"Folio {folio.id} adjusted: Posted credit ₹{credit_total} for {unused_nights} unused nights. "
                    f"New balance: {folio.balance}"
                )

            # If this is a child booking, update parent booking totals
            if parent_booking and credit_total > 0:
                parent_booking.base_price = round((parent_booking.base_price or 0) - credit_base, 2)
                parent_booking.taxes = round((parent_booking.taxes or 0) - credit_tax, 2)
                parent_booking.total_price = round((parent_booking.total_price or 0) - credit_total, 2)
                parent_booking.balance_due = round((parent_booking.balance_due or 0) - credit_total, 2)
                parent_booking.updated_at = datetime.utcnow()
                logger.info(f"Updated parent booking {parent_booking.id} totals for early checkout: -₹{credit_total}")

        except Exception as folio_err:
            logger.error(f"Failed to adjust folio for early checkout: {folio_err}")
            import traceback
            traceback.print_exc()

        # NOW update the booking with new dates/nights (AFTER folio credits are posted)
        booking.departure_date = check_out_date
        booking.nights = actual_nights
        booking.base_price = charges["base_amount"]
        booking.taxes = charges["tax_amount"]
        booking.total_price = charges["total_amount"]

        logger.info(
            f"Early checkout pricing: {actual_nights} nights @ ₹{nightly_rate}/night = "
            f"₹{booking.base_price} + ₹{booking.taxes} tax = ₹{booking.total_price}"
        )

        # Add early checkout note
        existing_notes = booking.special_requests or ""
        early_note = f"[Early checkout]: Departed {check_out_date} (originally {original_departure}, {original_nights - actual_nights} night(s) early)"
        booking.special_requests = f"{existing_notes}\n{early_note}".strip()

    # ============== ENSURE MINIMUM CHARGES AT CHECKOUT ==============
    # Handle same-day checkout or checkout before night audit ran
    # If no room charges exist, post charges for billable nights (minimum 1 night)
    # This block MUST succeed - we cannot checkout without posting charges
    # For child bookings, charges go to the PARENT folio
    from app.models.operations import Folio, FolioLineItem
    from app.services.billing_service import (
        create_room_charge_line_item,
        recalculate_folio_totals,
    )

    # Determine target booking for folio lookup (parent for child bookings)
    checkout_target_booking_id = booking.id
    checkout_parent_booking = None
    if is_child and booking.parent_booking_id:
        checkout_parent_booking = await session.get(Booking, booking.parent_booking_id)
        if checkout_parent_booking:
            checkout_target_booking_id = checkout_parent_booking.id
            logger.info(f"Checkout for child booking {booking.id}: minimum charges go to parent booking {checkout_parent_booking.id}")

    # Try to find folio by target booking_id first
    primary_folio = (await session.exec(
        select(Folio).where(
            Folio.booking_id == checkout_target_booking_id,
            Folio.status == "open"
        )
    )).first()

    # If not found, try via legacy reservation (same confirmation_code)
    if not primary_folio and booking.confirmation_code:
        # Note: Reservation is already imported at top of file
        legacy_res = (await session.exec(
            select(Reservation).where(
                Reservation.confirmation_code == booking.confirmation_code
            )
        )).first()
        if legacy_res:
            primary_folio = (await session.exec(
                select(Folio).where(
                    Folio.reservation_id == legacy_res.id,
                    Folio.status == "open"
                )
            )).first()
            # Link folio to booking for future queries
            if primary_folio:
                primary_folio.booking_id = booking.id
                logger.info(f"Linked folio {primary_folio.id} to booking {booking.id}")

    # If still no folio, create one
    if not primary_folio:
        from app.api.v1.frontdesk import generate_folio_number
        primary_folio = Folio(
            booking_id=booking.id,
            reservation_id=booking.id,  # Use booking_id as fallback
            folio_number=generate_folio_number(),
            total_charges=0.0,
            total_payments=0.0,
            balance=0.0
        )
        session.add(primary_folio)
        await session.flush()
        logger.info(f"Created folio for booking {booking.id} at checkout")

    if primary_folio:
        # Check if any room charges exist (non-voided)
        existing_room_charges = (await session.exec(
            select(FolioLineItem).where(
                FolioLineItem.folio_id == primary_folio.id,
                FolioLineItem.item_type == "room_charge",
                FolioLineItem.is_voided == False,
            )
        )).all()

        if not existing_room_charges:
            # No charges posted yet - post charges for billable nights
            # This handles same-day checkout before night audit
            logger.info(f"No room charges found for booking {booking.id} at checkout - will post minimum charges")

            # Calculate billable nights (minimum 1 night for same-day checkout)
            billable_nights = max(1, actual_nights)

            # Get nightly rate - try multiple sources
            nightly_rate = await get_effective_nightly_rate(session, booking)

            # If rate is still 0, try to get from room type directly
            if nightly_rate <= 0 and booking.room_id:
                room_for_rate = await session.get(Room, booking.room_id)
                if room_for_rate and room_for_rate.room_type_id:
                    room_type_for_rate = await session.get(RoomType, room_for_rate.room_type_id)
                    if room_type_for_rate and room_type_for_rate.base_price:
                        nightly_rate = float(room_type_for_rate.base_price)
                        logger.info(f"Using room type base price as fallback: ₹{nightly_rate}")

            # If we still can't determine rate, log error but DON'T silently continue
            if nightly_rate <= 0:
                logger.error(
                    f"CRITICAL: Cannot determine nightly rate for booking {booking.id}. "
                    f"base_price={booking.base_price}, total_price={booking.total_price}, "
                    f"room_id={booking.room_id}, room_type_id={booking.room_type_id}"
                )
                # Use a minimum fallback rate to avoid 0 charges - better to overcharge than undercharge
                # This should never happen in production with proper data
                nightly_rate = 1000.0  # Minimum fallback rate
                logger.warning(f"Using emergency fallback rate of ₹{nightly_rate} for booking {booking.id}")

            logger.info(
                f"Posting checkout charges: {billable_nights} night(s) @ ₹{nightly_rate}/night "
                f"for booking {booking.id}"
            )

            # Post individual nightly charges (not bulk) for proper auditing
            # For child bookings, include room number in description
            from datetime import timedelta
            check_in_date = booking.check_in_date.date() if booking.check_in_date else booking.arrival_date
            total_base = 0.0
            total_tax = 0.0

            # Build room descriptor for child bookings
            room_desc = ""
            if is_child and booking.room_id:
                room_obj = await session.get(Room, booking.room_id)
                if room_obj:
                    room_desc = f" (Room {room_obj.number})"

            for night_idx in range(billable_nights):
                charge_date = check_in_date + timedelta(days=night_idx)
                charge_date_str = charge_date.isoformat()

                room_charge, tax_item = await create_room_charge_line_item(
                    folio_id=primary_folio.id,
                    per_night_rate=nightly_rate,
                    nights=1,
                    posted_by=current_user.id,
                    description=f"Room charge{room_desc} – {charge_date_str} @ ₹{nightly_rate:.2f}",
                    charge_date=charge_date,
                )
                session.add(room_charge)
                session.add(tax_item)
                total_base += room_charge.amount
                total_tax += tax_item.amount if tax_item else 0

            await session.flush()

            # Update booking totals to reflect actual charges
            booking.base_price = round(total_base, 2)
            booking.taxes = round(total_tax, 2)
            booking.total_price = round(total_base + total_tax, 2)
            booking.nights = billable_nights

            await recalculate_folio_totals(session, primary_folio)

            # If this is a child booking, also update parent booking totals
            if checkout_parent_booking:
                checkout_parent_booking.base_price = round((checkout_parent_booking.base_price or 0) + total_base, 2)
                checkout_parent_booking.taxes = round((checkout_parent_booking.taxes or 0) + total_tax, 2)
                checkout_parent_booking.total_price = round((checkout_parent_booking.total_price or 0) + total_base + total_tax, 2)
                checkout_parent_booking.balance_due = round((checkout_parent_booking.balance_due or 0) + total_base + total_tax, 2)
                checkout_parent_booking.updated_at = datetime.utcnow()
                logger.info(f"Updated parent booking {checkout_parent_booking.id} with minimum charges: +₹{total_base + total_tax}")

            logger.info(
                f"Checkout charges posted for booking {booking.id}: "
                f"{billable_nights} night(s), base=₹{booking.base_price}, tax=₹{booking.taxes}, total=₹{booking.total_price}"
            )

    # Sync booking payment fields with folio totals
    try:
        from app.models.operations import Folio
        all_booking_folios = (await session.exec(
            select(Folio).where(Folio.booking_id == booking.id)
        )).all()
        total_charges = sum(f.total_charges or 0 for f in all_booking_folios)
        total_payments = sum(f.total_payments or 0 for f in all_booking_folios)
        total_balance = sum(f.balance or 0 for f in all_booking_folios)

        booking.balance_due = max(0, round(total_balance, 2))
        if total_payments <= 0:
            booking.payment_status = "pending"
        elif total_balance <= 0:
            booking.payment_status = "paid"
        else:
            booking.payment_status = "partial"

        logger.info(f"Checkout: Booking #{booking.id} - balance due: ₹{booking.balance_due}, payment_status: {booking.payment_status}")

    except Exception as sync_err:
        logger.error(f"Failed to sync booking payment fields: {sync_err}")

    if reservation:
        reservation.status = "checked_out"
        if hasattr(reservation, 'check_out_date'):
            reservation.check_out_date = get_ist_now()
        reservation.updated_at = get_ist_now()
        # Sync early checkout changes to reservation
        if is_early_checkout:
            reservation.departure_date = booking.departure_date
            if hasattr(reservation, 'nights'):
                reservation.nights = booking.nights
            if hasattr(reservation, 'total_amount'):
                reservation.total_amount = booking.total_price
            reservation.special_requests = booking.special_requests

    if payload and payload.notes:
        existing_notes = booking.special_requests or ""
        booking.special_requests = f"{existing_notes}\n[Check-out note]: {payload.notes}".strip()
        if reservation:
            reservation.special_requests = booking.special_requests

    # Get guest
    guest = await session.get(Guest, booking.guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    # Log check-out in history
    if reservation:
        history = ReservationHistory(
            reservation_id=reservation.id,
            action="checked_out",
            changed_by=current_user.id,
            old_value="checked_in",
            new_value="checked_out",
            notes=f"Checked out by {current_user.email}"
        )
        session.add(history)

    # Auto-release pre-authorization holds at checkout
    try:
        from app.models.operations import AuthorizationHold
        active_holds = (await session.exec(
            select(AuthorizationHold).where(
                AuthorizationHold.booking_id == booking.id,
                AuthorizationHold.status == "authorized",
            )
        )).all()
        for h in active_holds:
            h.status = "released"
            h.released_at = datetime.utcnow()
            h.released_by = current_user.id
            h.release_reason = "checkout"
    except Exception as e:
        import logging
        logging.error(f"Failed to release pre-auth holds at checkout: {str(e)}")

    # Close all open folios on checkout — auto-route company folios to AR
    try:
        from app.models.operations import Folio
        from app.models.ar import ARAccount, ARPosting
        open_folios = (await session.exec(
            select(Folio).where(
                Folio.booking_id == booking.id,
                Folio.status == "open"
            )
        )).all()
        for f in open_folios:
            # If this is a company folio and booking has a corporate account, route balance to AR
            if (
                f.folio_type == "company"
                and booking.corporate_account_id
                and f.balance > 0
            ):
                try:
                    ar_result = await session.exec(
                        select(ARAccount).where(
                            ARAccount.corporate_account_id == booking.corporate_account_id,
                            ARAccount.status == "active",
                        )
                    )
                    ar = ar_result.first()
                    if ar:
                        new_balance = round(ar.current_balance + f.balance, 2)
                        ar_posting = ARPosting(
                            ar_account_id=ar.id,
                            booking_id=booking.id,
                            folio_id=f.id,
                            posting_type="charge",
                            amount=f.balance,
                            balance_after=new_balance,
                            description=f"Checkout transfer – Booking #{booking.booking_number}, Folio {f.folio_number}",
                            posted_by=current_user.id,
                            status="pending",
                        )
                        session.add(ar_posting)
                        ar.current_balance = new_balance
                        ar.updated_at = datetime.utcnow()
                except Exception as ar_err:
                    import logging
                    logging.error(f"Failed to route company folio to AR: {ar_err}")

            f.status = "closed"
            f.closed_at = datetime.utcnow()
            f.closed_by = current_user.id
    except Exception as e:
        import logging
        logging.error(f"Failed to close folios on checkout: {str(e)}")

    await session.commit()
    await session.refresh(booking)

    # Update guest stats
    # Use booking.nights which reflects actual nights stayed (updated by early checkout logic)
    nights = booking.nights or (booking.departure_date - booking.arrival_date).days
    guest.total_bookings = (guest.total_bookings or 0) + 1
    guest.total_spent = (guest.total_spent or 0) + (booking.total_price or 0)
    guest.total_nights = (guest.total_nights or 0) + nights
    guest.loyalty_points = int((guest.total_spent or 0) * 0.1)

    # Update VIP status based on loyalty points
    if guest.loyalty_points > 2000:
        guest.vip_status = True

    await session.commit()

    # Build response before email/notification (which may corrupt session)
    response = await booking_to_response(booking, guest, room, session)

    # Send heartwarming thank you email automatically on checkout (non-blocking)
    if guest.email:
        from app.core.config import settings
        from app.models.inventory import RoomType
        from app.services.background_email import send_checkout_thank_you_email_bg

        feedback_url = f"{settings.frontend_url}/feedback?bookingId={booking.id}"

        # Get room type name before adding to background task
        room_type_name = "Standard Room"
        if room and room.room_type_id:
            room_type_obj = await session.get(RoomType, room.room_type_id)
            if room_type_obj:
                room_type_name = room_type_obj.name

        loyalty_points_earned = int((booking.total_price or 0) * 0.1)
        actual_checkout = booking.check_out_date or booking.departure_date

        background_tasks.add_task(
            send_checkout_thank_you_email_bg,
            to_email=guest.email,
            guest_name=f"{guest.first_name} {guest.last_name}",
            booking_number=booking.confirmation_code,
            room_number=room.number if room else "N/A",
            room_type=room_type_name,
            check_in_date=booking.arrival_date.strftime("%B %d, %Y"),
            check_out_date=actual_checkout.strftime("%B %d, %Y"),
            nights_stayed=nights,
            total_spent=booking.total_price or 0,
            currency="INR",
            loyalty_points_earned=loyalty_points_earned,
            is_vip=guest.vip_status or False,
            feedback_url=feedback_url,
        )

    # Notify admins about check-out
    try:
        await notify_guest_checkout(
            session=session,
            guest_name=f"{guest.first_name} {guest.last_name}",
            room_number=room.number if room else "N/A",
            booking_id=booking.id,
            guest_id=guest.id,
            room_id=room.id if room else None
        )
        await session.commit()
    except Exception as e:
        import logging
        logging.error(f"Failed to send check-out notification: {str(e)}")
        await session.rollback()

    return response


@router.post("/{booking_id}/cancel-checkin")
async def cancel_checkin(
    booking_id: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Cancel a check-in and revert booking back to confirmed/arrival status.
    Frees the room and sets it to 'dirty' for housekeeping.
    """
    allowed_roles = ["admin", "front_desk", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only front desk staff can cancel check-ins")

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    booking = await session.get(Booking, booking_id_int)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.status != "checked_in":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel check-in - booking status is '{booking.status}', expected 'checked_in'"
        )

    # Date guard: cannot cancel check-in for expired bookings
    today = await get_business_date(session)
    if booking.departure_date <= today:
        raise HTTPException(status_code=400, detail="Cannot cancel check-in for an expired booking (checkout date has passed)")

    # Cancel Check-in is a same-day correction for a mistaken check-in, NOT a
    # way to undo a stay. Once the guest has spent a night in the room the stay
    # has really happened — reversing it would wipe an occupied night and make
    # the booking cancellable again. Those guests must be checked out instead.
    checkin_date = booking.check_in_date.date() if booking.check_in_date else booking.arrival_date
    if checkin_date < today:
        nights_stayed = (today - checkin_date).days
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot cancel check-in — the guest has been in-house for {nights_stayed} night(s) "
                f"since {checkin_date}. Use Check-out to end the stay."
            )
        )

    # Also get legacy Reservation
    reservation_result = await session.exec(
        select(Reservation).where(Reservation.confirmation_code == booking.confirmation_code)
    )
    reservation = reservation_result.first()

    # Release room — mark dirty for housekeeping and unassign from booking
    if booking.room_id:
        room = await session.get(Room, booking.room_id)
        if room:
            room.status = "dirty"
            room.occupancy_status = "vacant"
            room.cleaning_status = "dirty"
            room.updated_at = datetime.utcnow()

    # Clear room assignment from booking
    booking.room_id = None
    booking.status = "booked"
    booking.check_in_date = None
    booking.updated_at = datetime.utcnow()

    if reservation:
        reservation.room_id = None
        reservation.status = "booked"
        reservation.updated_at = datetime.utcnow()

    # Log in history
    if reservation:
        history = ReservationHistory(
            reservation_id=reservation.id,
            action="cancel_checkin",
            changed_by=current_user.id,
            old_value="checked_in",
            new_value="booked",
            notes=f"Check-in cancelled by {current_user.email}. Room unassigned."
        )
        session.add(history)

    await session.commit()

    guest = await session.get(Guest, booking.guest_id)
    room = None  # Room has been unassigned

    return await booking_to_response(booking, guest, room, session)


@router.post("/{booking_id}/no-show")
async def mark_no_show(
    booking_id: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Mark a booking as No Show. Frees the assigned room.
    Only allowed for confirmed/booked bookings where the arrival date has passed.
    """
    allowed_roles = ["admin", "front_desk", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only front desk staff can mark no-shows")

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    booking = await session.get(Booking, booking_id_int)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.status not in ["booked", "confirmed", "pending"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark as no-show — booking status is '{booking.status}'. "
                   f"Only confirmed/booked bookings can be marked as no-show."
        )

    today = await get_business_date(session)
    if booking.arrival_date > today:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark as no-show before arrival date ({booking.arrival_date})"
        )

    # Free the assigned room
    if booking.room_id:
        room = await session.get(Room, booking.room_id)
        if room and room.status == "occupied":
            room.status = "dirty"
            room.occupancy_status = "vacant"
            room.cleaning_status = "dirty"
            room.updated_at = datetime.utcnow()

    # Update booking status
    booking.status = "no_show"
    booking.updated_at = datetime.utcnow()

    # Sync legacy reservation
    reservation_result = await session.exec(
        select(Reservation).where(Reservation.confirmation_code == booking.confirmation_code)
    )
    reservation = reservation_result.first()
    if reservation:
        reservation.status = "no_show"
        reservation.updated_at = datetime.utcnow()

    # Log history
    try:
        history = ReservationHistory(
            reservation_id=reservation.id if reservation else booking.id,  # Fallback to booking_id
            booking_id=booking.id,
            action="no_show",
            changed_by=current_user.email,
            old_value="confirmed",
            new_value="no_show",
            notes=f"Marked as no-show by {current_user.email}"
        )
        session.add(history)
    except Exception:
        pass

    await session.commit()

    guest = await session.get(Guest, booking.guest_id)
    room_obj = await session.get(Room, booking.room_id) if booking.room_id else None
    return await booking_to_response(booking, guest, room_obj, session)


@router.post("/{booking_id}/reinstate", response_model=BookingResponse)
async def reinstate_booking(
    booking_id: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Reinstate a no-show or cancelled booking back to confirmed status.
    Only allowed for no_show and cancelled bookings where the departure date hasn't passed.
    """
    allowed_roles = ["admin", "front_desk", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only front desk staff can reinstate bookings")

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    booking = await session.get(Booking, booking_id_int)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.status not in ["no_show", "cancelled"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reinstate — booking status is '{booking.status}'. "
                   f"Only no-show or cancelled bookings can be reinstated."
        )

    today = await get_business_date(session)
    if booking.departure_date < today:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reinstate — departure date ({booking.departure_date}) has already passed."
        )

    old_status = booking.status
    booking.status = "confirmed"
    booking.updated_at = datetime.utcnow()

    # Sync legacy reservation
    reservation_result = await session.exec(
        select(Reservation).where(Reservation.confirmation_code == booking.confirmation_code)
    )
    reservation = reservation_result.first()
    if reservation:
        reservation.status = "confirmed"
        reservation.updated_at = datetime.utcnow()

    # Log history
    try:
        history = ReservationHistory(
            reservation_id=reservation.id if reservation else booking.id,  # Fallback to booking_id
            booking_id=booking.id,
            action="reinstated",
            changed_by=current_user.email,
            old_value=old_status,
            new_value="confirmed",
            notes=f"Reinstated from {old_status} by {current_user.email}"
        )
        session.add(history)
    except Exception:
        pass

    await session.commit()

    guest = await session.get(Guest, booking.guest_id)
    room_obj = await session.get(Room, booking.room_id) if booking.room_id else None
    return await booking_to_response(booking, guest, room_obj, session)


@router.get("/{booking_id}/invoice")
async def download_invoice(
    booking_id: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Generate and download invoice PDF for a booking"""
    from starlette.responses import StreamingResponse
    from app.services.pdf_service import generate_invoice_pdf
    from io import BytesIO

    try:
        bid = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    booking = await session.get(Booking, bid)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    guest = await session.get(Guest, booking.guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    room = await session.get(Room, booking.room_id) if booking.room_id else None
    room_type_obj = await session.get(RoomType, booking.room_type_id) if booking.room_type_id else None

    # Get hotel name from settings or fallback
    hotel_name = "Glimmora Hotel & Suites"
    try:
        from app.models.hotel import HotelSettings
        settings = (await session.exec(select(HotelSettings))).first()
        if settings and settings.hotel_name:
            hotel_name = settings.hotel_name
    except Exception:
        pass

    nights = booking.nights or (booking.departure_date - booking.arrival_date).days
    base_price = booking.base_price or 0
    taxes = booking.taxes or 0
    service_fee = booking.service_fee or 0
    total = booking.total_price or (base_price + taxes + service_fee)
    amount_paid = booking.deposit_amount or 0

    invoice_data = {
        "hotel_name": hotel_name,
        "booking_number": booking.confirmation_code,
        "guest_name": f"{guest.first_name} {guest.last_name}",
        "email": guest.email or "",
        "phone": guest.phone or "",
        "check_in": booking.arrival_date.strftime("%b %d, %Y"),
        "check_out": booking.departure_date.strftime("%b %d, %Y"),
        "nights": nights,
        "room_type": room_type_obj.name if room_type_obj else "Standard Room",
        "room_number": room.number if room else "N/A",
        "base_price": base_price,
        "taxes": taxes,
        "service_fee": service_fee,
        "total_amount": total,
        "payment_status": booking.payment_status or "pending",
        "payment_method": booking.payment_method or "card",
        "amount_paid": amount_paid,
        "balance_due": total - amount_paid,
        "invoice_date": datetime.utcnow().strftime("%B %d, %Y"),
        "currency": "₹",
    }

    pdf_bytes = generate_invoice_pdf(invoice_data)
    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="Failed to generate invoice PDF")

    filename = f"invoice-{booking.confirmation_code}.pdf"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


class RoomChangeRequest(BaseModel):
    new_room_id: int
    reason: Optional[str] = None
    price_adjustment: Optional[float] = None  # Manual override (if None, auto-calculate)
    skip_billing: bool = False  # If True, no charges added (complimentary move)


@router.post("/{booking_id}/room-change")
async def change_room(
    booking_id: str,
    payload: RoomChangeRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Change room for an active booking"""
    allowed_roles = ["admin", "front_desk", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only front desk staff can change rooms")

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # Use Booking model (not legacy Reservation) for consistency
    booking = await session.get(Booking, booking_id_int)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Also get legacy Reservation if it exists (for backward compatibility)
    reservation_result = await session.exec(
        select(Reservation).where(Reservation.confirmation_code == booking.confirmation_code)
    )
    reservation = reservation_result.first()

    if booking.status not in ["booked", "confirmed", "checked_in"]:
        raise HTTPException(status_code=400, detail=f"Cannot change room for {booking.status} booking")

    # Date guard: cannot change room for expired bookings — but allow for checked-in guests
    # (they may be overstaying or have extended their stay)
    today = await get_business_date(session)
    if booking.departure_date <= today and booking.status != "checked_in":
        raise HTTPException(status_code=400, detail="Cannot change room for an expired booking (checkout date has passed)")

    # Check new room availability
    new_room = await session.get(Room, payload.new_room_id)
    if not new_room:
        raise HTTPException(status_code=404, detail="New room not found")

    # Allow move to rooms that are available, clean, inspected, dirty, or being cleaned
    # Only block occupied, out_of_service, out_of_order rooms
    blocked_statuses = ["occupied", "out_of_service", "out_of_order", "maintenance"]
    if new_room.status in blocked_statuses:
        raise HTTPException(status_code=400, detail=f"New room is not available (status: {new_room.status})")

    # Check for booking conflicts on the new room
    conflict = (await session.exec(
        select(Booking).where(and_(
            Booking.room_id == payload.new_room_id,
            Booking.id != booking.id,
            Booking.status.in_(["booked", "confirmed", "checked_in", "pending"]),
            Booking.arrival_date < booking.departure_date,
            Booking.departure_date > booking.arrival_date,
        ))
    )).first()
    if conflict:
        conflict_guest = await session.get(Guest, conflict.guest_id)
        guest_name = f"{conflict_guest.first_name} {conflict_guest.last_name}" if conflict_guest else "another guest"
        raise HTTPException(
            status_code=409,
            detail=f"Room {new_room.number} is already assigned to {guest_name} "
                   f"({conflict.arrival_date} to {conflict.departure_date}). "
                   f"Please choose a different room."
        )

    # Get old room and room types for comparison
    old_room = await session.get(Room, booking.room_id) if booking.room_id else None
    old_room_type = await session.get(RoomType, old_room.room_type_id) if old_room and old_room.room_type_id else None
    new_room_type = await session.get(RoomType, new_room.room_type_id) if new_room.room_type_id else None

    # Get old room type from booking if old_room doesn't have it
    if not old_room_type and booking.room_type_id:
        old_room_type = await session.get(RoomType, booking.room_type_id)

    # Calculate pricing adjustment for remaining nights
    old_rate_per_night = float(old_room_type.base_price or 0) if old_room_type else 0
    new_rate_per_night = float(new_room_type.base_price or 0) if new_room_type else 0
    rate_difference = new_rate_per_night - old_rate_per_night

    # Get total nights from booking (most reliable source)
    total_nights = booking.nights or max(1, (booking.departure_date - booking.arrival_date).days)

    # Calculate remaining nights (from today onwards, not past nights)
    if booking.status == "checked_in":
        # Guest is staying - only charge for nights NOT YET STAYED
        # Days already stayed = today - arrival_date
        days_already_stayed = max(0, (today - booking.arrival_date).days)
        remaining_nights = max(0, total_nights - days_already_stayed)

        # If room change happens on same day as check-in, charge for all nights
        if days_already_stayed == 0:
            remaining_nights = total_nights
    else:
        # Booking not started - charge for full stay
        remaining_nights = total_nights

    # Determine change type based on price comparison
    change_type = "lateral"  # Default: same category move
    if rate_difference > 0:
        change_type = "upgrade"
    elif rate_difference < 0:
        change_type = "downgrade"

    # Check if reason indicates emergency (overrides price-based determination)
    reason_lower = (payload.reason or "").lower()
    if any(word in reason_lower for word in ["emergency", "urgent", "immediate", "safety", "maintenance issue"]):
        change_type = "emergency_relocation"

    # Calculate price adjustment with GST (using new room's rate for tax slab)
    from app.services.billing_engine import calculate_stay_charges

    calculated_adjustment = 0.0
    adjustment_base = 0.0
    adjustment_tax = 0.0
    tax_rate_pct = 0

    if rate_difference != 0 and remaining_nights > 0 and not payload.skip_billing:
        adjustment_base = rate_difference * remaining_nights

        # Calculate GST based on NEW room's nightly rate (determines tax slab)
        charges = calculate_stay_charges(new_rate_per_night, remaining_nights)
        tax_rate_pct = charges.tax.tax_rate_percent  # 12 or 18

        # Apply GST to the adjustment amount
        adjustment_tax = round(abs(adjustment_base) * float(charges.tax.tax_rate), 2)
        if adjustment_base < 0:
            adjustment_tax = -adjustment_tax  # Negative tax for downgrade credit

        calculated_adjustment = adjustment_base + adjustment_tax

    # Use manual price_adjustment if provided, otherwise use calculated
    final_adjustment = payload.price_adjustment if payload.price_adjustment is not None else calculated_adjustment

    # For complimentary moves or skip_billing, no adjustment
    if payload.skip_billing:
        final_adjustment = 0.0

    # CRITICAL: Validate room type matches what was booked (unless explicitly allowing type change)
    if booking.room_type_id and new_room.room_type_id != booking.room_type_id:
        # Allow room change with warning in notes, but update room_type_id to match
        booking.room_type_id = new_room.room_type_id
        if reservation:
            reservation.room_type_id = new_room.room_type_id
        # Add note about type change
        type_change_note = f"[Room type changed from '{old_room_type.name if old_room_type else 'Unknown'}' to '{new_room_type.name if new_room_type else 'Unknown'}']"
        existing_notes = booking.special_requests or ""
        booking.special_requests = f"{existing_notes}\n{type_change_note}".strip()

    # If guest is checked in, update room statuses
    if booking.status == "checked_in":
        if old_room:
            old_room.status = "dirty"
            old_room.occupancy_status = "vacant"
            old_room.cleaning_status = "dirty"
            old_room.updated_at = datetime.utcnow()
        new_room.status = "occupied"
        new_room.occupancy_status = "occupied"
        new_room.cleaning_status = "clean"
        new_room.updated_at = datetime.utcnow()

    # Update booking (and sync to legacy reservation)
    booking.room_id = payload.new_room_id
    if final_adjustment != 0:
        booking.total_price = (booking.total_price or 0) + final_adjustment
        booking.base_price = (booking.base_price or 0) + adjustment_base
        booking.taxes = (booking.taxes or 0) + adjustment_tax
    if reservation:
        reservation.room_id = payload.new_room_id
        if final_adjustment != 0:
            reservation.total_amount = (reservation.total_amount or 0) + final_adjustment

    if payload.reason:
        existing_notes = booking.special_requests or ""
        booking.special_requests = f"{existing_notes}\n[Room change]: {payload.reason}".strip()
        if reservation:
            reservation.special_requests = booking.special_requests

    booking.updated_at = datetime.utcnow()
    if reservation:
        reservation.updated_at = datetime.utcnow()

    # Add folio line item for the price adjustment (if any)
    folio_line_item = None
    if final_adjustment != 0:
        from app.models.operations import Folio, FolioLineItem

        # Get or create folio for this booking
        folio_result = await session.exec(
            select(Folio).where(
                Folio.booking_id == booking.id,
                Folio.status != "closed"
            )
        )
        folio = folio_result.first()

        if folio:
            # Create line item for room change adjustment
            if final_adjustment > 0:
                item_description = f"Room Upgrade: {old_room_type.name if old_room_type else 'Standard'} → {new_room_type.name if new_room_type else 'Unknown'} ({remaining_nights} night{'s' if remaining_nights != 1 else ''})"
                item_type = "room_charge"
            else:
                item_description = f"Room Downgrade Credit: {old_room_type.name if old_room_type else 'Standard'} → {new_room_type.name if new_room_type else 'Unknown'} ({remaining_nights} night{'s' if remaining_nights != 1 else ''})"
                item_type = "adjustment"

            # Create room charge/adjustment line item (base amount only, tax separate)
            folio_line_item = FolioLineItem(
                folio_id=folio.id,
                item_type=item_type,
                description=item_description,
                quantity=remaining_nights,
                unit_price=rate_difference,
                amount=adjustment_base,
                tax_rate_pct=tax_rate_pct,
                tax_amount=adjustment_tax,
                tax_component_1_name="CGST",
                tax_component_1_pct=tax_rate_pct / 2,
                tax_component_1_amount=round(adjustment_tax / 2, 2),
                tax_component_2_name="SGST",
                tax_component_2_pct=tax_rate_pct / 2,
                tax_component_2_amount=round(adjustment_tax / 2, 2),
                posted_at=datetime.utcnow(),
                posted_by=current_user.id,
                reference_id=f"ROOM_CHANGE_{booking.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                notes=f"Room change from {old_room.number if old_room else 'N/A'} to {new_room.number}. Reason: {payload.reason or 'Not specified'}",
            )
            session.add(folio_line_item)

            # Create SEPARATE tax line item (following billing_service.py pattern)
            # This prevents folio-repair from creating duplicate tax entries
            # Note: adjustment_tax already has the correct sign (negative for downgrades)
            # For downgrades (negative tax), use item_type="adjustment" so recalculate_folio counts it as credit
            if adjustment_tax != 0:
                tax_item_type = "tax" if adjustment_tax > 0 else "adjustment"
                tax_description = f"GST @ {tax_rate_pct}% on room {'upgrade' if final_adjustment > 0 else 'downgrade'}"
                tax_line_item = FolioLineItem(
                    folio_id=folio.id,
                    item_type=tax_item_type,
                    description=tax_description,
                    quantity=1,
                    unit_price=adjustment_tax,
                    amount=adjustment_tax,
                    tax_rate_pct=tax_rate_pct,
                    tax_amount=adjustment_tax,
                    tax_component_1_name="CGST",
                    tax_component_1_pct=tax_rate_pct / 2,
                    tax_component_1_amount=round(adjustment_tax / 2, 2),
                    tax_component_2_name="SGST",
                    tax_component_2_pct=tax_rate_pct / 2,
                    tax_component_2_amount=round(adjustment_tax / 2, 2),
                    posted_at=datetime.utcnow(),
                    posted_by=current_user.id,
                    reference_id=f"ROOM_CHANGE_TAX_{booking.id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
                    notes=f"Tax on room change: {item_description}",
                )
                session.add(tax_line_item)

            # Update folio totals
            from app.api.v1.folio import recalculate_folio, sync_booking_payment
            await session.flush()  # Ensure line items are saved
            await recalculate_folio(session, folio)
            await sync_booking_payment(session, booking)

    # Create a ScheduledRoomMove record so the move appears in Room Moves page
    from app.models.operations import ScheduledRoomMove
    room_move = ScheduledRoomMove(
        booking_id=booking.id,
        from_room_id=old_room.id if old_room else 0,
        to_room_id=payload.new_room_id,
        scheduled_date=today,
        move_reason=payload.reason or "Room move requested by staff",
        status="completed",
        moved_at=datetime.utcnow(),
        moved_by=current_user.id,
        created_by=current_user.id,
        notes=payload.reason,
    )
    session.add(room_move)

    # Create RoomChanges record for tracking room change history
    from app.models.bookings import RoomChanges

    # Determine reason category from common patterns
    reason_category = "other"
    if any(word in reason_lower for word in ["upgrade", "complimentary", "vip"]):
        reason_category = "upgrade"
    elif any(word in reason_lower for word in ["maintenance", "repair", "broken", "leak"]):
        reason_category = "maintenance"
    elif any(word in reason_lower for word in ["request", "preference", "view", "floor"]):
        reason_category = "guest_request"
    elif any(word in reason_lower for word in ["noise", "complaint", "issue"]):
        reason_category = "guest_complaint"
    elif any(word in reason_lower for word in ["overbooking", "overbook"]):
        reason_category = "overbooking"

    room_change_record = RoomChanges(
        reservation_id=booking.id,
        original_room_type_id=old_room.room_type_id if old_room else booking.room_type_id,
        original_room_id=old_room.id if old_room else None,
        new_room_type_id=new_room.room_type_id,
        new_room_id=new_room.id,
        change_type=change_type,
        reason_category=reason_category,
        reason=payload.reason,
        price_adjustment=final_adjustment,
        changed_by=current_user.id,
        changed_at=datetime.utcnow(),
        notes=f"Base: ₹{adjustment_base:.2f}, GST ({tax_rate_pct}%): ₹{adjustment_tax:.2f}, Total: ₹{final_adjustment:.2f}" if final_adjustment != 0 else payload.reason,
    )
    session.add(room_change_record)

    # Log to GuestActivityLog for comprehensive guest activity tracking
    from app.models.crm_extended import GuestActivityLog
    activity_metadata = {
        "original_room_id": old_room.id if old_room else None,
        "original_room_number": old_room.number if old_room else None,
        "original_room_type": old_room_type.name if old_room_type else None,
        "original_rate_per_night": old_rate_per_night,
        "new_room_id": new_room.id,
        "new_room_number": new_room.number,
        "new_room_type": new_room_type.name if new_room_type else None,
        "new_rate_per_night": new_rate_per_night,
        "change_type": change_type,
        "reason": payload.reason,
        "remaining_nights": remaining_nights,
        "base_adjustment": round(adjustment_base, 2),
        "tax_rate_pct": tax_rate_pct,
        "tax_amount": round(adjustment_tax, 2),
        "total_adjustment": round(final_adjustment, 2),
    }

    activity_log = GuestActivityLog(
        property_id=1,  # Default property for single-tenant mode
        guest_id=booking.guest_id,
        activity_type="room_change",
        description=f"Room changed from {old_room.number if old_room else 'N/A'} to {new_room.number} ({change_type})",
        related_entity_type="booking",
        related_entity_id=booking.id,
        activity_metadata=json.dumps(activity_metadata),
        platform="front_desk",
        timestamp=datetime.utcnow(),
    )
    session.add(activity_log)

    await session.commit()

    # Build pricing details response
    pricing_details = None
    if final_adjustment != 0:
        pricing_details = {
            "old_room_rate_per_night": old_rate_per_night,
            "new_room_rate_per_night": new_rate_per_night,
            "rate_difference_per_night": rate_difference,
            "remaining_nights": remaining_nights,
            "base_adjustment": round(adjustment_base, 2),
            "tax_rate_percent": tax_rate_pct,
            "tax_amount": round(adjustment_tax, 2),
            "total_adjustment": round(final_adjustment, 2),
            "folio_line_item_id": folio_line_item.id if folio_line_item else None,
        }

    return {
        "message": "Room changed successfully",
        "booking_id": booking_id,
        "old_room": {
            "id": old_room.id if old_room else None,
            "number": old_room.number if old_room else None,
            "type": old_room_type.name if old_room_type else None,
            "rate_per_night": old_rate_per_night,
        },
        "new_room": {
            "id": new_room.id,
            "number": new_room.number,
            "type": new_room_type.name if new_room_type else None,
            "rate_per_night": new_rate_per_night,
        },
        "change_type": change_type,
        "reason": payload.reason,
        "room_change_id": room_change_record.id,
        "pricing": pricing_details,
        "new_booking_total": booking.total_price,
    }


@router.get("/{booking_id}/room-changes")
async def get_booking_room_changes(
    booking_id: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get all room changes for a specific booking"""
    from app.models.bookings import RoomChanges
    from app.schemas.reservations import RoomChangeResponse, BookingRoomChangesResponse

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # Get booking
    booking = await session.get(Booking, booking_id_int)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Get all room changes for this booking
    room_changes_result = await session.exec(
        select(RoomChanges)
        .where(RoomChanges.reservation_id == booking_id_int)
        .order_by(RoomChanges.changed_at.desc())
    )
    room_changes = room_changes_result.all()

    # Build response with room and user details
    room_change_responses = []
    for rc in room_changes:
        # Get original room details
        original_room = await session.get(Room, rc.original_room_id) if rc.original_room_id else None
        original_room_type = await session.get(RoomType, rc.original_room_type_id) if rc.original_room_type_id else None

        # Get new room details
        new_room = await session.get(Room, rc.new_room_id) if rc.new_room_id else None
        new_room_type = await session.get(RoomType, rc.new_room_type_id) if rc.new_room_type_id else None

        # Get staff who made the change
        changed_by_user = await session.get(User, rc.changed_by) if rc.changed_by else None

        room_change_responses.append(RoomChangeResponse(
            id=rc.id,
            reservation_id=rc.reservation_id,
            original_room_id=rc.original_room_id,
            original_room_number=original_room.number if original_room else None,
            original_room_type_name=original_room_type.name if original_room_type else None,
            new_room_id=rc.new_room_id,
            new_room_number=new_room.number if new_room else "Unknown",
            new_room_type_name=new_room_type.name if new_room_type else "Unknown",
            change_type=rc.change_type or "lateral",
            reason_category=rc.reason_category,
            reason=rc.reason,
            price_adjustment=rc.price_adjustment,
            changed_by=rc.changed_by,
            changed_by_name=changed_by_user.full_name or changed_by_user.email if changed_by_user else None,
            changed_at=rc.changed_at,
        ))

    return BookingRoomChangesResponse(
        booking_id=booking.id,
        confirmation_code=booking.confirmation_code,
        total_room_changes=len(room_change_responses),
        room_changes=room_change_responses,
    )


class ExtendStayRequest(BaseModel):
    new_checkout_date: str
    price_per_night: Optional[float] = None


@router.post("/{booking_id}/extend")
async def extend_stay(
    booking_id: str,
    payload: ExtendStayRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Extend a guest's stay"""
    allowed_roles = ["admin", "front_desk", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only front desk staff can extend stays")

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # Use Booking model (not legacy Reservation) for consistency
    booking = await session.get(Booking, booking_id_int)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Also get legacy Reservation if it exists (for backward compatibility)
    reservation_result = await session.exec(
        select(Reservation).where(Reservation.confirmation_code == booking.confirmation_code)
    )
    reservation = reservation_result.first()

    if booking.status != "checked_in":
        raise HTTPException(status_code=400, detail="Can only extend stay for checked-in guests")

    try:
        new_checkout = date.fromisoformat(payload.new_checkout_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format")

    if new_checkout <= booking.departure_date:
        raise HTTPException(status_code=400, detail="New checkout date must be after current checkout date")

    # Check room availability for extended dates
    room = await session.get(Room, booking.room_id)
    if room:
        # Check for conflicting reservations
        conflicts = (await session.exec(
            select(Reservation).where(
                and_(
                    Reservation.room_id == room.id,
                    Reservation.id != reservation.id,
                    Reservation.status.in_(["booked", "confirmed", "checked_in"]),
                    Reservation.arrival_date < new_checkout,
                    Reservation.departure_date > booking.departure_date
                )
            )
        )).all()

        if conflicts:
            raise HTTPException(
                status_code=400,
                detail="Room is not available for the extended dates - conflicts with other bookings"
            )

    # Calculate additional charges using billing_engine (single source of truth)
    from app.services.billing_engine import calculate_extension
    from app.services.billing_service import create_room_charge_line_item, recalculate_folio_totals
    from app.models.operations import Folio

    extra_nights = (new_checkout - booking.departure_date).days
    original_nights = (booking.departure_date - booking.arrival_date).days
    new_nights = original_nights + extra_nights

    # Use stored nightly_rate from booking (set at booking creation) for consistency
    if payload.price_per_night:
        price_per_night = payload.price_per_night
    elif booking.nightly_rate and booking.nightly_rate > 0:
        price_per_night = booking.nightly_rate
    elif booking.base_price and original_nights > 0:
        # Fallback: reverse calculate from base_price (without tax)
        price_per_night = booking.base_price / original_nights
    else:
        # Last resort: get from room type
        if booking.room_type_id:
            rt = await session.get(RoomType, booking.room_type_id)
            price_per_night = rt.base_price if rt and rt.base_price else 0
        else:
            price_per_night = 0

    # Calculate extension charges using billing_engine
    extension = calculate_extension(original_nights, new_nights, price_per_night)
    additional_charge = float(extension.delta_total)

    # Update reservation
    old_checkout = booking.departure_date
    booking.departure_date = new_checkout
    booking.nights = new_nights
    booking.base_price = float(extension.new_charges.base_amount)
    booking.taxes = float(extension.new_charges.tax_amount)
    booking.total_price = float(extension.new_charges.total_amount)
    booking.balance_due = max(0, float(extension.new_charges.total_amount) - (booking.deposit_amount or 0))
    booking.updated_at = datetime.utcnow()

    if reservation:
        reservation.departure_date = new_checkout
        reservation.total_amount = float(extension.new_charges.total_amount)
        reservation.updated_at = datetime.utcnow()
        reservation.updated_by = current_user.id

    # Post extension charges to folio
    # For child bookings, charges go to the PARENT folio
    target_booking_id = booking.id
    parent_booking = None
    if booking.parent_booking_id:
        parent_booking = await session.get(Booking, booking.parent_booking_id)
        if parent_booking:
            target_booking_id = parent_booking.id
            logger.info(f"Extension for child booking {booking.id}: charges will go to parent booking {parent_booking.id}")

    folio_result = await session.exec(
        select(Folio).where(Folio.booking_id == target_booking_id)
    )
    folio = folio_result.first()
    if folio:
        # Build description with room details for child bookings
        room_desc = ""
        if booking.parent_booking_id and booking.room_id:
            room_obj = await session.get(Room, booking.room_id)
            if room_obj:
                room_desc = f" (Room {room_obj.number})"

        extension_desc = f"Extended stay{room_desc} – {extra_nights} additional night(s) @ ₹{price_per_night:.2f}/night ({old_checkout.isoformat()} to {new_checkout.isoformat()})"
        room_charge, tax_item = await create_room_charge_line_item(
            folio_id=folio.id,
            per_night_rate=price_per_night,
            nights=extra_nights,
            posted_by=current_user.id,
            description=extension_desc,
            charge_date=old_checkout,
        )
        session.add(room_charge)
        session.add(tax_item)
        await recalculate_folio_totals(session, folio)

        # If this is a child booking, also update parent booking totals
        if parent_booking:
            additional_base = round(price_per_night * extra_nights, 2)
            additional_tax = round(additional_charge - additional_base, 2)
            parent_booking.base_price = round((parent_booking.base_price or 0) + additional_base, 2)
            parent_booking.taxes = round((parent_booking.taxes or 0) + additional_tax, 2)
            parent_booking.total_price = round((parent_booking.total_price or 0) + additional_charge, 2)
            parent_booking.balance_due = round((parent_booking.balance_due or 0) + additional_charge, 2)
            parent_booking.updated_at = datetime.utcnow()
            logger.info(f"Updated parent booking {parent_booking.id} totals: +₹{additional_charge}")

    # Add note
    existing_notes = booking.special_requests or ""
    booking.special_requests = f"{existing_notes}\n[Stay extended]: from {old_checkout} to {new_checkout}".strip()
    if reservation:
        reservation.special_requests = booking.special_requests

    await session.commit()

    return {
        "message": "Stay extended successfully",
        "booking_id": booking_id,
        "original_checkout": old_checkout.isoformat(),
        "new_checkout": new_checkout.isoformat(),
        "extra_nights": extra_nights,
        "additional_charge": round(additional_charge, 2),
        "new_total": round(booking.total_price, 2),
    }


# ============== SMART ROOM ASSIGNMENT ENDPOINTS ==============

class RoomRecommendation(BaseModel):
    room_id: int
    room_number: str
    floor: Optional[int] = None
    room_type: str
    bed_type: Optional[str] = None
    view_type: Optional[str] = None
    status: str
    is_accessible: bool = False
    is_smoking: bool = False
    match_score: float
    last_cleaned: Optional[str] = None


class RoomRecommendationsResponse(BaseModel):
    success: bool
    recommendations: List[RoomRecommendation]
    booking_id: str
    guest_preferences: Optional[dict] = None


class SmartAssignRequest(BaseModel):
    room_id: Optional[int] = None  # Specific room ID if manually selected
    preferences: Optional[dict] = None  # Guest preferences for auto-assignment


class SmartAssignResponse(BaseModel):
    success: bool
    room_id: int
    room_number: str
    room_type: str
    message: str


@router.get("/{booking_id}/room-recommendations", response_model=RoomRecommendationsResponse)
async def get_room_recommendations(
    booking_id: str,
    limit: int = Query(5, ge=1, le=20),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get AI-recommended rooms for a booking based on guest preferences and room scoring.

    The scoring algorithm considers:
    - Floor preference (+25 points)
    - View preference (+20 points)
    - Bed type preference (+20 points)
    - Room cleanliness status (+15 points for clean/inspected)
    - Accessibility needs (+10 points)
    - Quiet room preference (+10 points)
    - VIP status bonuses (+15-25 points)
    """
    import logging
    from app.services.room_assignment_service import get_room_recommendations as get_recommendations

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # Get the booking - try Booking first, then Reservation
    booking = await session.get(Booking, booking_id_int)
    reservation = None

    if booking:
        # Find corresponding reservation by confirmation code
        reservation = (await session.exec(
            select(Reservation).where(Reservation.confirmation_code == booking.confirmation_code)
        )).first()

    if not reservation:
        # Try direct reservation lookup
        reservation = await session.get(Reservation, booking_id_int)

    if not reservation:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Get guest preferences from pre-checkin or profile
    guest = await session.get(Guest, reservation.guest_id)
    preferences = {}

    if guest and guest.preferences:
        try:
            import json
            preferences = json.loads(guest.preferences) if isinstance(guest.preferences, str) else guest.preferences
        except (json.JSONDecodeError, TypeError):
            pass

    try:
        recommendations = await get_recommendations(session, reservation.id, preferences, limit)

        return RoomRecommendationsResponse(
            success=True,
            recommendations=[RoomRecommendation(**r) for r in recommendations],
            booking_id=booking_id,
            guest_preferences=preferences if preferences else None
        )
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Error getting room recommendations: {e}")
        raise HTTPException(status_code=500, detail="Failed to get room recommendations")


@router.post("/{booking_id}/smart-assign", response_model=SmartAssignResponse)
async def smart_assign_room(
    booking_id: str,
    payload: SmartAssignRequest = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Smart room assignment with AI-powered matching and Redis distributed locking.

    If room_id is provided, assigns that specific room (with validation).
    Otherwise, automatically selects the best room based on guest preferences.

    Features:
    - Conflict detection with existing reservations
    - Redis distributed locking to prevent race conditions
    - Guest preference matching (floor, view, bed type, accessibility)
    - VIP prioritization
    - Cleanliness status consideration
    """
    import logging
    from app.services.room_assignment_service import assign_room_smart

    # Only staff/admin can assign rooms
    allowed_roles = ["admin", "front_desk", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only front desk staff can assign rooms")

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # Get the booking - try Booking first, then Reservation
    booking_record = await session.get(Booking, booking_id_int)
    reservation = None

    if booking_record:
        # Find corresponding reservation by confirmation code
        reservation = (await session.exec(
            select(Reservation).where(Reservation.confirmation_code == booking_record.confirmation_code)
        )).first()

    if not reservation:
        # Try direct reservation lookup
        reservation = await session.get(Reservation, booking_id_int)

    # Allow booking-only cases (e.g., child bookings from group booking flow)
    if not reservation and not booking_record:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Checked-in restriction: only admin/manager can reassign rooms for checked-in bookings
    if booking_record and booking_record.status == "checked_in" and booking_record.room_id:
        is_manager = current_user.role in ["admin", "manager", "general_manager"] or current_user.is_superuser
        if not is_manager:
            raise HTTPException(
                status_code=403,
                detail="Checked-in rooms can only be reassigned by admin or manager."
            )

    # Date guard: cannot assign room to past-date bookings that aren't checked in
    today_date = await get_business_date(session)
    if booking_record:
        if booking_record.departure_date <= today_date:
            raise HTTPException(
                status_code=400,
                detail="Cannot assign room to an expired booking (checkout date has passed)"
            )
        if booking_record.arrival_date < today_date and booking_record.status not in ("checked_in",):
            raise HTTPException(
                status_code=400,
                detail="Cannot assign room to a past-date booking that has not been checked in"
            )

    # DNM check: prevent reassignment if booking is locked
    if booking_record and booking_record.do_not_move and booking_record.room_id:
        is_dnm_owner = booking_record.dnm_set_by == current_user.id
        is_manager = current_user.role in [
            "admin", "manager", "general_manager", "front_office_manager",
            "duty_manager", "reservation_manager",
        ] or current_user.is_superuser
        if not is_dnm_owner and not is_manager:
            raise HTTPException(
                status_code=403,
                detail="Room assignment is locked (DNM - Do Not Move). Only the assigner or a manager can modify."
            )

    # Get preferences from payload or guest profile
    preferences = {}
    if payload and payload.preferences:
        preferences = payload.preferences
    else:
        guest_id = reservation.guest_id if reservation else (booking_record.guest_id if booking_record else None)
        if guest_id:
            guest = await session.get(Guest, guest_id)
            if guest and guest.preferences:
                try:
                    import json
                    preferences = json.loads(guest.preferences) if isinstance(guest.preferences, str) else guest.preferences
                except (json.JSONDecodeError, TypeError):
                    pass

    try:
        room = None

        if reservation:
            # Use smart assignment service when we have a Reservation
            room = await assign_room_smart(
                session=session,
                reservation_id=reservation.id,
                preferences=preferences,
                requested_room_id=payload.room_id if payload else None,
                use_redis_lock=True
            )
        else:
            # Booking-only case (e.g., child bookings from group booking flow)
            # Do direct room assignment
            requested_room_id = payload.room_id if payload else None

            if requested_room_id:
                # Specific room requested - validate and assign
                room = await session.get(Room, requested_room_id)
                if not room:
                    raise HTTPException(status_code=404, detail="Room not found")

                # Validate room status
                if room.status not in ["available", "clean", "inspected", "vacant", "dirty"]:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Room {room.number} is not available for assignment (status: {room.status})"
                    )

                # Validate room type match (optional - allow different type but log it)
                if booking_record.room_type_id and room.room_type_id != booking_record.room_type_id:
                    booked_type = await session.get(RoomType, booking_record.room_type_id)
                    assigned_type = await session.get(RoomType, room.room_type_id)
                    logger.info(
                        f"Room type change for booking {booking_record.id}: "
                        f"{booked_type.name if booked_type else 'Unknown'} -> {assigned_type.name if assigned_type else 'Unknown'}"
                    )
            else:
                # Auto-assign: find best available room of the booking's room type
                room_type_id = booking_record.room_type_id
                if not room_type_id:
                    raise HTTPException(status_code=400, detail="Booking has no room type - cannot auto-assign")

                # Find available rooms of this type
                available_rooms = (await session.exec(
                    select(Room).where(
                        Room.room_type_id == room_type_id,
                        Room.status.in_(["available", "clean", "inspected", "vacant"])
                    ).order_by(Room.number)
                )).all()

                if not available_rooms:
                    room_type = await session.get(RoomType, room_type_id)
                    raise HTTPException(
                        status_code=400,
                        detail=f"No {room_type.name if room_type else 'matching'} rooms available"
                    )

                # Check for conflicts with existing bookings
                for candidate in available_rooms:
                    conflict = (await session.exec(
                        select(Booking).where(
                            Booking.room_id == candidate.id,
                            Booking.id != booking_record.id,
                            Booking.status.in_(["booked", "confirmed", "checked_in", "pending"]),
                            Booking.arrival_date < booking_record.departure_date,
                            Booking.departure_date > booking_record.arrival_date,
                        )
                    )).first()

                    if not conflict:
                        room = candidate
                        break

                if not room:
                    raise HTTPException(
                        status_code=400,
                        detail="All rooms of this type are booked for the selected dates"
                    )

            # Update room status
            if booking_record.status == "checked_in":
                room.status = "occupied"
                room.occupancy_status = "occupied"
            else:
                room.occupancy_status = "reserved"
            room.updated_at = datetime.utcnow()
            session.add(room)

        # Update the Booking record
        if booking_record:
            booking_record.room_id = room.id
            booking_record.updated_at = datetime.utcnow()
            session.add(booking_record)

        await session.commit()

        # Get room type name
        room_type_obj = await session.get(RoomType, room.room_type_id)
        room_type_name = room_type_obj.name if room_type_obj else "Standard Room"

        logging.info(f"Smart assignment: Room {room.number} assigned to booking {booking_id}")

        return SmartAssignResponse(
            success=True,
            room_id=room.id,
            room_number=room.number,
            room_type=room_type_name,
            message=f"Room {room.number} assigned successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Smart room assignment failed: {e}")
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to assign room: {str(e)}")


# ============== GROUP BOOKING AUTO-ASSIGN ==============

class GroupAssignResult(BaseModel):
    booking_id: int
    booking_number: str
    room_type: str
    success: bool
    room_id: Optional[int] = None
    room_number: Optional[str] = None
    error: Optional[str] = None


class GroupAutoAssignResponse(BaseModel):
    success: bool
    total_bookings: int
    assigned_count: int
    failed_count: int
    results: List[GroupAssignResult]
    message: str


@router.post("/{booking_id}/group-auto-assign", response_model=GroupAutoAssignResponse)
async def group_auto_assign_rooms(
    booking_id: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Auto-assign rooms to all bookings in a group.

    Takes a booking ID that belongs to a group and auto-assigns rooms to all
    bookings in that group that don't already have rooms assigned.

    Returns detailed results showing which bookings were assigned and which failed.
    """
    import logging
    from app.services.room_assignment_service import assign_room_smart

    # Only staff/admin can assign rooms
    allowed_roles = ["admin", "front_desk", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only front desk staff can assign rooms")

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # Get the booking
    booking = await session.get(Booking, booking_id_int)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Check if it's a group booking
    if not booking.is_group_booking or not booking.group_booking_id:
        raise HTTPException(status_code=400, detail="This is not a group booking")

    # Get all bookings in the group
    group_bookings_result = await session.exec(
        select(Booking).where(
            and_(
                Booking.group_booking_id == booking.group_booking_id,
                Booking.status.notin_(["checked_out", "cancelled", "no_show"])
            )
        ).order_by(Booking.id)
    )
    group_bookings = list(group_bookings_result.all())

    if not group_bookings:
        raise HTTPException(status_code=404, detail="No bookings found in group")

    results: List[GroupAssignResult] = []
    assigned_count = 0
    failed_count = 0

    for bk in group_bookings:
        # Get room type
        room_type = await session.get(RoomType, bk.room_type_id)
        room_type_name = room_type.name if room_type else "Standard"

        # Skip if already has a room assigned
        if bk.room_id:
            room = await session.get(Room, bk.room_id)
            results.append(GroupAssignResult(
                booking_id=bk.id,
                booking_number=bk.booking_number,
                room_type=room_type_name,
                success=True,
                room_id=bk.room_id,
                room_number=room.number if room else "Unknown",
                error=None
            ))
            assigned_count += 1
            continue

        # Find corresponding reservation
        reservation = (await session.exec(
            select(Reservation).where(Reservation.confirmation_code == bk.confirmation_code)
        )).first()

        if not reservation:
            # Create a minimal reservation for room assignment
            results.append(GroupAssignResult(
                booking_id=bk.id,
                booking_number=bk.booking_number,
                room_type=room_type_name,
                success=False,
                error="No reservation found for this booking"
            ))
            failed_count += 1
            continue

        try:
            # Get guest preferences
            preferences = {}
            guest = await session.get(Guest, bk.guest_id)
            if guest and guest.preferences:
                try:
                    import json
                    preferences = json.loads(guest.preferences) if isinstance(guest.preferences, str) else guest.preferences
                except (json.JSONDecodeError, TypeError):
                    pass

            # Auto-assign room
            room = await assign_room_smart(
                session=session,
                reservation_id=reservation.id,
                preferences=preferences,
                requested_room_id=None,
                use_redis_lock=True
            )

            # Update booking record
            bk.room_id = room.id
            bk.updated_at = datetime.utcnow()
            session.add(bk)

            results.append(GroupAssignResult(
                booking_id=bk.id,
                booking_number=bk.booking_number,
                room_type=room_type_name,
                success=True,
                room_id=room.id,
                room_number=room.number,
                error=None
            ))
            assigned_count += 1
            logging.info(f"Group auto-assign: Room {room.number} assigned to booking {bk.id}")

        except HTTPException as e:
            results.append(GroupAssignResult(
                booking_id=bk.id,
                booking_number=bk.booking_number,
                room_type=room_type_name,
                success=False,
                error=e.detail
            ))
            failed_count += 1
            logging.warning(f"Group auto-assign failed for booking {bk.id}: {e.detail}")

        except Exception as e:
            results.append(GroupAssignResult(
                booking_id=bk.id,
                booking_number=bk.booking_number,
                room_type=room_type_name,
                success=False,
                error=str(e)
            ))
            failed_count += 1
            logging.error(f"Group auto-assign error for booking {bk.id}: {e}")

    await session.commit()

    # Build response message
    if failed_count == 0:
        message = f"All {assigned_count} rooms assigned successfully"
    elif assigned_count == 0:
        message = f"Failed to assign any rooms ({failed_count} failed)"
    else:
        message = f"{assigned_count} rooms assigned, {failed_count} failed"

    return GroupAutoAssignResponse(
        success=failed_count == 0,
        total_bookings=len(group_bookings),
        assigned_count=assigned_count,
        failed_count=failed_count,
        results=results,
        message=message
    )


# ============== DNM (DO NOT MOVE) ENDPOINT ==============

class DNMToggleRequest(BaseModel):
    enabled: bool


@router.patch("/{booking_id}/dnm")
async def toggle_dnm(
    booking_id: str,
    payload: DNMToggleRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Toggle DNM (Do Not Move) flag on a booking to lock/unlock room assignment."""
    allowed_roles = ["admin", "front_desk", "manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Only front desk staff can toggle DNM")

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    booking = await session.get(Booking, booking_id_int)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not booking.room_id:
        raise HTTPException(status_code=400, detail="Cannot set DNM on a booking without an assigned room")

    # If disabling DNM, check permissions (only the setter or admin/manager)
    if not payload.enabled and booking.do_not_move:
        is_dnm_owner = booking.dnm_set_by == current_user.id
        is_manager = current_user.role in [
            "admin", "manager", "general_manager", "front_office_manager",
            "duty_manager", "reservation_manager",
        ] or current_user.is_superuser
        if not is_dnm_owner and not is_manager:
            raise HTTPException(
                status_code=403,
                detail="Only the staff member who set DNM or a manager can remove it."
            )

    booking.do_not_move = payload.enabled
    if payload.enabled:
        booking.dnm_set_by = current_user.id
        booking.dnm_set_at = datetime.utcnow()
    else:
        booking.dnm_set_by = None
        booking.dnm_set_at = None

    booking.updated_at = datetime.utcnow()
    session.add(booking)
    await session.commit()
    await session.refresh(booking)

    setter_name = None
    if payload.enabled:
        setter_name = current_user.full_name or current_user.email

    return {
        "success": True,
        "booking_id": booking.id,
        "do_not_move": booking.do_not_move,
        "dnm_set_by_name": setter_name,
        "dnm_set_at": booking.dnm_set_at.isoformat() if booking.dnm_set_at else None,
        "message": f"DNM {'enabled' if payload.enabled else 'disabled'} for booking {booking.id}"
    }


# ============== AI DRAFT ENDPOINT ==============

class CancellationDraftRequest(BaseModel):
    reason: str
    context: Optional[str] = None
    tone: Optional[str] = "professional"  # professional, friendly, formal, casual


class CancellationDraftResponse(BaseModel):
    success: bool
    notes: str
    reason: str


@router.post("/{booking_id}/draft-cancellation", response_model=CancellationDraftResponse)
async def draft_cancellation_notes(
    booking_id: str,
    payload: CancellationDraftRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Generate AI-drafted cancellation notes based on booking context"""
    import logging

    try:
        booking_id_int = int(booking_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid booking ID")

    # Get booking details
    reservation = await session.get(Reservation, booking_id_int)
    if not reservation:
        raise HTTPException(status_code=404, detail="Booking not found")

    guest = await session.get(Guest, reservation.guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    # Get room type name
    room_type_name = "Standard Room"
    if reservation.room_type_id:
        room_type_obj = await session.get(RoomType, reservation.room_type_id)
        if room_type_obj:
            room_type_name = room_type_obj.name

    # Try to use LangChain/OpenAI for AI drafting
    try:
        from langchain_openai import ChatOpenAI
        from langchain_core.prompts import ChatPromptTemplate
        from app.core.config import settings

        if not settings.openai_api_key:
            raise ValueError("OpenAI API key not configured")

        logging.info(f"AI Draft - Generating cancellation notes for booking {booking_id}")

        llm = ChatOpenAI(
            model="gpt-3.5-turbo",
            temperature=0.7,
            openai_api_key=settings.openai_api_key
        )

        prompt = ChatPromptTemplate.from_template("""
You are a professional hotel staff member drafting internal cancellation notes.
Generate brief, professional notes for a booking cancellation.

Booking Details:
- Guest: {guest_name}
- Room Type: {room_type}
- Check-in: {check_in}
- Check-out: {check_out}
- Nights: {nights}
- Total: ${total:.2f}

Cancellation Reason: {reason}
Additional Context: {context}

Tone: {tone}

Write a concise 2-3 sentence internal note about this cancellation. Include any relevant details that would be useful for hotel records. Be {tone} in tone.
Do not include greetings or signatures. Just the notes content.
""")

        nights = (reservation.departure_date - reservation.arrival_date).days

        chain = prompt | llm
        response = chain.invoke({
            "guest_name": f"{guest.first_name} {guest.last_name}",
            "room_type": room_type_name,
            "check_in": reservation.arrival_date.strftime("%B %d, %Y"),
            "check_out": reservation.departure_date.strftime("%B %d, %Y"),
            "nights": nights,
            "total": reservation.total_amount or 0,
            "reason": payload.reason,
            "context": payload.context or "No additional context provided",
            "tone": payload.tone or "professional"
        })

        generated_notes = response.content.strip()
        logging.info(f"AI draft generated successfully for booking {booking_id}")

        return CancellationDraftResponse(
            success=True,
            notes=generated_notes,
            reason=payload.reason
        )

    except Exception as e:
        logging.warning(f"AI drafting failed, using fallback: {e}")

        # Fallback to template-based notes
        nights = (reservation.departure_date - reservation.arrival_date).days
        fallback_notes = (
            f"Booking cancelled by {current_user.email}. "
            f"Guest: {guest.first_name} {guest.last_name}, "
            f"Room: {room_type_name}, "
            f"Dates: {reservation.arrival_date.strftime('%b %d')} - {reservation.departure_date.strftime('%b %d, %Y')} ({nights} nights). "
            f"Reason: {payload.reason}."
        )

        if payload.context:
            fallback_notes += f" Additional notes: {payload.context}"

        return CancellationDraftResponse(
            success=True,
            notes=fallback_notes,
            reason=payload.reason
        )


# ─── RESEND CONFIRMATION EMAIL ─────────────────────────────────────────────────

@router.post("/{booking_id}/resend-confirmation")
async def resend_confirmation_email(
    booking_id: str,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Resend booking confirmation email to the guest"""
    allowed_roles = ["admin", "front_desk", "manager", "general_manager"]
    if current_user.role not in allowed_roles and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    # Look up by numeric ID, booking_number, or confirmation_code
    booking = None
    try:
        booking_id_int = int(booking_id)
        booking = (await session.exec(
            select(Booking).where(Booking.id == booking_id_int)
        )).first()
    except ValueError:
        pass

    if not booking:
        booking = (await session.exec(
            select(Booking).where(Booking.booking_number == booking_id)
        )).first()

    if not booking:
        booking = (await session.exec(
            select(Booking).where(Booking.confirmation_code == booking_id)
        )).first()

    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Fetch guest directly from Booking (Booking has guest_id)
    guest = await session.get(Guest, booking.guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    if not guest.email:
        raise HTTPException(status_code=400, detail="Guest does not have an email address")

    # Get room type name
    room_type_name = "Standard"
    if booking.room_type_id:
        rt = await session.get(RoomType, booking.room_type_id)
        if rt:
            room_type_name = rt.name

    # Get room number if assigned
    room_number = None
    if booking.room_id:
        room = await session.get(Room, booking.room_id)
        if room:
            room_number = room.number

    try:
        from app.services.pdf_service import generate_booking_confirmation_pdf
        from app.services.background_email import send_booking_confirmation_email_bg
        from app.core.config import settings

        nights = (booking.departure_date - booking.arrival_date).days

        # Generate PDF (fast, CPU-bound — keep synchronous)
        pdf_data = {
            'booking_number': booking.confirmation_code or booking.booking_number,
            'guest_name': f"{guest.first_name} {guest.last_name}",
            'email': guest.email,
            'phone': guest.phone or 'N/A',
            'check_in': booking.arrival_date.isoformat(),
            'check_out': booking.departure_date.isoformat(),
            'nights': nights,
            'room_type': room_type_name,
            'room_number': room_number,
            'base_price': float(booking.base_price or 0),
            'taxes': float(booking.taxes or 0),
            'service_fee': float(booking.service_fee or 0),
            'total_amount': float(booking.total_price or 0),
        }
        pdf_content = generate_booking_confirmation_pdf(pdf_data)

        precheckin_url = f"{settings.frontend_url}/pre-checkin?bookingId={booking.id}"

        # Send email in background - doesn't block response
        background_tasks.add_task(
            send_booking_confirmation_email_bg,
            to_email=guest.email,
            booking_number=booking.confirmation_code or booking.booking_number,
            guest_name=f"{guest.first_name} {guest.last_name}",
            check_in=booking.arrival_date.isoformat(),
            check_out=booking.departure_date.isoformat(),
            room_type=room_type_name,
            room_number=room_number,
            total_amount=float(booking.total_price or 0),
            currency="INR",
            precheckin_url=precheckin_url,
            pdf_content=pdf_content,
        )

        logging.info(f"Queued confirmation email for booking {booking_id} to {guest.email}")
        return {
            "success": True,
            "message": f"Confirmation email sent to {guest.email}",
            "email": guest.email
        }

    except Exception as e:
        logging.error(f"Failed to resend confirmation email for booking {booking_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to send email: {str(e)}")

