import secrets
import json
from datetime import date, datetime, timedelta
from typing import Optional, List, Tuple
from sqlmodel import select, and_, or_, func
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.reservations import Reservation, Booking, Guest, ReservationHistory, ReservationNote, Waitlist, GroupBooking
from app.models.inventory import Room, RatePlan, RoomType, DailyAvailability
from app.schemas.reservations import ReservationCreate


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

    # No rate plans exist - return 1 as fallback (will fail with FK error if not exists)
    return 1


def generate_confirmation_code() -> str:
    return f"GLM-{secrets.token_urlsafe(6).upper().replace('_', '').replace('-', '')[:6]}"


def generate_booking_number() -> str:
    """Generate a unique booking number (e.g., BK-20260107-ABC123)"""
    date_part = datetime.utcnow().strftime("%Y%m%d")
    random_part = secrets.token_urlsafe(4).upper().replace('_', '').replace('-', '')[:6]
    return f"BK-{date_part}-{random_part}"


def generate_group_code() -> str:
    return f"GRP-{secrets.token_urlsafe(6).upper().replace('_', '').replace('-', '')[:6]}"


def _normalize_name(value: Optional[str]) -> str:
    """Normalize a name for comparison: trim, collapse spaces, lowercase."""
    if not value:
        return ""
    import re
    return re.sub(r'\s+', ' ', value.strip()).lower()


async def create_guest(session: AsyncSession, data: dict) -> Tuple[Guest, int]:
    """Create or resolve a guest from booking payload.

    Returns (guest, profile_count) where profile_count is the total number of
    guest rows sharing the normalized email. The caller can use profile_count
    to decide whether to surface a duplicate-email warning.
    """
    profile_count = 0

    if data.get("email"):
        normalized_email = data["email"].lower().strip()

        # Find ALL guests with this email (not just the first match)
        all_matches = (await session.execute(
            select(Guest).where(Guest.email == normalized_email)
        )).scalars().all()
        profile_count = len(all_matches)

        if all_matches:
            submitted_first = _normalize_name(data.get("first_name"))
            submitted_last = _normalize_name(data.get("last_name"))

            # Try to find a profile whose name matches the submitted name
            matched_guest = None
            for g in all_matches:
                if (_normalize_name(g.first_name) == submitted_first
                        and _normalize_name(g.last_name) == submitted_last):
                    matched_guest = g
                    break

            if matched_guest:
                # Name matches — reuse this profile, update contact fields only
                name_fields = {'first_name', 'last_name'}
                for key, value in data.items():
                    if key in name_fields:
                        continue
                    if value is not None and value != '':
                        if key == 'phone' or str(value).strip():
                            setattr(matched_guest, key, value.strip() if isinstance(value, str) else value)
                matched_guest.updated_at = datetime.utcnow()
                await session.flush()
                # profile_count may increase by 0 (reused existing row)
                return matched_guest, profile_count
            else:
                # Email exists but name doesn't match any profile — insert a new guest
                # so the booking gets the name the booker actually typed.
                profile_count += 1  # new row will be created

    # Create new guest - ensure email is lowercase and stripped
    guest_data = {**data}
    if 'email' in guest_data and guest_data['email']:
        guest_data['email'] = guest_data['email'].lower().strip()
    # Strip string fields
    for key, value in guest_data.items():
        if isinstance(value, str):
            guest_data[key] = value.strip()

    guest = Guest(**guest_data)
    session.add(guest)
    await session.flush()

    # Auto-generate profile number (E-08): GP-NNNNNN
    if not guest.profile_number:
        guest.profile_number = f"GP-{guest.id:06d}"

    if profile_count == 0:
        profile_count = 1  # the newly-created row

    return guest, profile_count


async def compute_total(
    session: AsyncSession,
    rate_plan_id: int,
    arrival_date: date,
    departure_date: date,
    room_type: Optional[str] = None,
    promo_code: Optional[str] = None
) -> Tuple[float, str]:
    """Calculate total price using RoomType base price"""
    nights = (departure_date - arrival_date).days
    if nights < 1:
        nights = 1

    # First try to get price from RoomType if room_type is provided
    base_price = 0.0
    currency = "INR"

    if room_type:
        # Look up room type by name to get its base_price
        rt = (await session.execute(
            select(RoomType).where(RoomType.name == room_type)
        )).scalars().first()
        if rt:
            base_price = rt.base_price

    # Fallback to rate plan if no room type price found
    if base_price == 0.0:
        rp = (await session.execute(select(RatePlan).where(RatePlan.id == rate_plan_id))).scalars().first()
        if rp and rp.is_active:
            base_price = rp.base_price
            currency = rp.currency

    # Calculate total
    total = base_price * nights
    
    # Apply promo code if provided
    if promo_code:
        from app.models.inventory import PromoCode
        promo = (await session.execute(
            select(PromoCode).where(
                and_(
                    PromoCode.code == promo_code.upper(),
                    PromoCode.is_active == True,
                    PromoCode.valid_from <= arrival_date,
                    PromoCode.valid_until >= departure_date
                )
            )
        )).scalars().first()
        
        if promo:
            if promo.min_stay and nights < promo.min_stay:
                pass  # Doesn't meet min stay
            elif promo.max_stay and nights > promo.max_stay:
                pass  # Exceeds max stay
            else:
                if promo.discount_type == "percentage":
                    total = total * (1 - promo.discount_value / 100)
                else:  # fixed_amount
                    total = max(0, total - promo.discount_value)
    
    return total, currency


async def check_availability(
    session: AsyncSession,
    arrival_date: date,
    departure_date: date,
    room_type: Optional[str] = None,
    adults: int = 1,
    exclude_reservation_id: Optional[int] = None
) -> List[Room]:
    """
    Check room availability for given dates.
    Returns list of available rooms after excluding:
    - Rooms with overlapping confirmed reservations
    - Rooms with active holds (not expired)
    """
    from app.models.inventory import RoomHold

    # Get all rooms - exclude only out_of_order rooms (major issues, cannot be sold)
    # Dirty/occupied rooms are included because they may be available by arrival date
    # (dirty rooms will be cleaned, occupied rooms will check out)
    # Actual room assignment validation happens at check-in time
    query = select(Room).where(Room.status != "out_of_order")
    room_type_id = None

    if room_type:
        # First find the room type ID by name
        room_type_obj = (await session.execute(
            select(RoomType).where(RoomType.name == room_type)
        )).scalars().first()
        if room_type_obj:
            room_type_id = room_type_obj.id
            query = query.where(Room.room_type_id == room_type_obj.id)
        else:
            # No matching room type found
            return []

    if adults:
        query = query.where(Room.capacity >= adults)

    all_rooms = (await session.execute(query)).scalars().all()

    # Get reservations that overlap with the date range
    overlapping_query = select(Reservation).where(
        and_(
            Reservation.status.in_(["booked", "confirmed", "checked_in"]),
            Reservation.arrival_date < departure_date,
            Reservation.departure_date > arrival_date
        )
    )
    if exclude_reservation_id:
        overlapping_query = overlapping_query.where(Reservation.id != exclude_reservation_id)

    overlapping = (await session.execute(overlapping_query)).scalars().all()

    # Get room IDs that are booked (have specific room assigned)
    booked_room_ids = {r.room_id for r in overlapping if r.room_id}

    # Also check for active room holds (not expired)
    hold_query = select(RoomHold).where(
        and_(
            RoomHold.status == "active",
            RoomHold.expires_at > datetime.utcnow(),
            RoomHold.arrival_date < departure_date,
            RoomHold.departure_date > arrival_date
        )
    )
    if room_type_id:
        hold_query = hold_query.where(RoomHold.room_type_id == room_type_id)

    active_holds = (await session.execute(hold_query)).scalars().all()

    # Get room IDs that are held
    held_room_ids = {h.room_id for h in active_holds if h.room_id}

    # Also check Booking table (V2.0 bookings) for overlapping date ranges
    booking_overlap_query = select(Booking.room_id).where(
        and_(
            Booking.room_id.isnot(None),
            Booking.status.in_(["booked", "confirmed", "checked_in", "pending"]),
            Booking.arrival_date < departure_date,
            Booking.departure_date > arrival_date
        )
    )
    booking_overlaps = (await session.execute(booking_overlap_query)).scalars().all()
    booked_via_v2_ids = {r for r in booking_overlaps if r is not None}

    # Combine all unavailable room IDs (legacy reservations + holds + V2.0 bookings)
    unavailable_room_ids = booked_room_ids | held_room_ids | booked_via_v2_ids

    # Filter available rooms
    available = [r for r in all_rooms if r.id not in unavailable_room_ids]

    return available


async def validate_restrictions(
    session: AsyncSession,
    arrival_date: date,
    departure_date: date,
    room_type_id: int,
) -> Optional[str]:
    """
    Validate booking against DailyAvailability restrictions.
    Returns None if all restrictions pass, or an error message string if violated.

    Only enforces restrictions that were explicitly set via the channel manager
    restrictions UI (is_closed, closed_to_arrival, closed_to_departure, min_stay > 1,
    max_stay). Records created solely for rate/availability tracking are ignored.

    Non-fatal: catches exceptions so booking flow is never broken by restriction checks.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        nights = (departure_date - arrival_date).days
        if nights < 1:
            return "Departure date must be after arrival date"

        # Fetch only DailyAvailability rows that have at least one active restriction
        # This avoids blocking bookings due to records created for rate tracking only
        restrictions = (await session.execute(
            select(DailyAvailability).where(
                and_(
                    DailyAvailability.room_type_id == room_type_id,
                    DailyAvailability.date >= arrival_date,
                    DailyAvailability.date < departure_date,
                    or_(
                        DailyAvailability.is_closed == True,
                        DailyAvailability.closed_to_arrival == True,
                        DailyAvailability.closed_to_departure == True,
                        DailyAvailability.min_stay > 1,
                        DailyAvailability.max_stay.isnot(None),
                    ),
                )
            )
        )).scalars().all()

        if not restrictions:
            return None

        for day in restrictions:
            date_str = day.date.isoformat()

            if day.is_closed:
                logger.info(f"Restriction: stop sell on {date_str} for room_type {room_type_id}")
                return f"Bookings are closed (stop sell) for {date_str}"

            if day.closed_to_arrival and day.date == arrival_date:
                return f"Arrivals are not allowed on {date_str} (closed to arrival)"

            if day.date == arrival_date and day.min_stay and day.min_stay > 1 and nights < day.min_stay:
                return f"Minimum stay is {day.min_stay} night(s) for arrival on {date_str}, but requested {nights}"

            if day.date == arrival_date and day.max_stay and nights > day.max_stay:
                return f"Maximum stay is {day.max_stay} night(s) for arrival on {date_str}, but requested {nights}"

        # Check CTD on departure date (not in the range above since query uses date < departure_date)
        departure_restriction = (await session.execute(
            select(DailyAvailability).where(
                and_(
                    DailyAvailability.room_type_id == room_type_id,
                    DailyAvailability.date == departure_date,
                    DailyAvailability.closed_to_departure == True,
                )
            )
        )).scalars().first()

        if departure_restriction:
            return f"Departures are not allowed on {departure_date.isoformat()} (closed to departure)"

        return None

    except Exception as e:
        # Never block a booking due to restriction check failures
        logger.warning(f"Restriction validation error (allowing booking): {e}")
        return None


async def assign_room(
    session: AsyncSession,
    reservation_id: int,
    room_id: Optional[int] = None,
    auto_assign: bool = True
) -> Optional[Room]:
    """Assign a room to a reservation"""
    reservation = await session.get(Reservation, reservation_id)
    if not reservation:
        return None
    
    if room_id:
        # Check if room is available
        room = await session.get(Room, room_id)
        if not room:
            return None

        # Validate room status - dirty/occupied rooms cannot be assigned
        if room.status not in ["available", "clean", "inspected"]:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=f"Room {room.number} is not available for assignment (status: {room.status}). "
                       f"Only rooms with status 'available', 'clean', or 'inspected' can be assigned."
            )

        # Validate room type matches the reservation's room type
        if reservation.room_type_id and room.room_type_id and room.room_type_id != reservation.room_type_id:
            from fastapi import HTTPException
            booked_type = await session.get(RoomType, reservation.room_type_id)
            assigned_type = await session.get(RoomType, room.room_type_id)
            booked_name = booked_type.name if booked_type else "the booked type"
            assigned_name = assigned_type.name if assigned_type else "Unknown"
            raise HTTPException(
                status_code=400,
                detail=f"Room type mismatch: Guest booked {booked_name} but Room {room.number} is {assigned_name}. "
                       f"Please assign a room that matches the booked room type."
            )

        # Get room type name
        room_type_name = None
        if room.room_type_id:
            rt = await session.get(RoomType, room.room_type_id)
            if rt:
                room_type_name = rt.name

        # Check if room is available for the dates
        available = await check_availability(
            session,
            reservation.arrival_date,
            reservation.departure_date,
            room_type_name,
            reservation.adults
        )

        if room not in available:
            return None

        reservation.room_id = room_id
        # Set room occupancy_status to "reserved" (not occupied - guest hasn't checked in yet)
        room.occupancy_status = "reserved"
        room.updated_at = datetime.utcnow()
        await session.flush()
        return room

    elif auto_assign:
        # Auto-assign best available room
        available = await check_availability(
            session,
            reservation.arrival_date,
            reservation.departure_date,
            None,
            reservation.adults
        )
        
        if available:
            # Assign first available room (could add logic for best match)
            room = available[0]
            reservation.room_id = room.id
            # Set room occupancy_status to "reserved" (not occupied - guest hasn't checked in yet)
            room.occupancy_status = "reserved"
            room.updated_at = datetime.utcnow()
            await session.flush()
            return room

    return None


async def check_overbooking(
    session: AsyncSession,
    arrival_date: date,
    departure_date: date,
    room_type: Optional[str] = None,
    room_type_id: Optional[int] = None
) -> Tuple[bool, int]:
    """
    Check if booking would cause overbooking.
    Returns (is_overbooked, available_count)

    Uses the advanced OverbookingService when room_type_id is provided,
    falls back to simple calculation otherwise.
    """
    available = await check_availability(session, arrival_date, departure_date, room_type)
    available_count = len(available)

    # Try to use advanced overbooking service if room_type_id available
    if room_type_id:
        try:
            from app.services.overbooking_service import get_overbooking_service

            service = get_overbooking_service(session)
            result = await service.check_overbooking_for_booking(
                room_type_id, arrival_date, departure_date
            )

            # Create alert if needed
            if result.alert_severity and result.would_cause_overbooking:
                await service.create_overbooking_alert(
                    room_type_id=room_type_id,
                    alert_date=arrival_date,
                    severity=result.alert_severity
                )

            return not result.can_book, available_count
        except Exception as e:
            import logging
            logging.warning(f"Advanced overbooking check failed, using fallback: {e}")

    # Fallback: Simple calculation
    # Get room_type_id from name if provided
    resolved_room_type_id = room_type_id
    if room_type and not resolved_room_type_id:
        rt = (await session.execute(
            select(RoomType).where(RoomType.name == room_type)
        )).scalars().first()
        if rt:
            resolved_room_type_id = rt.id

    # Get total rooms of this type
    query = select(Room).where(Room.status != "out_of_order")
    if resolved_room_type_id:
        query = query.where(Room.room_type_id == resolved_room_type_id)

    total_rooms = len((await session.execute(query)).scalars().all())

    # Get overbooking limit from room type if available
    overbooking_limit_percent = 5.0  # Default 5%
    if resolved_room_type_id:
        rt = await session.get(RoomType, resolved_room_type_id)
        if rt and rt.overbooking_enabled:
            overbooking_limit_percent = rt.overbooking_limit_percent
        elif rt and not rt.overbooking_enabled:
            overbooking_limit_percent = 0.0  # No overbooking allowed

    # Get current bookings
    booking_query = select(Reservation).where(
        and_(
            Reservation.status.in_(["booked", "confirmed", "checked_in"]),
            Reservation.arrival_date < departure_date,
            Reservation.departure_date > arrival_date
        )
    )
    if resolved_room_type_id:
        booking_query = booking_query.where(Reservation.room_type_id == resolved_room_type_id)

    overlapping = (await session.execute(booking_query)).scalars().all()
    booked_count = len(overlapping)

    # Calculate overbooking threshold
    overbooking_threshold = int(total_rooms * (1 + overbooking_limit_percent / 100))
    is_overbooked = booked_count >= overbooking_threshold

    return is_overbooked, available_count


async def create_reservation(
    session: AsyncSession,
    payload: ReservationCreate,
    user_id: Optional[int] = None,
    allow_overbooking: bool = False,
    room_type_id: Optional[int] = None,
    base_price: Optional[float] = None,
    payment_method: Optional[str] = "card",
    payment_status: Optional[str] = None
) -> Reservation:
    """Create a reservation with overbooking check and room assignment.

    Also creates a corresponding Booking record for AGI/analytics queries.

    Args:
        session: Database session
        payload: Reservation creation payload
        user_id: ID of user creating the reservation
        allow_overbooking: Whether to allow overbooking
        room_type_id: Optional room type ID for the booking
        base_price: Optional base price per night (if None, calculated from rate plan)
        payment_method: Payment method ("card" or "pay_at_hotel")
        payment_status: Payment status (if None, determined by payment_method)
    """
    import logging

    # Check availability
    is_overbooked, available_count = await check_overbooking(
        session,
        payload.arrival_date,
        payload.departure_date,
        None  # room_type
    )

    if is_overbooked and not allow_overbooking:
        # Add to waitlist instead
        guest, _ = await create_guest(session, payload.guest.model_dump())
        waitlist_entry = Waitlist(
            guest_id=guest.id,
            arrival_date=payload.arrival_date,
            departure_date=payload.departure_date,
            adults=payload.adults,
            children=payload.children,
            rate_plan_id=payload.rate_plan_id,
            status="active"
        )
        session.add(waitlist_entry)
        await session.flush()
        raise ValueError(f"Fully booked. Added to waitlist. Available rooms: {available_count}")

    # Create guest
    guest, _ = await create_guest(session, payload.guest.model_dump())

    # Compute total
    total, currency = await compute_total(
        session,
        payload.rate_plan_id,
        payload.arrival_date,
        payload.departure_date,
        None,
        getattr(payload, 'promo_code', None)
    )

    # Generate codes
    confirmation_code = generate_confirmation_code()
    booking_number = generate_booking_number()

    # Calculate nights
    nights = (payload.departure_date - payload.arrival_date).days
    if nights < 1:
        nights = 1

    # Calculate price breakdown for Booking model
    # Check for None OR 0 to ensure we always try to get a valid price
    if base_price is None or base_price == 0:
        # Try to get base price from room type or rate plan
        if room_type_id:
            rt = await session.get(RoomType, room_type_id)
            if rt and rt.base_price and rt.base_price > 0:
                base_price = rt.base_price
        if not base_price or base_price == 0:
            rp = await session.get(RatePlan, payload.rate_plan_id)
            if rp and rp.base_price and rp.base_price > 0:
                base_price = rp.base_price
            else:
                base_price = 0.0

    # Calculate taxes using GST slab-based rates
    # - Room rate ≤ ₹7,500/night: 12% GST
    # - Room rate > ₹7,500/night: 18% GST
    from app.core.tax import calculate_booking_taxes
    tax_calc = calculate_booking_taxes(base_price, nights)
    calculated_base = tax_calc["calculated_base"]
    taxes = tax_calc["taxes"]
    service_fee = tax_calc["service_fee"]
    total_price = tax_calc["total_price"]

    # Create legacy Reservation (for backward compatibility)
    # Use total_price (with taxes and service fee) for consistency with Booking model
    reservation = Reservation(
        confirmation_code=confirmation_code,
        guest_id=guest.id,
        room_id=None,  # Explicitly None - assigned at pre-checkin/front desk
        room_type_id=room_type_id,
        rate_plan_id=payload.rate_plan_id,
        arrival_date=payload.arrival_date,
        departure_date=payload.departure_date,
        adults=payload.adults,
        children=payload.children,
        special_requests=payload.special_requests,
        group_code=payload.group_code,
        total_amount=total_price,
        currency=currency,
        promo_code=getattr(payload, 'promo_code', None),
        overbooked_flag=is_overbooked,
        created_by=user_id
    )
    session.add(reservation)
    await session.flush()

    # Also create a Booking record (for AGI/analytics queries)
    # The Booking model is the new standard - Reservation is legacy
    if room_type_id:
        try:
            # Determine payment status based on payment method
            effective_payment_status = payment_status
            if effective_payment_status is None:
                effective_payment_status = "paid" if payment_method == "card" else "pending"

            # Do not auto-set deposit at booking creation — deposit is recorded
            # when actual payment is collected (via folio payment endpoint).
            effective_deposit = 0.0

            booking = Booking(
                booking_number=booking_number,
                confirmation_code=confirmation_code,
                guest_id=guest.id,
                room_type_id=room_type_id,
                room_id=None,  # Assigned at check-in
                arrival_date=payload.arrival_date,
                departure_date=payload.departure_date,
                adults=payload.adults,
                children=payload.children,
                infants=0,
                nights=nights,
                status="pending",
                payment_status=effective_payment_status,
                payment_method=payment_method,
                booking_source="direct",
                base_price=calculated_base,
                taxes=taxes,
                service_fee=service_fee,
                total_price=total_price,
                deposit_amount=effective_deposit,
                balance_due=round(total_price - effective_deposit, 2),
                special_requests=payload.special_requests,
                vip_flag=False,
                discount_amount=0.0,
                modification_count=0,
                created_by=user_id
            )
            session.add(booking)
            await session.flush()
            logging.info(f"Created Booking record: {booking_number} with confirmation: {confirmation_code}")
        except Exception as e:
            logging.error(f"Failed to create Booking record: {e}")
            # Don't fail the entire operation if Booking creation fails
            # The legacy Reservation is still created
    else:
        logging.warning(f"No room_type_id provided, skipping Booking record creation")

    # Create history entry
    history = ReservationHistory(
        reservation_id=reservation.id,
        action="created",
        changed_by=user_id,
        notes=f"Reservation created. Overbooked: {is_overbooked}"
    )
    session.add(history)
    await session.flush()

    return reservation


async def update_reservation(
    session: AsyncSession,
    reservation_id: int,
    updates: dict,
    user_id: Optional[int] = None
) -> Optional[Reservation]:
    """Update a reservation and track changes in history"""
    reservation = await session.get(Reservation, reservation_id)
    if not reservation:
        return None
    
    # Track changes
    for field, new_value in updates.items():
        if hasattr(reservation, field):
            old_value = getattr(reservation, field)
            if old_value != new_value:
                history = ReservationHistory(
                    reservation_id=reservation_id,
                    action="modified",
                    changed_by=user_id,
                    old_value=str(old_value),
                    new_value=str(new_value),
                    notes=f"Field {field} changed"
                )
                session.add(history)
                setattr(reservation, field, new_value)
    
    reservation.updated_at = datetime.utcnow()
    await session.flush()
    return reservation


async def cancel_reservation(
    session: AsyncSession,
    reservation_id: int,
    reason: Optional[str] = None,
    user_id: Optional[int] = None
) -> Optional[Reservation]:
    """Cancel a reservation"""
    reservation = await session.get(Reservation, reservation_id)
    if not reservation:
        return None
    
    if reservation.status in ["checked_out", "cancelled"]:
        return None  # Already cancelled or checked out
    
    reservation.status = "cancelled"
    reservation.cancelled_at = datetime.utcnow()
    reservation.cancelled_by = user_id
    reservation.cancellation_reason = reason
    reservation.updated_at = datetime.utcnow()
    
    # Create history entry
    history = ReservationHistory(
        reservation_id=reservation_id,
        action="cancelled",
        changed_by=user_id,
        notes=f"Reservation cancelled. Reason: {reason}"
    )
    session.add(history)
    
    # Check waitlist for potential conversion
    await check_waitlist_for_availability(session, reservation.arrival_date, reservation.departure_date)
    
    await session.flush()
    return reservation


async def check_waitlist_for_availability(
    session: AsyncSession,
    arrival_date: date,
    departure_date: date
):
    """Check if any waitlist entries can be converted to reservations"""
    waitlist_entries = (await session.execute(
        select(Waitlist).where(
            and_(
                Waitlist.status == "active",
                Waitlist.arrival_date == arrival_date,
                Waitlist.departure_date == departure_date
            )
        ).order_by(Waitlist.priority.desc(), Waitlist.created_at.asc())
    )).scalars().all()
    
    for entry in waitlist_entries:
        available = await check_availability(
            session,
            entry.arrival_date,
            entry.departure_date,
            entry.room_type_preference,
            entry.adults
        )
        
        if available:
            # Convert waitlist to reservation
            from app.schemas.reservations import GuestCreate, ReservationCreate
            guest = await session.get(Guest, entry.guest_id)
            if guest:
                # Get default rate plan if none specified
                rate_plan_id = entry.rate_plan_id
                if not rate_plan_id:
                    rate_plan_id = await get_default_rate_plan_id(session)

                reservation = await create_reservation(
                    session,
                    ReservationCreate(
                        guest=GuestCreate(
                            first_name=guest.first_name,
                            last_name=guest.last_name,
                            email=guest.email,
                            phone=guest.phone
                        ),
                        rate_plan_id=rate_plan_id,
                        arrival_date=entry.arrival_date,
                        departure_date=entry.departure_date,
                        adults=entry.adults,
                        children=entry.children
                    ),
                    allow_overbooking=False
                )
                
                entry.status = "converted"
                entry.converted_at = datetime.utcnow()
                entry.converted_to_reservation_id = reservation.id
                await session.flush()
                break  # Only convert one at a time


