"""
Multi-Room Booking API (C-11).
Create N linked bookings when a guest needs multiple rooms.
Parent booking holds the group, child bookings are one per room.

DEPRECATION NOTICE:
    Multi-room booking creation is now supported directly via the main booking endpoint:
        POST /api/v1/bookings

    To create a multi-room booking, include a `rooms` array in the request payload:
        {
            "checkIn": "2024-01-15",
            "checkOut": "2024-01-18",
            "guestInfo": { ... },
            "rooms": [
                { "roomTypeId": 1, "adults": 2, "children": 0 },
                { "roomTypeId": 2, "adults": 2, "children": 1 }
            ]
        }

    This endpoint (/api/v1/multi-room/*) is maintained for backward compatibility
    and for managing existing group bookings (view, add room, cancel room).
    New integrations should use the main /api/v1/bookings endpoint.
"""
import uuid
from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.reservations import Booking, Guest, ReservationHistory
from app.models.inventory import Room, RoomType, DailyAvailability
from app.models.user import User
from app.core.business_date import get_business_date

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class RoomRequest(BaseModel):
    room_type_id: int
    adults: int = 1
    children: int = 0
    special_requests: Optional[str] = None

class MultiRoomBookingCreate(BaseModel):
    guest_id: int
    arrival_date: str  # YYYY-MM-DD
    departure_date: str  # YYYY-MM-DD
    rooms: List[RoomRequest]  # One entry per room needed
    payment_method: Optional[str] = "card"
    booking_source: Optional[str] = "Direct"
    corporate_account_id: Optional[int] = None

class AddRoomRequest(BaseModel):
    room_type_id: int
    adults: int = 1
    children: int = 0
    special_requests: Optional[str] = None


# ── Create Multi-Room Booking ────────────────────────────────────

@router.post("/create", status_code=status.HTTP_201_CREATED, deprecated=True)
async def create_multi_room_booking(
    payload: MultiRoomBookingCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Create a multi-room booking: one parent + N child bookings.

    DEPRECATED: Use POST /api/v1/bookings with a `rooms` array instead.
    This endpoint is maintained for backward compatibility.
    """
    if len(payload.rooms) < 2:
        raise HTTPException(status_code=400, detail="Multi-room booking requires at least 2 rooms")

    arrival = date.fromisoformat(payload.arrival_date)
    departure = date.fromisoformat(payload.departure_date)
    business_date = await get_business_date(session)

    if departure <= arrival:
        raise HTTPException(status_code=400, detail="Departure must be after arrival")
    if arrival < business_date:
        raise HTTPException(status_code=400, detail="Arrival date cannot be in the past")

    guest = await session.get(Guest, payload.guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    nights = (departure - arrival).days

    # Validate all room types and check availability
    room_types = {}
    for i, room_req in enumerate(payload.rooms):
        rt = await session.get(RoomType, room_req.room_type_id)
        if not rt:
            raise HTTPException(status_code=404, detail=f"Room type ID {room_req.room_type_id} not found (room #{i+1})")
        room_types[i] = rt

    # Generate group booking ID
    group_id = int(datetime.utcnow().timestamp() * 1000) % 1000000

    # Look up dynamic rates from DailyAvailability (pricing-rule-adjusted rates)
    from app.core.tax import calculate_booking_taxes
    dynamic_rates: dict[int, float] = {}
    for rt_id_key in set(rt.id for rt in room_types.values()):
        da_result = await session.exec(
            select(DailyAvailability).where(
                and_(
                    DailyAvailability.room_type_id == rt_id_key,
                    DailyAvailability.date == arrival,
                )
            ).limit(1)
        )
        da = da_result.first()
        if da and da.base_rate:
            dynamic_rates[rt_id_key] = da.base_rate

    # Create parent booking (first room)
    first_rt = room_types[0]
    first_req = payload.rooms[0]
    per_night_rate = dynamic_rates.get(first_rt.id, first_rt.base_price or 0)
    tax_calc = calculate_booking_taxes(per_night_rate, nights)
    base_price = tax_calc["calculated_base"]
    taxes = tax_calc["taxes"]
    service_fee = tax_calc["service_fee"]

    parent = Booking(
        booking_number=f"BK-{uuid.uuid4().hex[:8].upper()}",
        confirmation_code=f"GRP-{uuid.uuid4().hex[:6].upper()}",
        guest_id=payload.guest_id,
        user_id=current_user.id,
        room_type_id=first_rt.id,
        arrival_date=arrival,
        departure_date=departure,
        nights=nights,
        adults=first_req.adults,
        children=first_req.children,
        status="confirmed",
        payment_status="pending",
        payment_method=payload.payment_method,
        booking_source=payload.booking_source,
        base_price=base_price,
        taxes=taxes,
        service_fee=service_fee,
        total_price=round(base_price + taxes + service_fee, 2),
        is_group_booking=True,
        group_booking_id=group_id,
        number_of_rooms=len(payload.rooms),
        corporate_account_id=payload.corporate_account_id,
        special_requests=first_req.special_requests,
        created_by=current_user.id,
    )
    session.add(parent)
    await session.flush()
    await session.refresh(parent)

    child_bookings = [parent]

    # Create child bookings for remaining rooms
    for i, room_req in enumerate(payload.rooms[1:], start=1):
        rt = room_types[i]
        child_per_night = dynamic_rates.get(rt.id, rt.base_price or 0)
        child_tax_calc = calculate_booking_taxes(child_per_night, nights)
        bp = child_tax_calc["calculated_base"]
        tx = child_tax_calc["taxes"]
        sf = child_tax_calc["service_fee"]

        child = Booking(
            booking_number=f"BK-{uuid.uuid4().hex[:8].upper()}",
            confirmation_code=f"GRP-{uuid.uuid4().hex[:6].upper()}",
            guest_id=payload.guest_id,
            user_id=current_user.id,
            room_type_id=rt.id,
            arrival_date=arrival,
            departure_date=departure,
            nights=nights,
            adults=room_req.adults,
            children=room_req.children,
            status="confirmed",
            payment_status="pending",
            payment_method=payload.payment_method,
            booking_source=payload.booking_source,
            base_price=bp,
            taxes=tx,
            service_fee=sf,
            total_price=round(bp + tx + sf, 2),
            is_group_booking=True,
            group_booking_id=group_id,
            number_of_rooms=len(payload.rooms),
            parent_booking_id=parent.id,
            corporate_account_id=payload.corporate_account_id,
            special_requests=room_req.special_requests,
            created_by=current_user.id,
        )
        session.add(child)
        await session.flush()
        await session.refresh(child)
        child_bookings.append(child)

    await session.commit()

    return {
        "message": f"Multi-room booking created: {len(payload.rooms)} rooms",
        "group_booking_id": group_id,
        "parent_booking_id": parent.id,
        "bookings": [{
            "id": b.id,
            "booking_number": b.booking_number,
            "room_type_id": b.room_type_id,
            "is_parent": b.parent_booking_id is None,
            "adults": b.adults,
            "children": b.children,
            "total_price": b.total_price,
        } for b in child_bookings],
        "total_price": round(sum(b.total_price for b in child_bookings), 2),
    }


# ── Get Linked Bookings ─────────────────────────────────────────

@router.get("/{parent_booking_id}")
async def get_linked_bookings(
    parent_booking_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Get all bookings in a multi-room group."""
    parent = await session.get(Booking, parent_booking_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not parent.group_booking_id:
        raise HTTPException(status_code=400, detail="This booking is not part of a multi-room group")

    # Find all bookings with same group_booking_id
    all_bookings = (await session.exec(
        select(Booking).where(Booking.group_booking_id == parent.group_booking_id)
    )).all()

    guest = await session.get(Guest, parent.guest_id)

    bookings_data = []
    for b in all_bookings:
        rt = await session.get(RoomType, b.room_type_id)
        room = await session.get(Room, b.room_id) if b.room_id else None
        bookings_data.append({
            "id": b.id,
            "booking_number": b.booking_number,
            "is_parent": b.parent_booking_id is None,
            "room_type": rt.name if rt else None,
            "room_number": room.number if room else None,
            "status": b.status,
            "adults": b.adults,
            "children": b.children,
            "total_price": b.total_price,
        })

    return {
        "group_booking_id": parent.group_booking_id,
        "parent_booking_id": parent.id if parent.parent_booking_id is None else parent.parent_booking_id,
        "guest_name": f"{guest.first_name or ''} {guest.last_name or ''}".strip() if guest else None,
        "arrival_date": str(parent.arrival_date),
        "departure_date": str(parent.departure_date),
        "nights": (parent.departure_date - parent.arrival_date).days,
        "payment_method": parent.payment_method or "card",
        "booking_source": parent.booking_source or "Direct",
        "number_of_rooms": len(all_bookings),
        "total_price": round(sum(b.total_price for b in all_bookings), 2),
        "bookings": bookings_data,
    }


# ── Add Room to Group ────────────────────────────────────────────

@router.post("/{parent_booking_id}/add-room", status_code=status.HTTP_201_CREATED)
async def add_room_to_group(
    parent_booking_id: int,
    payload: AddRoomRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Add another room to an existing multi-room booking group."""
    parent = await session.get(Booking, parent_booking_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Booking not found")
    if not parent.group_booking_id:
        raise HTTPException(status_code=400, detail="This booking is not part of a multi-room group")
    if parent.parent_booking_id is not None:
        # Navigate to the actual parent
        parent = await session.get(Booking, parent.parent_booking_id)

    rt = await session.get(RoomType, payload.room_type_id)
    if not rt:
        raise HTTPException(status_code=404, detail="Room type not found")

    from app.core.tax import calculate_booking_taxes
    nights = (parent.departure_date - parent.arrival_date).days
    # Look up dynamic rate from DailyAvailability
    da_result = await session.exec(
        select(DailyAvailability).where(
            and_(
                DailyAvailability.room_type_id == rt.id,
                DailyAvailability.date == parent.arrival_date,
            )
        ).limit(1)
    )
    da = da_result.first()
    add_room_rate = (da.base_rate if da and da.base_rate else None) or rt.base_price or 0
    add_room_tax_calc = calculate_booking_taxes(add_room_rate, nights)
    bp = add_room_tax_calc["calculated_base"]
    tx = add_room_tax_calc["taxes"]
    sf = add_room_tax_calc["service_fee"]

    import uuid
    child = Booking(
        booking_number=f"BK-{uuid.uuid4().hex[:8].upper()}",
        confirmation_code=f"GRP-{uuid.uuid4().hex[:6].upper()}",
        guest_id=parent.guest_id,
        user_id=current_user.id,
        room_type_id=rt.id,
        arrival_date=parent.arrival_date,
        departure_date=parent.departure_date,
        nights=nights,
        adults=payload.adults,
        children=payload.children,
        status="confirmed",
        payment_status="pending",
        payment_method=parent.payment_method,
        booking_source=parent.booking_source,
        base_price=bp,
        taxes=tx,
        service_fee=sf,
        total_price=round(bp + tx + sf, 2),
        is_group_booking=True,
        group_booking_id=parent.group_booking_id,
        parent_booking_id=parent.id,
        number_of_rooms=parent.number_of_rooms + 1,
        corporate_account_id=parent.corporate_account_id,
        special_requests=payload.special_requests,
        created_by=current_user.id,
    )
    session.add(child)

    # Update room count on all group bookings
    group_bookings = (await session.exec(
        select(Booking).where(Booking.group_booking_id == parent.group_booking_id)
    )).all()
    new_count = len(group_bookings) + 1
    for b in group_bookings:
        b.number_of_rooms = new_count
        session.add(b)

    await session.commit()
    await session.refresh(child)

    return {
        "message": f"Room added to group. Total rooms: {new_count}",
        "booking_id": child.id,
        "booking_number": child.booking_number,
        "room_type": rt.name,
        "total_rooms": new_count,
    }


# ── Cancel One Room from Group ───────────────────────────────────

@router.post("/{booking_id}/cancel-room")
async def cancel_room_from_group(
    booking_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Cancel a single room from a multi-room group."""
    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    if not booking.group_booking_id:
        raise HTTPException(status_code=400, detail="Not part of a multi-room group")
    if booking.status in ("checked_in", "checked_out"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel a {booking.status} booking")

    # Don't cancel the parent if it's the last remaining room
    group_bookings = (await session.exec(
        select(Booking).where(
            Booking.group_booking_id == booking.group_booking_id,
            Booking.status.notin_(["cancelled", "no_show"]),
        )
    )).all()

    if len(group_bookings) <= 1:
        raise HTTPException(status_code=400, detail="Cannot cancel last room in group. Cancel the entire booking instead.")

    booking.status = "cancelled"
    booking.cancellation_reason = "Removed from multi-room group"
    booking.cancelled_at = datetime.utcnow()

    # Update room count on remaining bookings
    new_count = len(group_bookings) - 1
    for b in group_bookings:
        if b.id != booking_id:
            b.number_of_rooms = new_count
            session.add(b)

    session.add(booking)

    history = ReservationHistory(
        reservation_id=booking.id,
        action="cancelled",
        changed_by=current_user.id,
        old_value=booking.status,
        new_value="cancelled (removed from multi-room group)",
        created_at=datetime.utcnow(),
    )
    session.add(history)

    await session.commit()
    return {"message": f"Room cancelled. {new_count} rooms remaining in group."}
