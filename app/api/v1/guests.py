from typing import List, Optional, Dict, Any
from datetime import datetime, date
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlmodel import select, func, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel
import json

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.reservations import Guest, Reservation, Booking
from app.models.user import User
from app.services.background_email import send_guest_email_bg
from app.core.config import settings
import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load .env file explicitly
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)

logger = logging.getLogger(__name__)

router = APIRouter()

# LangChain imports for AI drafting
try:
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage, SystemMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:
    LANGCHAIN_AVAILABLE = False
    logger.warning("LangChain not available - AI drafting will use templates")


# ============== SCHEMAS ==============

class GuestCreate(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    date_of_birth: Optional[str] = None
    nationality: Optional[str] = None
    passport_number: Optional[str] = None
    notes: Optional[str] = None


class GuestUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    date_of_birth: Optional[str] = None
    nationality: Optional[str] = None
    passport_number: Optional[str] = None
    avatar: Optional[str] = None
    status: Optional[str] = None  # Active, Inactive, VIP, Blacklisted
    emotion: Optional[str] = None  # happy, neutral, unhappy, positive, negative
    vip_status: Optional[bool] = None
    preferred_room_type: Optional[str] = None  # suite, deluxe, standard
    loyalty_tier: Optional[str] = None  # bronze, silver, gold, platinum, member
    tags: Optional[List[str]] = None
    preferences: Optional[Dict[str, Any]] = None


class GuestRead(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    avatar: Optional[str] = None
    status: str = "Active"
    loyalty_points: int = 0
    loyalty_tier: Optional[str] = None
    total_bookings: int = 0
    total_spent: float = 0.0
    total_nights: int = 0
    member_since: str
    vip_status: bool = False
    last_visit: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None
    tags: Optional[List[str]] = None
    emotion: str = "neutral"

    class Config:
        from_attributes = True


class GuestFullProfile(BaseModel):
    id: int
    user_id: Optional[int] = None
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    date_of_birth: Optional[str] = None
    nationality: Optional[str] = None
    passport_number: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    postal_code: Optional[str] = None
    avatar: Optional[str] = None
    status: str = "Active"
    emotion: str = "neutral"
    # Pre-checkin preferences
    floor_preference: Optional[str] = None
    view_preference: Optional[str] = None
    bed_type_preference: Optional[str] = None
    quietness_preference: Optional[str] = None
    pillow_type: Optional[str] = None
    temperature_preference: Optional[int] = None
    dietary_restrictions: Optional[str] = None
    special_requests: Optional[str] = None
    arrival_time: Optional[str] = None
    transportation_needed: bool = False
    loyalty_points: int = 0
    loyalty_tier: Optional[str] = None
    total_bookings: int = 0
    total_spent: float = 0.0
    total_nights: int = 0
    avg_stay_duration: float = 0.0
    vip_status: bool = False
    preferred_room_type: Optional[str] = None
    member_since: str
    last_visit: Optional[str] = None
    preferences: Optional[Dict[str, Any]] = None
    notes: Optional[List[Dict[str, Any]]] = None
    tags: Optional[List[str]] = None
    booking_source: Optional[str] = None
    id_type: Optional[str] = None
    id_number: Optional[str] = None
    id_verified: bool = False
    stay_history: Optional[List[Dict[str, Any]]] = None
    bookings: Optional[List[Dict[str, Any]]] = None

    class Config:
        from_attributes = True


class PreferencesUpdate(BaseModel):
    room_preferences: Optional[Dict[str, Any]] = None  # bed_type, floor, view, temperature
    dining_preferences: Optional[Dict[str, Any]] = None  # dietary_restrictions, favorite_cuisine
    special_requests: Optional[List[str]] = None


class GuestNote(BaseModel):
    text: str
    category: str = "general"  # general, complaint, preference, special_request


class GuestFeedback(BaseModel):
    booking_id: Optional[int] = None
    rating: int  # 1-5
    comment: Optional[str] = None
    categories: Optional[Dict[str, int]] = None  # room: 5, service: 4, cleanliness: 5, etc.


# ============== HELPER FUNCTIONS ==============

def parse_json_field(value) -> Any:
    """Parse JSON field that might be a string or already parsed"""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except:
            return value
    return value


def calculate_loyalty_tier(points: int) -> str:
    """Calculate loyalty tier based on points"""
    if points >= 10000:
        return "platinum"
    elif points >= 5000:
        return "gold"
    elif points >= 2000:
        return "silver"
    elif points >= 500:
        return "bronze"
    return "member"


async def get_guest_stats(session: AsyncSession, guest_id: int) -> dict:
    """Calculate guest statistics from bookings"""
    # Get the guest's email to find all related guest records
    guest = await session.get(Guest, guest_id)
    guest_ids_to_search = [guest_id]

    if guest and guest.email:
        try:
            matching_guests = (await session.exec(
                select(Guest.id).where(Guest.email == guest.email.lower().strip())
            )).all()
            guest_ids_to_search = list(set([guest_id] + list(matching_guests)))
        except Exception:
            pass

    # Query BOTH Booking (V2.0) and Reservation (legacy) tables and combine results
    bookings = []

    # Query Booking table first (V2.0 - primary table where new bookings are stored)
    try:
        booking_results = (await session.exec(
            select(Booking).where(Booking.guest_id.in_(guest_ids_to_search))
        )).all()
        bookings.extend(booking_results)
    except Exception as e:
        logger.debug(f"Error querying Booking table: {e}")

    # Also query Reservation table (legacy) for older bookings
    try:
        reservation_results = (await session.exec(
            select(Reservation).where(Reservation.guest_id.in_(guest_ids_to_search))
        )).all()
        bookings.extend(reservation_results)
    except Exception as e:
        logger.debug(f"Error querying Reservation table: {e}")

    # Deduplicate by confirmation_code — create_reservation creates both a
    # Booking and a Reservation with the same code, so without dedup every
    # stay would be counted twice.
    seen_codes: set = set()
    unique_bookings = []
    for b in bookings:
        code = getattr(b, 'confirmation_code', None)
        if code and code in seen_codes:
            continue
        if code:
            seen_codes.add(code)
        unique_bookings.append(b)
    bookings = unique_bookings

    total_bookings = len(bookings)
    total_spent = 0.0
    total_nights = 0
    last_visit = None

    for b in bookings:
        total_spent += getattr(b, 'total_price', 0) or getattr(b, 'total_amount', 0) or 0
        nights = getattr(b, 'nights', 0) or 0
        if nights == 0:
            arrival = getattr(b, 'arrival_date', None) or getattr(b, 'check_in', None)
            departure = getattr(b, 'departure_date', None) or getattr(b, 'check_out', None)
            if arrival and departure:
                nights = (departure - arrival).days
        total_nights += nights

        visit_date = getattr(b, 'arrival_date', None) or getattr(b, 'check_in', None)
        if visit_date:
            if last_visit is None or visit_date > last_visit:
                last_visit = visit_date

    loyalty_points = int(total_spent * 0.1)  # 10% of spending as points
    avg_stay = total_nights / total_bookings if total_bookings > 0 else 0

    return {
        "total_bookings": total_bookings,
        "total_spent": round(total_spent, 2),
        "total_nights": total_nights,
        "loyalty_points": loyalty_points,
        "loyalty_tier": calculate_loyalty_tier(loyalty_points),
        "avg_stay_duration": round(avg_stay, 1),
        "last_visit": last_visit.isoformat() if last_visit else None,
        "vip_status": None,  # BUG-011 FIX: Don't compute VIP - let manual override take precedence
    }


def guest_to_read(guest: Guest, stats: dict) -> GuestRead:
    """Convert Guest model to GuestRead schema"""
    preferences = parse_json_field(guest.preferences)
    tags = parse_json_field(guest.tags)

    return GuestRead(
        id=guest.id,
        first_name=guest.first_name,
        last_name=guest.last_name,
        email=guest.email,
        phone=guest.phone,
        address=guest.address,
        city=guest.city,
        state=guest.state,
        country=guest.country,
        postal_code=guest.postal_code,
        avatar=guest.avatar,
        status=guest.status or "Active",
        loyalty_points=stats.get("loyalty_points", guest.loyalty_points or 0),
        loyalty_tier=stats.get("loyalty_tier", guest.loyalty_tier),
        total_bookings=stats.get("total_bookings", guest.total_bookings or 0),
        total_spent=stats.get("total_spent", guest.total_spent or 0.0),
        total_nights=stats.get("total_nights", guest.total_nights or 0),
        member_since=guest.created_at.date().isoformat() if guest.created_at else "",
        vip_status=guest.vip_status if guest.vip_status is not None else (stats.get("loyalty_points", 0) > 2000),
        last_visit=stats.get("last_visit"),
        preferences=preferences if isinstance(preferences, dict) else None,
        tags=tags if isinstance(tags, list) else None,
        emotion=guest.emotion or "neutral",
    )


# ============== ENDPOINTS ==============

@router.get("/stats")
async def get_guests_stats(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get guest counts for tabs (all, returning, VIP, blacklisted). Excludes staff."""
    # Get staff user IDs to exclude
    staff_roles = {
        'admin', 'manager', 'staff', 'front_desk', 'front_desk_agent',
        'housekeeping', 'housekeeper', 'maintenance', 'technician',
        'runner', 'finance', 'management', 'Maintenance'
    }
    staff_users_query = select(User.id).where(User.role.in_(staff_roles))
    staff_user_ids = (await session.exec(staff_users_query)).all()

    # Build query excluding staff and inactive guests
    query = select(Guest).where(Guest.status != "Inactive")
    if staff_user_ids:
        query = query.where(
            or_(
                Guest.user_id.is_(None),
                Guest.user_id.notin_(staff_user_ids)
            )
        )

    all_guests = (await session.exec(query)).all()

    # Calculate stats for each guest to determine returning status
    returning_count = 0
    vip_count = 0
    blacklisted_count = 0

    for guest in all_guests:
        # Get booking count from BOTH tables
        booking_count = 0

        try:
            bookings = (await session.exec(
                select(Booking).where(Booking.guest_id == guest.id)
            )).all()
            booking_count += len(bookings)
        except Exception:
            pass

        try:
            reservations = (await session.exec(
                select(Reservation).where(Reservation.guest_id == guest.id)
            )).all()
            booking_count += len(reservations)
        except Exception:
            pass

        if booking_count > 1:
            returning_count += 1

        if guest.vip_status:
            vip_count += 1

        if guest.status and guest.status.lower() == "blacklisted":
            blacklisted_count += 1

    return {
        "all": len(all_guests),
        "returning": returning_count,
        "vip": vip_count,
        "blacklisted": blacklisted_count,
    }


# Staff roles to exclude from guests list
STAFF_ROLES = {
    'admin', 'manager', 'staff', 'front_desk', 'front_desk_agent',
    'housekeeping', 'housekeeper', 'maintenance', 'technician',
    'runner', 'finance', 'management', 'Maintenance'
}


@router.get("", response_model=List[GuestRead])
async def list_guests(
    search: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    filter_type: Optional[str] = Query(None, description="Filter by: all, returning, vip, blacklisted"),
    vip_only: bool = Query(False),
    include_staff: bool = Query(False, description="Include staff members in results"),
    include_inactive: bool = Query(False, description="Include deleted/inactive guests"),
    page: int = Query(1, ge=1),
    pageSize: int = Query(20, ge=1, le=1000),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List guests with optional search and filters. Excludes staff and inactive by default."""
    query = select(Guest)

    # Exclude inactive/deleted guests by default
    if not include_inactive and not status:
        query = query.where(Guest.status != "Inactive")

    # Exclude staff members by default (guests linked to users with staff roles)
    if not include_staff:
        # Get user IDs that are staff
        staff_users_query = select(User.id).where(User.role.in_(STAFF_ROLES))
        staff_user_ids = (await session.exec(staff_users_query)).all()

        if staff_user_ids:
            # Exclude guests linked to staff users
            query = query.where(
                or_(
                    Guest.user_id.is_(None),  # Guests not linked to any user
                    Guest.user_id.notin_(staff_user_ids)  # Guests not linked to staff
                )
            )

    if search:
        query = query.where(
            or_(
                Guest.first_name.ilike(f"%{search}%"),
                Guest.last_name.ilike(f"%{search}%"),
                Guest.email.ilike(f"%{search}%"),
                Guest.phone.ilike(f"%{search}%")
            )
        )
    if email:
        query = query.where(Guest.email == email)
    if status:
        query = query.where(Guest.status == status)
    if vip_only or filter_type == "vip":
        query = query.where(Guest.vip_status == True)
    if filter_type == "blacklisted":
        query = query.where(Guest.status == "Blacklisted")

    result = await session.exec(query.order_by(Guest.created_at.desc()))
    all_guests = result.all()

    # Calculate stats for each guest
    guests_with_stats = []
    for guest in all_guests:
        stats = await get_guest_stats(session, guest.id)
        guest_read = guest_to_read(guest, stats)

        # Filter returning guests (more than 1 booking)
        if filter_type == "returning":
            if stats.get("total_bookings", 0) <= 1:
                continue

        guests_with_stats.append(guest_read)

    # Paginate
    offset = (page - 1) * pageSize
    paginated = guests_with_stats[offset:offset + pageSize]

    return paginated


@router.get("/{guest_id}", response_model=GuestRead)
async def get_guest(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get guest by ID"""
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    stats = await get_guest_stats(session, guest.id)
    return guest_to_read(guest, stats)


@router.get("/{guest_id}/profile", response_model=GuestFullProfile)
async def get_guest_full_profile(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get full guest profile with stay history, bookings, and pre-checkin preferences"""
    from app.models.precheckin import PreCheckIn
    from app.models.inventory import RoomType

    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    stats = await get_guest_stats(session, guest.id)

    # Build a cache of room types for lookup
    room_types_cache = {}
    try:
        room_types_result = await session.exec(select(RoomType))
        for rt in room_types_result.all():
            room_types_cache[rt.id] = rt.name
    except Exception as e:
        print(f"Error fetching room types: {e}")

    # Get latest pre-checkin data for this guest (most recent completed one)
    precheckin_data = {}
    try:
        # Find the most recent completed pre-checkin for this guest
        precheckin_result = await session.exec(
            select(PreCheckIn)
            .where(PreCheckIn.guest_id == guest_id)
            .order_by(PreCheckIn.updated_at.desc())
        )
        precheckin = precheckin_result.first()

        if precheckin:
            # Parse JSON fields
            pillow_type = precheckin.pillow_type
            if pillow_type and isinstance(pillow_type, str):
                try:
                    pillow_type = json.loads(pillow_type)
                except:
                    pass

            dietary_restrictions = precheckin.dietary_restrictions
            if dietary_restrictions and isinstance(dietary_restrictions, str):
                try:
                    dietary_restrictions = json.loads(dietary_restrictions)
                except:
                    pass

            minibar_preferences = precheckin.minibar_preferences
            if minibar_preferences and isinstance(minibar_preferences, str):
                try:
                    minibar_preferences = json.loads(minibar_preferences)
                except:
                    pass

            precheckin_data = {
                "floor_preference": precheckin.floor_preference,
                "view_preference": precheckin.view_preference,
                "bed_type_preference": precheckin.bed_type_preference,
                "quietness_preference": precheckin.quietness_preference,
                "pillow_type": pillow_type,
                "temperature_preference": precheckin.temperature,
                "minibar_preferences": minibar_preferences,
                "dietary_restrictions": dietary_restrictions,
                "special_requests": precheckin.special_requests,
                "arrival_time": precheckin.arrival_time,
                "transportation_needed": precheckin.transportation_needed or False,
                "early_check_in": precheckin.early_check_in or False,
                "late_check_out": precheckin.late_check_out or False,
            }
    except Exception as e:
        print(f"Error fetching precheckin data: {e}")

    # Get booking history - look up by guest_id OR by email (for guests with multiple records)
    booking_list = []
    guest_email = guest.email.lower().strip() if guest.email else None

    # First, find all guest IDs that share this email (handles duplicate guest records)
    guest_ids_to_search = [guest_id]
    if guest_email:
        try:
            matching_guests = (await session.exec(
                select(Guest.id).where(Guest.email == guest_email)
            )).all()
            guest_ids_to_search = list(set([guest_id] + list(matching_guests)))
        except Exception as e:
            print(f"Error finding matching guests: {e}")

    # Query BOTH tables and combine results (Booking first as primary, then Reservation for legacy)
    booking_list = []

    # Query Booking table first (V2.0 - primary table)
    try:
        bookings_result = await session.exec(
            select(Booking)
            .where(Booking.guest_id.in_(guest_ids_to_search))
            .order_by(Booking.arrival_date.desc())
        )
        bookings = bookings_result.all()
        for b in bookings:
            booking_list.append({
                "id": b.id,
                "booking_number": b.booking_number,
                "confirmation_code": b.confirmation_code,
                "arrival_date": b.arrival_date.isoformat() if b.arrival_date else None,
                "departure_date": b.departure_date.isoformat() if b.departure_date else None,
                "nights": b.nights,
                "room_id": b.room_id,
                "room_type_id": b.room_type_id,
                "room_type": room_types_cache.get(b.room_type_id, "Standard"),
                "status": b.status,
                "total_price": b.total_price,
                "payment_status": b.payment_status,
            })
    except Exception as e:
        logger.debug(f"Error fetching from Booking table: {e}")

    # Also query Reservation table (legacy) for older bookings
    try:
        reservations_result = await session.exec(
            select(Reservation)
            .where(Reservation.guest_id.in_(guest_ids_to_search))
            .order_by(Reservation.arrival_date.desc())
        )
        reservations = reservations_result.all()
        for b in reservations:
            # Avoid duplicates by checking confirmation_code
            existing_codes = {item.get("confirmation_code") for item in booking_list}
            if b.confirmation_code not in existing_codes:
                booking_list.append({
                    "id": b.id,
                    "booking_number": getattr(b, 'booking_number', None),
                    "confirmation_code": b.confirmation_code,
                    "arrival_date": b.arrival_date.isoformat() if b.arrival_date else None,
                    "departure_date": b.departure_date.isoformat() if b.departure_date else None,
                    "nights": (b.departure_date - b.arrival_date).days if b.departure_date and b.arrival_date else 0,
                    "room_id": b.room_id,
                    "room_type_id": getattr(b, 'room_type_id', None),
                    "room_type": room_types_cache.get(getattr(b, 'room_type_id', None), "Standard"),
                    "status": b.status,
                    "total_price": getattr(b, 'total_price', None) or b.total_amount,
                    "payment_status": getattr(b, 'payment_status', 'pending'),
                })
    except Exception as e:
        logger.debug(f"Error fetching from Reservation table: {e}")

    # Sort combined list by arrival_date descending
    booking_list.sort(key=lambda x: x.get("arrival_date") or "", reverse=True)

    # Build stay history summary with room_type
    stay_history = []
    for b in booking_list:
        stay_history.append({
            "booking_id": b.get("id"),
            "check_in": b.get("arrival_date"),
            "check_out": b.get("departure_date"),
            "nights": b.get("nights", 0),
            "total_spent": b.get("total_price", 0) or b.get("total_amount", 0),
            "room_type": b.get("room_type", "Standard"),
            "status": b.get("status"),
        })

    # Parse JSON fields
    preferences = parse_json_field(guest.preferences)
    notes = parse_json_field(guest.notes)
    tags = parse_json_field(guest.tags)

    # If no guest preferences, try to get from linked User record
    if not preferences or (isinstance(preferences, dict) and len(preferences) == 0):
        try:
            # Try to find linked user by user_id or email
            linked_user = None
            if guest.user_id:
                linked_user = await session.get(User, guest.user_id)
            elif guest.email:
                user_result = await session.exec(
                    select(User).where(User.email == guest.email.lower().strip())
                )
                linked_user = user_result.first()

            if linked_user and linked_user.preferences:
                user_prefs = parse_json_field(linked_user.preferences)
                if isinstance(user_prefs, dict) and len(user_prefs) > 0:
                    preferences = user_prefs
                    # Also sync to guest record for future reads
                    guest.preferences = user_prefs
                    if not guest.user_id and linked_user:
                        guest.user_id = linked_user.id
                    await session.commit()
                    print(f"[Guests API] Synced preferences from User ID {linked_user.id} to Guest ID {guest.id}")
        except Exception as e:
            print(f"[Guests API] Warning: Could not fetch User preferences: {e}")

    # Merge precheckin preferences into main preferences for complete view
    if not isinstance(preferences, dict):
        preferences = {}

    # Add room preferences from precheckin
    if precheckin_data:
        preferences["room"] = {
            "floor": precheckin_data.get("floor_preference"),
            "view": precheckin_data.get("view_preference"),
            "bedType": precheckin_data.get("bed_type_preference"),
            "quietness": precheckin_data.get("quietness_preference"),
        }
        preferences["comfort"] = {
            "pillowType": precheckin_data.get("pillow_type"),
            "temperature": precheckin_data.get("temperature_preference"),
        }
        preferences["dining"] = {
            "dietaryRestrictions": precheckin_data.get("dietary_restrictions"),
            "minibar": precheckin_data.get("minibar_preferences"),
        }
        preferences["travel"] = {
            "arrivalTime": precheckin_data.get("arrival_time"),
            "transportationNeeded": precheckin_data.get("transportation_needed"),
            "earlyCheckIn": precheckin_data.get("early_check_in"),
            "lateCheckOut": precheckin_data.get("late_check_out"),
        }
        if precheckin_data.get("special_requests"):
            preferences["specialRequests"] = precheckin_data.get("special_requests")

    return GuestFullProfile(
        id=guest.id,
        user_id=guest.user_id,
        first_name=guest.first_name,
        last_name=guest.last_name,
        email=guest.email,
        phone=guest.phone,
        date_of_birth=guest.date_of_birth.isoformat() if guest.date_of_birth else None,
        nationality=guest.nationality,
        passport_number=guest.passport_number,
        address=guest.address,
        city=guest.city,
        state=guest.state,
        country=guest.country,
        postal_code=guest.postal_code,
        avatar=guest.avatar,
        status=guest.status or "Active",
        emotion=guest.emotion or "neutral",
        # Pre-checkin preferences
        floor_preference=precheckin_data.get("floor_preference"),
        view_preference=precheckin_data.get("view_preference"),
        bed_type_preference=precheckin_data.get("bed_type_preference"),
        quietness_preference=precheckin_data.get("quietness_preference"),
        pillow_type=precheckin_data.get("pillow_type"),
        temperature_preference=precheckin_data.get("temperature_preference"),
        dietary_restrictions=precheckin_data.get("dietary_restrictions"),
        special_requests=precheckin_data.get("special_requests"),
        arrival_time=precheckin_data.get("arrival_time"),
        transportation_needed=precheckin_data.get("transportation_needed", False),
        # Stats
        loyalty_points=stats.get("loyalty_points", guest.loyalty_points or 0),
        loyalty_tier=stats.get("loyalty_tier", guest.loyalty_tier),
        total_bookings=stats.get("total_bookings", guest.total_bookings or 0),
        total_spent=stats.get("total_spent", guest.total_spent or 0.0),
        total_nights=stats.get("total_nights", guest.total_nights or 0),
        avg_stay_duration=stats.get("avg_stay_duration", 0.0),
        vip_status=guest.vip_status if guest.vip_status is not None else (stats.get("loyalty_points", 0) > 2000),
        preferred_room_type=guest.preferred_room_type,
        member_since=guest.created_at.date().isoformat() if guest.created_at else "",
        last_visit=stats.get("last_visit"),
        preferences=preferences if isinstance(preferences, dict) else None,
        notes=notes if isinstance(notes, list) else None,
        tags=tags if isinstance(tags, list) else None,
        booking_source=guest.booking_source,
        id_type=guest.id_type,
        id_number=guest.id_number,
        id_verified=guest.id_verified or False,
        stay_history=stay_history,
        bookings=booking_list,
    )


@router.get("/{guest_id}/bookings")
async def get_guest_bookings(
    guest_id: int,
    status: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get all bookings for a guest with new booking fields"""
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    # Find all guest IDs with same email (handles duplicates)
    guest_ids_to_search = [guest_id]
    if guest.email:
        try:
            matching_guests = (await session.exec(
                select(Guest.id).where(Guest.email == guest.email.lower().strip())
            )).all()
            guest_ids_to_search = list(set([guest_id] + list(matching_guests)))
        except Exception:
            pass

    booking_list = []

    # Query Booking table (V2.0 - primary)
    try:
        query = select(Booking).where(Booking.guest_id.in_(guest_ids_to_search))
        if status:
            query = query.where(Booking.status == status)

        result = await session.exec(query.order_by(Booking.arrival_date.desc()))
        bookings = result.all()

        for b in bookings:
            booking_list.append({
                "id": b.id,
                "booking_number": b.booking_number,
                "confirmation_code": b.confirmation_code,
                "room_id": b.room_id,
                "room_type_id": b.room_type_id,
                "arrival_date": b.arrival_date.isoformat() if b.arrival_date else None,
                "departure_date": b.departure_date.isoformat() if b.departure_date else None,
                "check_in_date": b.check_in_date.isoformat() if b.check_in_date else None,
                "check_out_date": b.check_out_date.isoformat() if b.check_out_date else None,
                "nights": b.nights,
                "adults": b.adults,
                "children": b.children,
                "infants": b.infants,
                "status": b.status,
                "payment_status": b.payment_status,
                "booking_source": b.booking_source,
                "channel": b.channel,
                "base_price": b.base_price,
                "taxes": b.taxes,
                "service_fee": b.service_fee,
                "total_price": b.total_price,
                "deposit_amount": b.deposit_amount,
                "balance_due": b.balance_due,
                "special_requests": b.special_requests,
                "vip_flag": b.vip_flag,
                "number_of_guests": b.number_of_guests,
                "upsells": json.loads(b.upsells) if b.upsells and isinstance(b.upsells, str) else b.upsells,
                "discount_code": b.discount_code,
                "discount_amount": b.discount_amount,
                "commission_rate": b.commission_rate,
                "commission_amount": b.commission_amount,
                "net_revenue": b.net_revenue,
                "modification_count": b.modification_count,
            })
    except Exception as e:
        logger.debug(f"Error fetching from Booking table: {e}")

    # Also query Reservation table (legacy)
    try:
        query = select(Reservation).where(Reservation.guest_id.in_(guest_ids_to_search))
        if status:
            query = query.where(Reservation.status == status)

        result = await session.exec(query.order_by(Reservation.arrival_date.desc()))
        reservations = result.all()

        existing_codes = {item.get("confirmation_code") for item in booking_list}
        for r in reservations:
            if r.confirmation_code not in existing_codes:
                booking_list.append({
                    "id": r.id,
                    "booking_number": getattr(r, 'booking_number', None),
                    "confirmation_code": r.confirmation_code,
                    "room_id": r.room_id,
                    "room_type_id": r.room_type_id,
                    "arrival_date": r.arrival_date.isoformat() if r.arrival_date else None,
                    "departure_date": r.departure_date.isoformat() if r.departure_date else None,
                    "check_in_date": None,
                    "check_out_date": None,
                    "nights": (r.departure_date - r.arrival_date).days if r.departure_date and r.arrival_date else 0,
                    "adults": r.adults,
                    "children": r.children,
                    "infants": 0,
                    "status": r.status,
                    "payment_status": "pending",
                    "booking_source": r.booking_source,
                    "channel": None,
                    "base_price": r.total_amount,
                    "taxes": 0,
                    "service_fee": 0,
                    "total_price": r.total_amount,
                    "deposit_amount": None,
                    "balance_due": None,
                    "special_requests": r.special_requests,
                    "vip_flag": False,
                    "number_of_guests": r.adults + r.children,
                    "upsells": None,
                    "discount_code": None,
                    "discount_amount": 0,
                    "commission_rate": None,
                    "commission_amount": None,
                    "net_revenue": None,
                    "modification_count": 0,
                })
    except Exception as e:
        logger.debug(f"Error fetching from Reservation table: {e}")

    # Sort by arrival_date descending
    booking_list.sort(key=lambda x: x.get("arrival_date") or "", reverse=True)

    return booking_list


@router.get("/{guest_id}/preferences")
async def get_guest_preferences(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get guest preferences"""
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    preferences = parse_json_field(guest.preferences)

    return {
        "guest_id": guest_id,
        "preferred_room_type": guest.preferred_room_type,
        "preferences": preferences if isinstance(preferences, dict) else {},
    }


@router.patch("/{guest_id}/preferences")
async def update_guest_preferences(
    guest_id: int,
    payload: PreferencesUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update guest preferences"""
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    # Get existing preferences
    existing = parse_json_field(guest.preferences) or {}
    if not isinstance(existing, dict):
        existing = {}

    # Merge new preferences
    if payload.room_preferences:
        existing["room"] = payload.room_preferences
    if payload.dining_preferences:
        existing["dining"] = payload.dining_preferences
    if payload.special_requests:
        existing["special_requests"] = payload.special_requests

    guest.preferences = json.dumps(existing)
    guest.updated_at = datetime.utcnow()
    await session.commit()

    return {
        "message": "Preferences updated",
        "guest_id": guest_id,
        "preferences": existing,
    }


@router.post("/{guest_id}/notes")
async def add_guest_note(
    guest_id: int,
    payload: GuestNote,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Add a note to guest profile"""
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    # Get existing notes
    existing_notes = parse_json_field(guest.notes) or []
    if not isinstance(existing_notes, list):
        existing_notes = []

    # Add new note
    new_note = {
        "id": len(existing_notes) + 1,
        "text": payload.text,
        "category": payload.category,
        "author": current_user.full_name or current_user.email,
        "author_id": current_user.id,
        "date": datetime.utcnow().isoformat(),
    }
    existing_notes.append(new_note)

    guest.notes = json.dumps(existing_notes)
    guest.updated_at = datetime.utcnow()
    await session.commit()

    return {
        "message": "Note added",
        "note": new_note,
    }


@router.get("/{guest_id}/notes")
async def get_guest_notes(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get all notes for a guest"""
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    notes = parse_json_field(guest.notes) or []
    return {"guest_id": guest_id, "notes": notes}


@router.delete("/{guest_id}/notes/{note_id}")
async def delete_guest_note(
    guest_id: int,
    note_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a note from guest profile"""
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    # Get existing notes
    existing_notes = parse_json_field(guest.notes) or []
    if not isinstance(existing_notes, list):
        existing_notes = []

    # Find and remove the note
    original_length = len(existing_notes)
    existing_notes = [n for n in existing_notes if n.get("id") != note_id]

    if len(existing_notes) == original_length:
        raise HTTPException(status_code=404, detail="Note not found")

    guest.notes = json.dumps(existing_notes)
    guest.updated_at = datetime.utcnow()
    await session.commit()

    return {
        "message": "Note deleted",
        "guest_id": guest_id,
        "note_id": note_id,
    }


@router.get("/{guest_id}/loyalty")
async def get_guest_loyalty(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get guest loyalty information"""
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    stats = await get_guest_stats(session, guest.id)

    # Calculate points needed for next tier
    points = stats["loyalty_points"]
    tier = stats["loyalty_tier"]

    tier_thresholds = {
        "member": 500,
        "bronze": 2000,
        "silver": 5000,
        "gold": 10000,
        "platinum": None,
    }

    next_tier_threshold = tier_thresholds.get(tier)
    points_to_next_tier = max(0, (next_tier_threshold or 0) - points) if next_tier_threshold else 0

    return {
        "guest_id": guest_id,
        "loyalty_points": points,
        "loyalty_tier": tier,
        "total_bookings": stats["total_bookings"],
        "total_spent": stats["total_spent"],
        "total_nights": stats["total_nights"],
        "vip_status": stats["vip_status"],
        "points_to_next_tier": points_to_next_tier,
        "next_tier": calculate_loyalty_tier(points + points_to_next_tier + 1) if points_to_next_tier > 0 else None,
    }


@router.post("/{guest_id}/feedback")
async def submit_guest_feedback(
    guest_id: int,
    payload: GuestFeedback,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Submit guest feedback"""
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    # Update guest emotion based on rating
    if payload.rating >= 4:
        guest.emotion = "happy"
    elif payload.rating <= 2:
        guest.emotion = "unhappy"
    else:
        guest.emotion = "neutral"

    guest.updated_at = datetime.utcnow()

    # Add feedback as a note
    existing_notes = parse_json_field(guest.notes) or []
    if not isinstance(existing_notes, list):
        existing_notes = []

    feedback_note = {
        "id": len(existing_notes) + 1,
        "text": f"Feedback (Rating: {payload.rating}/5): {payload.comment or 'No comment'}",
        "category": "feedback",
        "rating": payload.rating,
        "categories": payload.categories,
        "booking_id": payload.booking_id,
        "author": "Guest",
        "date": datetime.utcnow().isoformat(),
    }
    existing_notes.append(feedback_note)
    guest.notes = json.dumps(existing_notes)

    await session.commit()

    return {
        "message": "Feedback submitted",
        "rating": payload.rating,
        "guest_id": guest_id,
    }


@router.post("", response_model=GuestRead, status_code=201)
async def create_guest(
    payload: GuestCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new guest"""
    # Check if guest with email already exists
    if payload.email:
        existing = (await session.exec(
            select(Guest).where(Guest.email == payload.email)
        )).first()
        if existing:
            raise HTTPException(status_code=400, detail="Guest with this email already exists")

    # Parse date of birth
    dob = None
    if payload.date_of_birth:
        try:
            dob = date.fromisoformat(payload.date_of_birth)
        except:
            pass

    guest = Guest(
        first_name=payload.first_name,
        last_name=payload.last_name,
        email=payload.email,
        phone=payload.phone,
        address=payload.address,
        city=payload.city,
        state=payload.state,
        country=payload.country,
        postal_code=payload.postal_code,
        date_of_birth=dob,
        nationality=payload.nationality,
        passport_number=payload.passport_number,
        status="Active",
        loyalty_points=0,
        total_bookings=0,
        total_spent=0.0,
    )
    session.add(guest)
    await session.commit()
    await session.refresh(guest)

    return guest_to_read(guest, {
        "total_bookings": 0,
        "total_spent": 0.0,
        "total_nights": 0,
        "loyalty_points": 0,
        "loyalty_tier": "member",
        "avg_stay_duration": 0.0,
        "last_visit": None,
        "vip_status": False,
    })


@router.patch("/{guest_id}", response_model=GuestRead)
async def update_guest(
    guest_id: int,
    payload: GuestUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update guest"""
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    update_data = payload.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        if key == "date_of_birth" and value:
            try:
                value = date.fromisoformat(value)
            except:
                continue
        elif key == "tags" and value is not None:
            # Serialize tags to JSON string for storage
            value = json.dumps(value) if isinstance(value, list) else value
        elif key == "preferences" and value is not None:
            # Serialize preferences to JSON for storage
            value = json.dumps(value) if isinstance(value, dict) else value
        setattr(guest, key, value)

    guest.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(guest)

    stats = await get_guest_stats(session, guest.id)
    return guest_to_read(guest, stats)


@router.delete("/{guest_id}")
async def delete_guest(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Soft delete guest (set status to Inactive)"""
    if current_user.role != "admin" and not current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Admin access required")

    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    guest.status = "Inactive"
    guest.updated_at = datetime.utcnow()
    await session.commit()

    return {"message": "Guest deactivated", "id": guest_id}


@router.post("/{guest_id}/tags")
async def update_guest_tags(
    guest_id: int,
    tags: List[str],
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update guest tags"""
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    guest.tags = json.dumps(tags)
    guest.updated_at = datetime.utcnow()
    await session.commit()

    return {"message": "Tags updated", "guest_id": guest_id, "tags": tags}


# ============== GUEST MESSAGING SCHEMAS ==============

class GuestMessageRequest(BaseModel):
    subject: str
    message: str
    template: Optional[str] = "custom"


class GuestDraftRequest(BaseModel):
    template: str  # welcome, thankyou, followup, birthday, promotional, apology, custom
    context: Optional[str] = None  # Additional context for AI drafting
    tone: Optional[str] = "professional"  # professional, friendly, formal, casual


class GuestMessageResponse(BaseModel):
    success: bool
    message: str
    email_sent: bool = False


class GuestDraftResponse(BaseModel):
    success: bool
    subject: str
    message: str
    template: str


# ============== GUEST MESSAGING ENDPOINTS ==============

@router.post("/{guest_id}/message", response_model=GuestMessageResponse)
async def send_guest_message(
    guest_id: int,
    payload: GuestMessageRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Send an email message to a guest.
    Requires staff or admin access.
    """
    # Verify permissions
    if current_user.role not in ["admin", "staff", "manager", "front_desk", "concierge"]:
        raise HTTPException(status_code=403, detail="Insufficient permissions to send messages")

    # Get guest
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    if not guest.email:
        raise HTTPException(status_code=400, detail="Guest does not have an email address")

    # Build HTML email body with hotel branding
    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: 'Georgia', serif; background-color: #FAF8F6; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 8px; overflow: hidden; }}
            .header {{ background: linear-gradient(135deg, #8E6554 0%, #A57865 100%); padding: 30px; text-align: center; }}
            .header h1 {{ color: white; margin: 0; font-size: 28px; font-weight: 400; }}
            .content {{ padding: 40px 30px; color: #333; line-height: 1.6; }}
            .footer {{ background: #FAF8F6; padding: 20px 30px; text-align: center; font-size: 12px; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Glimmora</h1>
            </div>
            <div class="content">
                {payload.message.replace(chr(10), '<br>')}
            </div>
            <div class="footer">
                <p>Glimmora Hotel & Resort</p>
                <p>Where Luxury Meets Tranquility</p>
            </div>
        </div>
    </body>
    </html>
    """

    # Send the email in background - doesn't block response
    background_tasks.add_task(
        send_guest_email_bg,
        to_email=guest.email,
        subject=payload.subject,
        html_body=html_body,
        text_body=payload.message,
    )

    return GuestMessageResponse(
        success=True,
        message=f"Email queued for delivery to {guest.email}",
        email_sent=True
    )


@router.post("/{guest_id}/draft-message", response_model=GuestDraftResponse)
async def draft_guest_message(
    guest_id: int,
    payload: GuestDraftRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Use AI to draft a personalized message for a guest.
    The AI considers guest history, preferences, and the specified template type.
    """
    # Get guest with full profile
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    guest_name = f"{guest.first_name} {guest.last_name}".strip() or "Guest"

    # Template-based drafting (fallback if AI not available)
    templates = {
        "welcome": {
            "subject": "Welcome to Glimmora",
            "message": f"Dear {guest_name},\n\nWelcome to Glimmora! We're thrilled to have you stay with us.\n\nIf you need anything during your stay, please don't hesitate to reach out to our concierge team.\n\nBest regards,\nThe Glimmora Team"
        },
        "thankyou": {
            "subject": "Thank You for Your Stay",
            "message": f"Dear {guest_name},\n\nThank you for choosing Glimmora for your recent stay. We hope you had a wonderful experience.\n\nWe'd love to welcome you back soon!\n\nWarm regards,\nThe Glimmora Team"
        },
        "followup": {
            "subject": "We'd Love Your Feedback",
            "message": f"Dear {guest_name},\n\nWe hope you enjoyed your recent stay at Glimmora.\n\nYour feedback is invaluable to us. Would you mind taking a moment to share your experience?\n\nThank you,\nThe Glimmora Team"
        },
        "birthday": {
            "subject": "Happy Birthday from Glimmora!",
            "message": f"Dear {guest_name},\n\nHappy Birthday!\n\nWe'd like to offer you a special 20% discount on your next stay with us.\n\nCelebrate in style at Glimmora!\n\nBest wishes,\nThe Glimmora Team"
        },
        "promotional": {
            "subject": "Exclusive Offer Just for You",
            "message": f"Dear {guest_name},\n\nAs a valued guest, we're pleased to offer you an exclusive discount on your next stay at Glimmora.\n\nBook within the next 30 days and enjoy 15% off our best available rates.\n\nWe look forward to welcoming you back!\n\nBest regards,\nThe Glimmora Team"
        },
        "apology": {
            "subject": "Our Sincere Apologies",
            "message": f"Dear {guest_name},\n\nWe sincerely apologize for any inconvenience you may have experienced during your stay.\n\nYour satisfaction is our top priority, and we would like to make it right. Please accept our offer of a complimentary upgrade on your next visit.\n\nThank you for your understanding.\n\nBest regards,\nThe Glimmora Team"
        },
    }

    # If LANGCHAIN is available and we have API key, use AI drafting
    if LANGCHAIN_AVAILABLE and payload.template == "custom":
        # Get API key - prioritize env var, then settings
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            api_key = settings.openai_api_key if settings.openai_api_key else None

        logger.info(f"AI Draft - LangChain available: {LANGCHAIN_AVAILABLE}, API key present: {bool(api_key)}")

        if api_key:
            try:
                llm = ChatOpenAI(
                    model="gpt-4o-mini",
                    temperature=0.7,
                    api_key=api_key
                )

                # Build context about the guest
                guest_context = f"""
                Guest Name: {guest_name}
                Email: {guest.email or 'Not provided'}
                VIP Status: {'Yes' if guest.vip_status else 'No'}
                Loyalty Tier: {guest.loyalty_tier or 'Member'}
                Total Bookings: {guest.total_bookings or 0}
                Country: {guest.country or 'Unknown'}
                """

                system_prompt = f"""You are a professional hotel communications specialist for Glimmora, a luxury boutique hotel.

Write a personalized email for a guest based on the provided context and request.
The tone should be {payload.tone}.
Keep the email concise but warm and professional.
Do not include subject line in the message body.

Guest Information:
{guest_context}

Additional Context: {payload.context or 'General guest communication'}
"""

                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=f"Write a {payload.tone} email for this guest. The purpose is: {payload.context or 'general outreach'}")
                ]

                logger.info(f"Calling OpenAI for guest {guest_id} with context: {payload.context}")
                response = llm.invoke(messages)

                # Generate a subject line
                subject_messages = [
                    SystemMessage(content="Generate a short, professional email subject line (max 60 characters) for a luxury hotel email."),
                    HumanMessage(content=f"Context: {payload.context or 'general outreach'}. Guest name: {guest_name}")
                ]
                subject_response = llm.invoke(subject_messages)

                logger.info(f"AI draft generated successfully for guest {guest_id}")
                return GuestDraftResponse(
                    success=True,
                    subject=subject_response.content.strip().strip('"'),
                    message=response.content.strip(),
                    template="ai_generated"
                )
            except Exception as e:
                logger.error(f"AI drafting failed for guest {guest_id}: {type(e).__name__}: {str(e)}")
                # Fall through to template-based response
        else:
            logger.warning("No OpenAI API key configured - using template fallback")

    # Use template-based response
    template_data = templates.get(payload.template, templates.get("welcome"))

    return GuestDraftResponse(
        success=True,
        subject=template_data["subject"],
        message=template_data["message"],
        template=payload.template
    )


# ============== ROOM CHANGE HISTORY ENDPOINT ==============

@router.get("/{guest_id}/room-change-history")
async def get_guest_room_change_history(
    guest_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Get room change history across all bookings for a guest.
    Returns all room changes made for any of the guest's bookings.
    """
    from app.models.bookings import RoomChanges
    from app.models.inventory import Room, RoomType
    from app.schemas.reservations import RoomChangeResponse, GuestRoomChangeHistoryResponse

    # Get guest
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    guest_name = f"{guest.first_name} {guest.last_name}".strip()

    # Find all guest IDs with same email (handles duplicates)
    guest_ids_to_search = [guest_id]
    if guest.email:
        try:
            matching_guests = (await session.exec(
                select(Guest.id).where(Guest.email == guest.email.lower().strip())
            )).all()
            guest_ids_to_search = list(set([guest_id] + list(matching_guests)))
        except Exception:
            pass

    # Get all bookings for the guest
    booking_ids = []

    # Query Booking table
    try:
        bookings_result = await session.exec(
            select(Booking.id).where(Booking.guest_id.in_(guest_ids_to_search))
        )
        booking_ids.extend(bookings_result.all())
    except Exception as e:
        logger.debug(f"Error fetching from Booking table: {e}")

    # Also query Reservation table for legacy bookings
    try:
        reservations_result = await session.exec(
            select(Reservation.id).where(Reservation.guest_id.in_(guest_ids_to_search))
        )
        booking_ids.extend(reservations_result.all())
    except Exception as e:
        logger.debug(f"Error fetching from Reservation table: {e}")

    # Deduplicate booking IDs
    booking_ids = list(set(booking_ids))

    if not booking_ids:
        return GuestRoomChangeHistoryResponse(
            guest_id=guest_id,
            guest_name=guest_name,
            total_room_changes=0,
            room_changes=[],
        )

    # Get all room changes for these bookings
    room_changes_result = await session.exec(
        select(RoomChanges)
        .where(RoomChanges.reservation_id.in_(booking_ids))
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

    return GuestRoomChangeHistoryResponse(
        guest_id=guest_id,
        guest_name=guest_name,
        total_room_changes=len(room_change_responses),
        room_changes=room_change_responses,
    )
