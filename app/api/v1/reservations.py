from typing import List, Optional, Dict, Any
from datetime import date, datetime
import json
from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.reservations import Reservation, ReservationHistory, ReservationNote, Waitlist, GroupBooking, Guest, Booking
from app.models.user import User
from app.api.v1.webhooks import broadcast_sse_event
from app.schemas.reservations import (
    ReservationCreate, ReservationRead,
    BookingCreate, BookingUpdate, BookingResponse, BookingListResponse
)
from app.services.reservation_service import (
    create_reservation, update_reservation, cancel_reservation,
    assign_room, check_availability
)

router = APIRouter()


class ReservationUpdate(BaseModel):
    arrival_date: Optional[date] = None
    departure_date: Optional[date] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    special_requests: Optional[str] = None
    room_id: Optional[int] = None
    rate_plan_id: Optional[int] = None
    # New fields
    vip_flag: Optional[bool] = None
    number_of_guests: Optional[int] = None
    discount_code: Optional[str] = None
    discount_amount: Optional[float] = None


class ReservationNoteCreate(BaseModel):
    note: str
    note_type: str = "general"
    is_internal: bool = False


class WaitlistCreate(BaseModel):
    guest: dict
    arrival_date: date
    departure_date: date
    adults: int = 1
    children: int = 0
    room_type_preference: Optional[str] = None
    rate_plan_id: Optional[int] = None
    priority: int = 0
    notes: Optional[str] = None


@router.get("", response_model=List[ReservationRead])
async def list_reservations(
    status_filter: Optional[str] = Query(None, alias="status"),
    arrival_from: Optional[date] = Query(None),
    arrival_to: Optional[date] = Query(None),
    guest_name: Optional[str] = Query(None),
    confirmation_code: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    query = select(Reservation)
    
    if status_filter:
        query = query.where(Reservation.status == status_filter)
    if arrival_from:
        query = query.where(Reservation.arrival_date >= arrival_from)
    if arrival_to:
        query = query.where(Reservation.arrival_date <= arrival_to)
    if confirmation_code:
        query = query.where(Reservation.confirmation_code == confirmation_code.upper())
    if guest_name:
        # Join with Guest table
        query = query.join(Guest).where(
            or_(
                Guest.first_name.ilike(f"%{guest_name}%"),
                Guest.last_name.ilike(f"%{guest_name}%")
            )
        )
    
    result = await session.execute(query.order_by(Reservation.arrival_date.desc()))
    items = result.scalars().all()
    return [ReservationRead.model_validate(i.__dict__) for i in items]


@router.post("", response_model=ReservationRead, status_code=status.HTTP_201_CREATED)
async def create_reservation_endpoint(
    payload: ReservationCreate,
    allow_overbooking: bool = False,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    import logging

    # Validate required fields
    if not payload.guest:
        raise HTTPException(status_code=400, detail="Guest information is required")
    if not payload.guest.first_name or not payload.guest.last_name:
        raise HTTPException(status_code=400, detail="Guest first_name and last_name are required")
    if not payload.arrival_date or not payload.departure_date:
        raise HTTPException(status_code=400, detail="arrival_date and departure_date are required")
    if payload.arrival_date >= payload.departure_date:
        raise HTTPException(status_code=400, detail="departure_date must be after arrival_date")

    try:
        res = await create_reservation(session, payload, user_id=current_user.id, allow_overbooking=allow_overbooking)
        await session.commit()
        await session.refresh(res)
        return ReservationRead.model_validate(res.__dict__)
    except ValueError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        logging.error(f"Error creating reservation: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create reservation: {str(e)}")


@router.get("/{reservation_id}", response_model=ReservationRead)
async def get_reservation(
    reservation_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    res = await session.get(Reservation, reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return ReservationRead.model_validate(res.__dict__)


@router.patch("/{reservation_id}", response_model=ReservationRead)
async def update_reservation_endpoint(
    reservation_id: int,
    payload: ReservationUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    updates = payload.model_dump(exclude_unset=True)
    res = await update_reservation(session, reservation_id, updates, user_id=current_user.id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    await session.commit()
    await session.refresh(res)
    return ReservationRead.model_validate(res.__dict__)


@router.post("/{reservation_id}/cancel", response_model=ReservationRead)
async def cancel_reservation_endpoint(
    reservation_id: int,
    reason: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    res = await cancel_reservation(session, reservation_id, reason, user_id=current_user.id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found or cannot be cancelled")
    await session.commit()
    await session.refresh(res)
    return ReservationRead.model_validate(res.__dict__)


@router.post("/{reservation_id}/assign-room")
async def assign_room_endpoint(
    reservation_id: int,
    room_id: Optional[int] = None,
    auto_assign: bool = True,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    room = await assign_room(session, reservation_id, room_id, auto_assign)
    if not room:
        raise HTTPException(status_code=400, detail="Room assignment failed")
    await session.commit()
    return {"room_id": room.id, "room_number": room.number, "status": "assigned"}


@router.get("/{reservation_id}/history")
async def get_reservation_history(
    reservation_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    history = (await session.execute(
        select(ReservationHistory)
        .where(ReservationHistory.reservation_id == reservation_id)
        .order_by(ReservationHistory.created_at.desc())
    )).scalars().all()
    return [{"id": h.id, "action": h.action, "old_value": h.old_value, "new_value": h.new_value,
             "notes": h.notes, "changed_by": h.changed_by, "created_at": h.created_at} for h in history]


@router.post("/{reservation_id}/notes", status_code=status.HTTP_201_CREATED)
async def add_reservation_note(
    reservation_id: int,
    payload: ReservationNoteCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    note = ReservationNote(
        reservation_id=reservation_id,
        note=payload.note,
        note_type=payload.note_type,
        is_internal=payload.is_internal,
        created_by=current_user.id
    )
    session.add(note)
    await session.commit()
    await session.refresh(note)
    return {"id": note.id, "note": note.note, "note_type": note.note_type, "created_at": note.created_at}


@router.get("/{reservation_id}/notes")
async def get_reservation_notes(
    reservation_id: int,
    include_internal: bool = False,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    query = select(ReservationNote).where(ReservationNote.reservation_id == reservation_id)
    if not include_internal:
        query = query.where(ReservationNote.is_internal == False)
    notes = (await session.execute(query.order_by(ReservationNote.created_at.desc()))).scalars().all()
    return [{"id": n.id, "note": n.note, "note_type": n.note_type, "is_internal": n.is_internal,
             "created_by": n.created_by, "created_at": n.created_at} for n in notes]


# Waitlist endpoints
@router.get("/waitlist", response_model=List[dict])
async def list_waitlist(
    status: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    query = select(Waitlist)
    if status:
        query = query.where(Waitlist.status == status)
    waitlist = (await session.execute(query.order_by(Waitlist.priority.desc(), Waitlist.created_at.asc()))).scalars().all()
    return [{"id": w.id, "guest_id": w.guest_id, "arrival_date": w.arrival_date,
             "departure_date": w.departure_date, "status": w.status, "priority": w.priority} for w in waitlist]


@router.post("/waitlist", status_code=status.HTTP_201_CREATED)
async def create_waitlist_entry(
    payload: WaitlistCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    from app.schemas.reservations import GuestCreate
    from app.services.reservation_service import create_guest
    
    # Convert guest dict to proper format
    guest_data = payload.guest if isinstance(payload.guest, dict) else payload.guest.model_dump() if hasattr(payload.guest, 'model_dump') else payload.guest
    guest, _ = await create_guest(session, guest_data)
    waitlist = Waitlist(
        guest_id=guest.id,
        arrival_date=payload.arrival_date,
        departure_date=payload.departure_date,
        adults=payload.adults,
        children=payload.children,
        room_type_preference=payload.room_type_preference,
        rate_plan_id=payload.rate_plan_id,
        priority=payload.priority,
        notes=payload.notes
    )
    session.add(waitlist)
    await session.commit()
    await session.refresh(waitlist)
    return {"id": waitlist.id, "status": "created"}


# Group booking endpoints
@router.get("/groups", response_model=List[dict])
async def list_group_bookings(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    groups = (await session.execute(select(GroupBooking).order_by(GroupBooking.created_at.desc()))).scalars().all()
    return [{"id": g.id, "group_code": g.group_code, "group_name": g.group_name,
             "arrival_date": g.arrival_date, "status": g.status} for g in groups]


# ============== NEW BOOKING V2.0 ENDPOINTS ==============

def serialize_booking(booking: Booking) -> dict:
    """Helper to serialize Booking model to dict for response"""
    data = {
        "id": booking.id,
        "booking_number": booking.booking_number,
        "confirmation_code": booking.confirmation_code,
        "user_id": booking.user_id,
        "guest_id": booking.guest_id,
        "room_type_id": booking.room_type_id,
        "room_id": booking.room_id,
        "arrival_date": booking.arrival_date,
        "departure_date": booking.departure_date,
        "check_in_date": booking.check_in_date,
        "check_out_date": booking.check_out_date,
        "adults": booking.adults,
        "children": booking.children,
        "infants": booking.infants,
        "nights": booking.nights,
        "status": booking.status,
        "payment_status": booking.payment_status,
        "booking_source": booking.booking_source,
        "channel": booking.channel,
        "base_price": booking.base_price,
        "taxes": booking.taxes,
        "service_fee": booking.service_fee,
        "total_price": booking.total_price,
        "deposit_amount": booking.deposit_amount,
        "balance_due": booking.balance_due,
        "special_requests": booking.special_requests,
        "internal_notes": booking.internal_notes,
        "cancellation_reason": booking.cancellation_reason,
        "cancelled_at": booking.cancelled_at,
        "rate_plan_id": booking.rate_plan_id,
        "corporate_account_id": booking.corporate_account_id,
        "is_group_booking": booking.is_group_booking,
        "group_booking_id": booking.group_booking_id,
        "parent_booking_id": booking.parent_booking_id,
        "number_of_rooms": booking.number_of_rooms,
        "payment_method": booking.payment_method,
        # New fields
        "vip_flag": booking.vip_flag,
        "number_of_guests": booking.number_of_guests,
        "upsells": json.loads(booking.upsells) if booking.upsells and isinstance(booking.upsells, str) else booking.upsells,
        "discount_code": booking.discount_code,
        "discount_amount": booking.discount_amount,
        "commission_rate": booking.commission_rate,
        "commission_amount": booking.commission_amount,
        "net_revenue": booking.net_revenue,
        "modification_count": booking.modification_count,
        "created_by": booking.created_by,
        "created_at": booking.created_at,
        "updated_at": booking.updated_at,
    }
    return data


@router.get("/bookings", response_model=BookingListResponse)
async def list_bookings(
    status_filter: Optional[str] = Query(None, alias="status"),
    payment_status: Optional[str] = Query(None),
    arrival_from: Optional[date] = Query(None),
    arrival_to: Optional[date] = Query(None),
    guest_id: Optional[int] = Query(None),
    vip_only: bool = Query(False),
    booking_source: Optional[str] = Query(None),
    source: Optional[str] = Query(None, description="Alias for booking_source - used by channel manager"),
    limit: Optional[int] = Query(None, ge=1, le=1000, description="Limit number of results (alias for page_size)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List bookings with filtering and pagination (V2.0 Booking model)"""
    query = select(Booking)

    # Use source as alias for booking_source (for channel manager compatibility)
    if source and not booking_source:
        booking_source = source
    
    # Use limit as alias for page_size (for channel manager compatibility)
    if limit and limit > 0:
        page_size = min(limit, 1000)

    if status_filter:
        query = query.where(Booking.status == status_filter)
    if payment_status:
        query = query.where(Booking.payment_status == payment_status)
    if arrival_from:
        query = query.where(Booking.arrival_date >= arrival_from)
    if arrival_to:
        query = query.where(Booking.arrival_date <= arrival_to)
    if guest_id:
        query = query.where(Booking.guest_id == guest_id)
    if vip_only:
        query = query.where(Booking.vip_flag == True)
    if booking_source:
        query = query.where(Booking.booking_source == booking_source)

    # Count total
    count_query = select(Booking)
    if status_filter:
        count_query = count_query.where(Booking.status == status_filter)
    if payment_status:
        count_query = count_query.where(Booking.payment_status == payment_status)
    if arrival_from:
        count_query = count_query.where(Booking.arrival_date >= arrival_from)
    if arrival_to:
        count_query = count_query.where(Booking.arrival_date <= arrival_to)
    if guest_id:
        count_query = count_query.where(Booking.guest_id == guest_id)
    if vip_only:
        count_query = count_query.where(Booking.vip_flag == True)
    if booking_source:
        count_query = count_query.where(Booking.booking_source == booking_source)

    count_result = await session.execute(count_query)
    total = len(count_result.scalars().all())

    # Paginate
    offset = (page - 1) * page_size
    query = query.order_by(Booking.created_at.desc()).offset(offset).limit(page_size)

    result = await session.execute(query)
    bookings = result.scalars().all()

    total_pages = (total + page_size - 1) // page_size

    return BookingListResponse(
        items=[BookingResponse(**serialize_booking(b)) for b in bookings],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.post("/bookings", response_model=BookingResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    payload: BookingCreate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Create a new booking (V2.0 Booking model)"""
    import secrets
    import logging

    # Validate guest exists
    guest = await session.get(Guest, payload.guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    # Validate dates
    if payload.arrival_date >= payload.departure_date:
        raise HTTPException(status_code=400, detail="Departure date must be after arrival date")

    # Calculate nights
    nights = (payload.departure_date - payload.arrival_date).days

    # Generate booking number and confirmation code
    booking_number = f"BK-{datetime.utcnow().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
    confirmation_code = secrets.token_hex(4).upper()

    # Prepare upsells as JSON string if provided
    upsells_json = json.dumps(payload.upsells) if payload.upsells else None

    # Calculate net revenue if commission is provided
    net_revenue = payload.net_revenue
    if net_revenue is None and payload.commission_amount is not None:
        net_revenue = payload.total_price - payload.commission_amount

    try:
        booking = Booking(
            booking_number=booking_number,
            confirmation_code=confirmation_code,
            user_id=current_user.id,
            guest_id=payload.guest_id,
            room_type_id=payload.room_type_id,
            room_id=payload.room_id,
            arrival_date=payload.arrival_date,
            departure_date=payload.departure_date,
            adults=payload.adults,
            children=payload.children,
            infants=payload.infants,
            nights=nights,
            status="pending",
            payment_status="pending",
            booking_source=payload.booking_source,
            channel=payload.channel,
            base_price=payload.base_price,
            taxes=payload.taxes,
            service_fee=payload.service_fee,
            total_price=payload.total_price,
            deposit_amount=payload.deposit_amount,
            balance_due=payload.balance_due or payload.total_price,
            special_requests=payload.special_requests,
            internal_notes=payload.internal_notes,
            rate_plan_id=payload.rate_plan_id,
            corporate_account_id=payload.corporate_account_id,
            is_group_booking=payload.is_group_booking,
            group_booking_id=payload.group_booking_id,
            # New fields
            vip_flag=payload.vip_flag,
            number_of_guests=payload.number_of_guests or (payload.adults + payload.children + payload.infants),
            upsells=upsells_json,
            discount_code=payload.discount_code,
            discount_amount=payload.discount_amount,
            commission_rate=payload.commission_rate,
            commission_amount=payload.commission_amount,
            net_revenue=net_revenue,
            modification_count=0,
            created_by=current_user.id,
        )

        session.add(booking)
        await session.commit()
        await session.refresh(booking)

        # Broadcast SSE event for real-time frontend updates
        background_tasks.add_task(
            broadcast_sse_event,
            "booking.created",
            {
                "booking_id": booking.id,
                "booking_number": booking.booking_number,
                "confirmation_code": booking.confirmation_code,
                "guest_id": booking.guest_id,
                "room_type_id": booking.room_type_id,
                "arrival_date": booking.arrival_date.isoformat() if booking.arrival_date else None,
                "departure_date": booking.departure_date.isoformat() if booking.departure_date else None,
                "status": booking.status,
                "channel": booking.channel or "direct"
            }
        )

        return BookingResponse(**serialize_booking(booking))

    except Exception as e:
        await session.rollback()
        logging.error(f"Error creating booking: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create booking: {str(e)}")


@router.get("/bookings/{booking_id}", response_model=BookingResponse)
async def get_booking(
    booking_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get a single booking by ID (V2.0 Booking model)"""
    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    return BookingResponse(**serialize_booking(booking))


@router.patch("/bookings/{booking_id}", response_model=BookingResponse)
async def update_booking_endpoint(
    booking_id: int,
    payload: BookingUpdate,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update a booking (V2.0 Booking model)"""
    import logging

    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    updates = payload.model_dump(exclude_unset=True)

    # Handle upsells serialization
    if "upsells" in updates and updates["upsells"] is not None:
        updates["upsells"] = json.dumps(updates["upsells"])

    # Recalculate nights if dates changed
    if "arrival_date" in updates or "departure_date" in updates:
        arrival = updates.get("arrival_date", booking.arrival_date)
        departure = updates.get("departure_date", booking.departure_date)
        if arrival >= departure:
            raise HTTPException(status_code=400, detail="Departure date must be after arrival date")
        updates["nights"] = (departure - arrival).days

    # Recalculate net revenue if commission changed
    if "commission_amount" in updates or "total_price" in updates:
        total = updates.get("total_price", booking.total_price)
        commission = updates.get("commission_amount", booking.commission_amount)
        if commission is not None:
            updates["net_revenue"] = total - commission

    # Increment modification count
    updates["modification_count"] = booking.modification_count + 1
    updates["updated_at"] = datetime.utcnow()

    try:
        for key, value in updates.items():
            setattr(booking, key, value)

        await session.commit()
        await session.refresh(booking)

        # Broadcast SSE event for real-time frontend updates
        background_tasks.add_task(
            broadcast_sse_event,
            "booking.modified",
            {
                "booking_id": booking.id,
                "booking_number": booking.booking_number,
                "changes": payload.model_dump(exclude_unset=True)
            }
        )

        return BookingResponse(**serialize_booking(booking))

    except Exception as e:
        await session.rollback()
        logging.error(f"Error updating booking: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update booking: {str(e)}")


@router.post("/bookings/{booking_id}/cancel", response_model=BookingResponse)
async def cancel_booking_endpoint(
    booking_id: int,
    background_tasks: BackgroundTasks,
    reason: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Cancel a booking (V2.0 Booking model)"""
    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    if booking.status in ["checked_in", "checked_out"]:
        raise HTTPException(status_code=400, detail=f"Cannot cancel a booking that is {booking.status}")

    if booking.status == "cancelled":
        raise HTTPException(status_code=400, detail="Booking is already cancelled")

    booking.status = "cancelled"
    booking.cancellation_reason = reason
    booking.cancelled_at = datetime.utcnow()
    booking.modification_count += 1
    booking.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(booking)

    # Broadcast SSE event for real-time frontend updates
    background_tasks.add_task(
        broadcast_sse_event,
        "booking.cancelled",
        {
            "booking_id": booking.id,
            "booking_number": booking.booking_number,
            "reason": reason
        }
    )

    return BookingResponse(**serialize_booking(booking))


@router.post("/bookings/{booking_id}/add-upsell")
async def add_booking_upsell(
    booking_id: int,
    item: str,
    price: float,
    quantity: int = 1,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Add an upsell item to a booking"""
    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Parse existing upsells
    upsells = []
    if booking.upsells:
        upsells = json.loads(booking.upsells) if isinstance(booking.upsells, str) else booking.upsells

    # Add new upsell
    new_upsell = {
        "item": item,
        "price": price,
        "quantity": quantity,
        "total": price * quantity,
        "added_at": datetime.utcnow().isoformat(),
        "added_by": current_user.id
    }
    upsells.append(new_upsell)

    # Update booking
    booking.upsells = json.dumps(upsells)
    booking.total_price += (price * quantity)
    booking.balance_due = (booking.balance_due or 0) + (price * quantity)
    booking.modification_count += 1
    booking.updated_at = datetime.utcnow()

    # Recalculate net revenue
    if booking.commission_rate:
        booking.commission_amount = booking.total_price * (booking.commission_rate / 100)
        booking.net_revenue = booking.total_price - booking.commission_amount

    await session.commit()

    return {
        "success": True,
        "message": f"Added {item} to booking",
        "upsell": new_upsell,
        "new_total": booking.total_price,
        "upsells": upsells
    }


@router.get("/bookings/{booking_id}/summary")
async def get_booking_summary(
    booking_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get a detailed summary of a booking including guest info and financials"""
    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    # Get guest info
    guest = await session.get(Guest, booking.guest_id)

    # Parse upsells
    upsells = []
    upsells_total = 0
    if booking.upsells:
        upsells = json.loads(booking.upsells) if isinstance(booking.upsells, str) else booking.upsells
        upsells_total = sum(u.get("total", u.get("price", 0)) for u in upsells)

    return {
        "booking": serialize_booking(booking),
        "guest": {
            "id": guest.id if guest else None,
            "name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
            "email": guest.email if guest else None,
            "phone": guest.phone if guest else None,
            "vip_status": guest.vip_status if guest else False,
            "loyalty_tier": guest.loyalty_tier if guest else None,
        },
        "financials": {
            "base_price": booking.base_price,
            "taxes": booking.taxes,
            "service_fee": booking.service_fee,
            "upsells_total": upsells_total,
            "discount_amount": booking.discount_amount,
            "total_price": booking.total_price,
            "deposit_paid": booking.deposit_amount or 0,
            "balance_due": booking.balance_due or 0,
            "commission_rate": booking.commission_rate,
            "commission_amount": booking.commission_amount,
            "net_revenue": booking.net_revenue,
        },
        "upsells": upsells,
    }


