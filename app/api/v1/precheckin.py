from typing import Optional, List
from datetime import datetime, date, timedelta
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File, Query
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel
import json

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user, get_current_user_optional
from app.models.precheckin import PreCheckIn
from app.models.reservations import Reservation, Booking, Guest
from app.models.inventory import Room, RoomType
from app.models.user import User

router = APIRouter()


# ============== BOOKING VERIFICATION ==============

class VerifyBookingRequest(BaseModel):
    booking_number: str
    guest_name: str


class VerifyBookingResponse(BaseModel):
    valid: bool
    reservation_id: Optional[int] = None
    guest_name: Optional[str] = None
    room_type: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    nights: Optional[int] = None
    status: Optional[str] = None
    error: Optional[str] = None
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None


class PreCheckInCreate(BaseModel):
    reservation_id: int
    email: str
    phone: str
    address: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    floor_preference: Optional[str] = None
    view_preference: Optional[str] = None
    bed_type_preference: Optional[str] = None
    quietness_preference: Optional[str] = None
    arrival_time: Optional[str] = None
    flight_number: Optional[str] = None
    purpose: Optional[str] = None
    transportation_needed: bool = False
    pillow_type: Optional[str] = None
    temperature: Optional[int] = None
    minibar_preferences: Optional[str] = None
    dietary_restrictions: Optional[str] = None
    special_requests: Optional[str] = None
    early_check_in: bool = False
    late_check_out: bool = False


class PreCheckInUpdate(BaseModel):
    # Room selection fields
    selected_room_id: Optional[int] = None
    ai_score: Optional[float] = None
    ai_reasoning: Optional[str] = None
    # ID verification fields
    id_front_url: Optional[str] = None
    id_back_url: Optional[str] = None
    id_type: Optional[str] = None
    id_verified: Optional[bool] = None
    # Digital key fields
    digital_key_id: Optional[str] = None
    digital_key_activated: Optional[bool] = None
    qr_code: Optional[str] = None
    status: Optional[str] = None
    # Room preference fields - needed for AI recommendations sync
    floor_preference: Optional[str] = None
    view_preference: Optional[str] = None
    bed_type_preference: Optional[str] = None
    quietness_preference: Optional[str] = None


class PreCheckInRead(BaseModel):
    id: int
    reservation_id: int
    guest_id: int
    email: str
    phone: str
    address: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    floor_preference: Optional[str] = None
    view_preference: Optional[str] = None
    bed_type_preference: Optional[str] = None
    quietness_preference: Optional[str] = None
    selected_room_id: Optional[int] = None
    ai_score: Optional[float] = None
    ai_reasoning: Optional[str] = None
    arrival_time: Optional[str] = None
    flight_number: Optional[str] = None
    purpose: Optional[str] = None
    transportation_needed: bool
    id_front_url: Optional[str] = None
    id_back_url: Optional[str] = None
    id_type: Optional[str] = None
    id_verified: bool
    pillow_type: Optional[str] = None
    temperature: Optional[int] = None
    minibar_preferences: Optional[str] = None
    dietary_restrictions: Optional[str] = None
    special_requests: Optional[str] = None
    early_check_in: bool
    late_check_out: bool
    digital_key_id: Optional[str] = None
    digital_key_activated: bool
    qr_code: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


@router.post("/verify-booking", response_model=VerifyBookingResponse)
async def verify_booking(
    payload: VerifyBookingRequest,
    session: AsyncSession = Depends(get_tenant_session)
):
    """Verify booking number and guest name before proceeding with pre-checkin"""
    from sqlalchemy import func

    booking_number = payload.booking_number.strip()
    guest_name = payload.guest_name.strip().lower()
    today = date.today()

    # Find reservation by confirmation code (case-insensitive)
    reservation = (await session.exec(
        select(Reservation).where(
            func.upper(Reservation.confirmation_code) == booking_number.upper()
        )
    )).first()

    if not reservation:
        # Also try the new Booking model if Reservation not found
        try:
            from app.models.reservations import Booking
            booking = (await session.exec(
                select(Booking).where(
                    func.upper(Booking.confirmation_code) == booking_number.upper()
                )
            )).first()

            if not booking:
                # Try booking_number field as well
                booking = (await session.exec(
                    select(Booking).where(
                        func.upper(Booking.booking_number) == booking_number.upper()
                    )
                )).first()

            if booking:
                # Convert Booking to Reservation-like object for rest of function
                # Get guest info
                guest = await session.get(Guest, booking.guest_id)
                if not guest:
                    return VerifyBookingResponse(
                        valid=False,
                        error="Guest information not found for this booking."
                    )

                # Verify guest name
                full_name = f"{guest.first_name} {guest.last_name}".lower()
                first_name = guest.first_name.lower() if guest.first_name else ""
                last_name = guest.last_name.lower() if guest.last_name else ""

                name_matches = (
                    guest_name == full_name or
                    guest_name == first_name or
                    guest_name == last_name or
                    guest_name in full_name or
                    full_name in guest_name or
                    (first_name and first_name in guest_name) or
                    (last_name and last_name in guest_name)
                )

                if not name_matches:
                    return VerifyBookingResponse(
                        valid=False,
                        error="Guest name does not match our records."
                    )

                # Check if booking is for a past date (check-out already passed)
                if booking.departure_date < today:
                    return VerifyBookingResponse(
                        valid=False,
                        error="This booking has already ended. Pre-check-in is not available for past bookings."
                    )

                # Check if already checked in or checked out
                if booking.status in ["checked_in", "checked_out"]:
                    return VerifyBookingResponse(
                        valid=False,
                        error=f"This booking is already {booking.status.replace('_', ' ')}. Pre-check-in is not required."
                    )

                # Check if booking is cancelled
                if booking.status in ["cancelled", "no_show"]:
                    return VerifyBookingResponse(
                        valid=False,
                        error=f"This booking has been {booking.status.replace('_', ' ')}. Pre-check-in is not available."
                    )

                # Check if pre-checkin already completed
                existing_precheckin = (await session.exec(
                    select(PreCheckIn).where(
                        and_(
                            PreCheckIn.booking_id == booking.id,
                            PreCheckIn.status == "completed"
                        )
                    )
                )).first()

                if existing_precheckin:
                    return VerifyBookingResponse(
                        valid=False,
                        error="Pre-check-in has already been completed for this booking. You should have received your digital key via email."
                    )

                # Check if pre-checkin is too early (more than 7 days before arrival)
                days_until_arrival = (booking.arrival_date - today).days
                if days_until_arrival > 7:
                    return VerifyBookingResponse(
                        valid=False,
                        error=f"Pre-check-in opens 7 days before arrival. Please try again on {(booking.arrival_date - timedelta(days=7)).strftime('%B %d, %Y')}."
                    )

                # Get room type name
                room_type_name = "Standard Room"
                if booking.room_type_id:
                    room_type = await session.get(RoomType, booking.room_type_id)
                    if room_type:
                        room_type_name = room_type.name

                return VerifyBookingResponse(
                    valid=True,
                    reservation_id=booking.id,
                    guest_name=f"{guest.first_name} {guest.last_name}",
                    room_type=room_type_name,
                    check_in=booking.arrival_date.isoformat(),
                    check_out=booking.departure_date.isoformat(),
                    nights=booking.nights,
                    status=booking.status,
                    guest_email=guest.email,
                    guest_phone=guest.phone,
                )
        except Exception as e:
            import logging
            logging.error(f"Error checking Booking model: {e}")

    if not reservation:
        return VerifyBookingResponse(
            valid=False,
            error="Booking not found. Please check your booking number."
        )

    # Get guest info
    guest = await session.get(Guest, reservation.guest_id)
    if not guest:
        return VerifyBookingResponse(
            valid=False,
            error="Guest information not found for this booking."
        )

    # Verify guest name (flexible matching)
    full_name = f"{guest.first_name} {guest.last_name}".lower()
    first_name = guest.first_name.lower() if guest.first_name else ""
    last_name = guest.last_name.lower() if guest.last_name else ""

    # Check if provided name matches first name, last name, or full name
    name_matches = (
        guest_name == full_name or
        guest_name == first_name or
        guest_name == last_name or
        guest_name in full_name or
        full_name in guest_name or
        (first_name and first_name in guest_name) or
        (last_name and last_name in guest_name)
    )

    if not name_matches:
        return VerifyBookingResponse(
            valid=False,
            error="Guest name does not match our records. Please enter your name as it appears on your booking."
        )

    # Check if booking is for a past date (check-out already passed)
    if reservation.departure_date < today:
        return VerifyBookingResponse(
            valid=False,
            error="This booking has already ended. Pre-check-in is not available for past bookings."
        )

    # Check booking status
    if reservation.status == "cancelled":
        return VerifyBookingResponse(
            valid=False,
            error="This booking has been cancelled."
        )

    if reservation.status == "checked_in":
        return VerifyBookingResponse(
            valid=False,
            error="You are already checked in. Pre-check-in is not required."
        )

    if reservation.status in ["checked_out", "completed"]:
        return VerifyBookingResponse(
            valid=False,
            error="This booking has already been completed."
        )

    # Check if pre-checkin already completed
    existing_precheckin = (await session.exec(
        select(PreCheckIn).where(
            and_(
                PreCheckIn.reservation_id == reservation.id,
                PreCheckIn.status == "completed"
            )
        )
    )).first()

    if existing_precheckin:
        return VerifyBookingResponse(
            valid=False,
            error="Pre-check-in has already been completed for this booking. You should have received your digital key via email."
        )

    # Check if check-in date is valid (allow pre-checkin up to 7 days before)
    days_until_checkin = (reservation.arrival_date - today).days

    if days_until_checkin > 7:
        return VerifyBookingResponse(
            valid=False,
            error=f"Pre-checkin opens 7 days before arrival. Please try again on {(reservation.arrival_date - timedelta(days=7)).strftime('%B %d, %Y')}."
        )

    # Get room type name
    room_type_name = "Standard Room"
    if reservation.room_type_id:
        room_type = await session.get(RoomType, reservation.room_type_id)
        if room_type:
            room_type_name = room_type.name
    elif reservation.room_id:
        room = await session.get(Room, reservation.room_id)
        if room and room.room_type_id:
            room_type = await session.get(RoomType, room.room_type_id)
            if room_type:
                room_type_name = room_type.name

    nights = (reservation.departure_date - reservation.arrival_date).days

    return VerifyBookingResponse(
        valid=True,
        reservation_id=reservation.id,
        guest_name=f"{guest.first_name} {guest.last_name}",
        room_type=room_type_name,
        check_in=reservation.arrival_date.isoformat(),
        check_out=reservation.departure_date.isoformat(),
        nights=nights,
        status=reservation.status,
        guest_email=guest.email,
        guest_phone=guest.phone,
    )


@router.get("", response_model=List[PreCheckInRead])
async def list_precheckins(
    reservation_id: Optional[int] = None,
    status: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """List pre-checkins"""
    query = select(PreCheckIn)

    if reservation_id:
        query = query.where(PreCheckIn.reservation_id == reservation_id)
    if status:
        query = query.where(PreCheckIn.status == status)

    result = await session.exec(query.order_by(PreCheckIn.created_at.desc()))
    precheckins = result.all()

    return [PreCheckInRead.model_validate(p.__dict__) for p in precheckins]


@router.post("", response_model=PreCheckInRead, status_code=201)
async def create_precheckin(
    payload: PreCheckInCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """Create or update pre-checkin - allows guest access without authentication"""
    from app.models.reservations import Booking

    # Check if reservation exists (try both Reservation and Booking tables)
    reservation = await session.get(Reservation, payload.reservation_id)
    booking = None
    guest_id = None

    if reservation:
        guest_id = reservation.guest_id
    else:
        # Try the newer Booking model
        booking = await session.get(Booking, payload.reservation_id)
        if booking:
            guest_id = booking.guest_id
        else:
            raise HTTPException(status_code=404, detail="Reservation not found")

    # Check if pre-checkin already exists (check both reservation_id and booking_id)
    existing = (await session.exec(
        select(PreCheckIn).where(PreCheckIn.reservation_id == payload.reservation_id)
    )).first()

    if not existing and booking:
        # Also check by booking_id
        existing = (await session.exec(
            select(PreCheckIn).where(PreCheckIn.booking_id == payload.reservation_id)
        )).first()

    if existing:
        # Update existing
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(existing, key, value)
        existing.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(existing)
        return PreCheckInRead.model_validate(existing.__dict__)

    # Create new
    guest = await session.get(Guest, guest_id)
    if not guest:
        raise HTTPException(status_code=404, detail="Guest not found")

    # Get payload data excluding reservation_id (we'll set it explicitly)
    payload_data = payload.model_dump(exclude={'reservation_id'})

    precheckin = PreCheckIn(
        reservation_id=payload.reservation_id,
        booking_id=booking.id if booking else None,
        guest_id=guest.id,
        **payload_data
    )
    session.add(precheckin)
    await session.commit()
    await session.refresh(precheckin)

    return PreCheckInRead.model_validate(precheckin.__dict__)


@router.get("/{precheckin_id}", response_model=PreCheckInRead)
async def get_precheckin(
    precheckin_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """Get pre-checkin by ID - allows guest access"""
    precheckin = await session.get(PreCheckIn, precheckin_id)
    if not precheckin:
        raise HTTPException(status_code=404, detail="Pre-checkin not found")
    
    return PreCheckInRead.model_validate(precheckin.__dict__)


@router.patch("/{precheckin_id}", response_model=PreCheckInRead)
async def update_precheckin(
    precheckin_id: int,
    payload: PreCheckInUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """Update pre-checkin - allows guest access"""
    precheckin = await session.get(PreCheckIn, precheckin_id)
    if not precheckin:
        raise HTTPException(status_code=404, detail="Pre-checkin not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(precheckin, key, value)

    if payload.status == "completed":
        precheckin.completed_at = datetime.utcnow()

        # CRITICAL: Sync selected_room_id to Reservation.room_id when precheckin is completed
        if precheckin.selected_room_id and precheckin.reservation_id:
            reservation = await session.get(Reservation, precheckin.reservation_id)
            if reservation:
                # Verify the room exists and is available
                room = await session.get(Room, precheckin.selected_room_id)
                if room and room.status in ["available", "clean", "inspected", "dirty"]:
                    reservation.room_id = precheckin.selected_room_id
                    reservation.updated_at = datetime.utcnow()

                    # Generate digital key if not already generated
                    if not precheckin.digital_key_id:
                        import secrets
                        precheckin.digital_key_id = f"DK-{secrets.token_urlsafe(6).upper()}"
                        precheckin.digital_key_activated = True
                        precheckin.qr_code = f"GLIMMORA-KEY-{precheckin.digital_key_id}-ROOM-{room.number}"

    precheckin.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(precheckin)

    return PreCheckInRead.model_validate(precheckin.__dict__)


class CompletePreCheckinRequest(BaseModel):
    selected_room_id: Optional[int] = None
    room_type_slug: Optional[str] = None  # Alternative: auto-assign room from this type
    ai_score: Optional[float] = None
    ai_reasoning: Optional[List[str]] = None


@router.post("/{precheckin_id}/complete")
async def complete_precheckin(
    precheckin_id: int,
    payload: CompletePreCheckinRequest,
    background_tasks: BackgroundTasks,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """Complete pre-checkin: assign room, generate digital key - allows guest access"""
    import secrets
    import logging
    from app.services.room_assignment_service import validate_and_assign_room, check_room_conflict
    from app.models.reservations import Booking

    precheckin = await session.get(PreCheckIn, precheckin_id)
    if not precheckin:
        raise HTTPException(status_code=404, detail="Pre-checkin not found")

    # Verify ID has been verified before completing
    if not precheckin.id_verified:
        raise HTTPException(status_code=400, detail="ID verification required before completing pre-checkin")

    # Get the reservation - check both Reservation and Booking tables
    reservation = await session.get(Reservation, precheckin.reservation_id)
    booking = None

    if not reservation:
        # Try the newer Booking model
        booking = await session.get(Booking, precheckin.reservation_id)
        if not booking:
            raise HTTPException(status_code=404, detail="Reservation not found")

    # Extract common fields from reservation or booking
    guest_id = reservation.guest_id if reservation else booking.guest_id
    arrival_date = reservation.arrival_date if reservation else booking.arrival_date
    departure_date = reservation.departure_date if reservation else booking.departure_date
    reservation_id = reservation.id if reservation else precheckin.reservation_id
    booking_id = precheckin.booking_id or (booking.id if booking else None)

    # Resolve room: either from selected_room_id or auto-assign from room_type_slug
    room = None
    if payload.selected_room_id:
        room = await session.get(Room, payload.selected_room_id)
        if not room:
            raise HTTPException(status_code=404, detail="Selected room not found")
    elif payload.room_type_slug:
        # Find room type by slug
        room_type_name = payload.room_type_slug.replace('-', ' ').title()
        room_type_obj = (await session.exec(
            select(RoomType).where(RoomType.name == room_type_name)
        )).first()
        if not room_type_obj:
            room_type_obj = (await session.exec(
                select(RoomType).where(RoomType.slug == payload.room_type_slug)
            )).first()
        if not room_type_obj:
            raise HTTPException(status_code=404, detail=f"Room type '{payload.room_type_slug}' not found")

        # Find an available room of this type
        all_rooms = (await session.exec(
            select(Room).where(
                Room.room_type_id == room_type_obj.id,
                Room.status.notin_(["out_of_order", "out_of_service", "maintenance"])
            )
        )).all()

        # Filter out rooms with conflicting reservations
        for candidate in all_rooms:
            conflicts = (await session.exec(
                select(Reservation).where(
                    and_(
                        Reservation.room_id == candidate.id,
                        Reservation.status.in_(["booked", "confirmed", "checked_in"]),
                        Reservation.arrival_date < departure_date,
                        Reservation.departure_date > arrival_date,
                        Reservation.id != reservation_id if reservation else True
                    )
                )
            )).all()
            # Also check Booking table conflicts
            booking_conflicts = (await session.exec(
                select(Booking).where(
                    and_(
                        Booking.room_id == candidate.id,
                        Booking.status.in_(["confirmed", "checked_in"]),
                        Booking.arrival_date < departure_date,
                        Booking.departure_date > arrival_date,
                        Booking.id != booking_id if booking_id else True
                    )
                )
            )).all()
            if not conflicts and not booking_conflicts:
                room = candidate
                break

        if not room:
            raise HTTPException(status_code=400, detail=f"No available rooms for type '{room_type_obj.name}' on selected dates")
    else:
        raise HTTPException(status_code=400, detail="Either selected_room_id or room_type_slug is required")

    # Check room is not out of service
    if room.status in ["out_of_order", "out_of_service", "maintenance"]:
        raise HTTPException(status_code=400, detail="Selected room is not available")

    # Check for conflicting reservations (for directly selected rooms)
    if payload.selected_room_id:
        conflicts = (await session.exec(
            select(Reservation).where(
                and_(
                    Reservation.room_id == room.id,
                    Reservation.status.in_(["booked", "confirmed", "checked_in"]),
                    Reservation.arrival_date < departure_date,
                    Reservation.departure_date > arrival_date,
                    Reservation.id != reservation_id if reservation else True
                )
            )
        )).all()

        if conflicts:
            raise HTTPException(status_code=400, detail="Selected room has a conflicting reservation")

    # Update room assignment (use room.id which handles both direct selection and auto-assign)
    if reservation:
        reservation.room_id = room.id
    if booking:
        booking.room_id = room.id

    # Generate digital key with QR code using DigitalKeyService
    from app.services.digital_key_service import get_digital_key_service

    digital_key_service = get_digital_key_service(session)

    # Get guest name for the digital key
    guest = await session.get(Guest, guest_id)
    guest_name = f"{guest.first_name} {guest.last_name}" if guest else "Guest"
    guest_email = precheckin.email or (guest.email if guest else None)

    # Generate the digital key
    digital_key = await digital_key_service.generate_digital_key(
        guest_id=guest_id,
        room_id=room.id,
        room_number=room.number,
        check_in_date=arrival_date,
        check_out_date=departure_date,
        guest_name=guest_name,
        guest_email=guest_email,
        booking_id=booking_id,
        reservation_id=reservation_id,
        precheckin_id=precheckin.id
    )

    digital_key_id = digital_key.key_code
    qr_code = digital_key.qr_data
    qr_image_base64 = digital_key.qr_image_base64

    # Update precheckin
    precheckin.selected_room_id = payload.selected_room_id
    precheckin.ai_score = payload.ai_score
    precheckin.ai_reasoning = json.dumps(payload.ai_reasoning) if payload.ai_reasoning else None
    precheckin.digital_key_id = digital_key_id
    precheckin.digital_key_activated = True
    precheckin.qr_code = qr_code
    precheckin.status = "completed"
    precheckin.completed_at = datetime.utcnow()
    precheckin.updated_at = datetime.utcnow()
    if booking_id:
        precheckin.booking_id = booking_id

    # Update reservation/booking status to checked-in
    if reservation:
        reservation.status = "checked_in"
        reservation.updated_at = datetime.utcnow()

    if booking:
        booking.status = "checked_in"
        booking.check_in_date = datetime.utcnow()
        booking.updated_at = datetime.utcnow()
        logging.info(f"Updated Booking {booking.id} status to checked_in")
    elif reservation:
        # Try to find booking by confirmation code from reservation
        booking_result = await session.exec(
            select(Booking).where(Booking.confirmation_code == reservation.confirmation_code)
        )
        linked_booking = booking_result.first()
        if linked_booking:
            linked_booking.room_id = room.id
            linked_booking.status = "checked_in"
            linked_booking.check_in_date = datetime.utcnow()
            linked_booking.updated_at = datetime.utcnow()
            # Also link the booking_id to precheckin
            precheckin.booking_id = linked_booking.id
            logging.info(f"Found and updated Booking {linked_booking.id} by confirmation code, status to checked_in")

    # Also sync preferences to Guest record
    guest = await session.get(Guest, guest_id)
    if guest and precheckin:
        # Sync preferences from precheckin to guest
        preferences = {}
        if precheckin.floor_preference:
            preferences['floor'] = precheckin.floor_preference
        if precheckin.view_preference:
            preferences['view'] = precheckin.view_preference
        if precheckin.bed_type_preference:
            preferences['bedType'] = precheckin.bed_type_preference
        if precheckin.quietness_preference:
            preferences['quietness'] = precheckin.quietness_preference
        if precheckin.pillow_type:
            try:
                preferences['pillowType'] = json.loads(precheckin.pillow_type)
            except:
                preferences['pillowType'] = precheckin.pillow_type
        if precheckin.temperature:
            preferences['temperature'] = precheckin.temperature
        if precheckin.minibar_preferences:
            try:
                preferences['minibar'] = json.loads(precheckin.minibar_preferences)
            except:
                preferences['minibar'] = precheckin.minibar_preferences
        if precheckin.dietary_restrictions:
            try:
                preferences['dietary'] = json.loads(precheckin.dietary_restrictions)
            except:
                preferences['dietary'] = precheckin.dietary_restrictions

        if preferences:
            # Merge with existing preferences
            existing_prefs = guest.preferences if isinstance(guest.preferences, dict) else {}
            if isinstance(guest.preferences, str):
                try:
                    existing_prefs = json.loads(guest.preferences)
                except:
                    existing_prefs = {}
            existing_prefs.update(preferences)
            guest.preferences = existing_prefs
            guest.updated_at = datetime.utcnow()
            logging.info(f"Synced preferences to Guest {guest.id}: {preferences}")

    await session.commit()
    await session.refresh(precheckin)
    if reservation:
        await session.refresh(reservation)
    if booking:
        await session.refresh(booking)

    # Get guest name for task notes
    guest = await session.get(Guest, guest_id)
    guest_name = f"{guest.first_name} {guest.last_name}" if guest else "Guest"

    # Create housekeeping task for room preparation based on guest preferences
    try:
        from app.models.operations import HousekeepingTask, MaintenanceRequest
        import uuid

        # Build preparation checklist from precheckin preferences
        preparation_items = []
        notes_items = []

        # Pillow preferences
        if precheckin.pillow_type:
            try:
                pillows = json.loads(precheckin.pillow_type) if isinstance(precheckin.pillow_type, str) else precheckin.pillow_type
                if isinstance(pillows, list) and pillows:
                    pillow_str = ", ".join(pillows)
                    preparation_items.append({"item": f"Set up pillows: {pillow_str}", "completed": False})
                    notes_items.append(f"Pillow preference: {pillow_str}")
            except:
                pass

        # Temperature preference
        if precheckin.temperature:
            preparation_items.append({"item": f"Set room temperature to {precheckin.temperature}°C", "completed": False})
            notes_items.append(f"Temperature: {precheckin.temperature}°C")

            # Create HVAC maintenance task to set temperature
            try:
                work_order_id = f"WO-{uuid.uuid4().hex[:8].upper()}"
                hvac_task = MaintenanceRequest(
                    work_order_id=work_order_id,
                    room_id=room.id,
                    category="hvac",
                    priority="high",
                    issue=f"Pre-arrival: Set room temperature to {precheckin.temperature}°C",
                    description=f"Guest arriving today. Please set thermostat to {precheckin.temperature}°C before arrival.\nGuest: {guest_name}\nArrival: {precheckin.arrival_time or 'Standard check-in time'}",
                    status="open",
                )
                session.add(hvac_task)
                logging.info(f"Created HVAC task for room {room.number}: set to {precheckin.temperature}°C")
            except Exception as e:
                logging.error(f"Failed to create HVAC task: {e}")

        # Minibar preferences
        if precheckin.minibar_preferences:
            try:
                minibar = json.loads(precheckin.minibar_preferences) if isinstance(precheckin.minibar_preferences, str) else precheckin.minibar_preferences
                if isinstance(minibar, list) and minibar:
                    minibar_str = ", ".join(minibar)
                    preparation_items.append({"item": f"Stock minibar with: {minibar_str}", "completed": False})
                    notes_items.append(f"Minibar: {minibar_str}")
            except:
                pass

        # Dietary restrictions (for welcome amenities)
        if precheckin.dietary_restrictions:
            try:
                dietary = json.loads(precheckin.dietary_restrictions) if isinstance(precheckin.dietary_restrictions, str) else precheckin.dietary_restrictions
                if isinstance(dietary, list) and dietary:
                    dietary_str = ", ".join(dietary)
                    preparation_items.append({"item": f"Ensure welcome amenities comply with: {dietary_str}", "completed": False})
                    notes_items.append(f"Dietary: {dietary_str}")
            except:
                pass

        # Bed type preference
        if precheckin.bed_type_preference and precheckin.bed_type_preference != "any":
            preparation_items.append({"item": f"Verify bed configuration: {precheckin.bed_type_preference}", "completed": False})

        # Special requests
        if precheckin.special_requests:
            preparation_items.append({"item": f"Special request: {precheckin.special_requests}", "completed": False})
            notes_items.append(f"Special: {precheckin.special_requests}")

        # Early check-in
        if precheckin.early_check_in:
            preparation_items.append({"item": "PRIORITY: Early check-in requested - prepare room early", "completed": False})
            notes_items.append("Early check-in requested")

        # VIP check from guest profile OR booking vip_flag
        is_vip = (guest and guest.vip_status)
        if precheckin.booking_id:
            booking_for_vip = await session.get(Booking, precheckin.booking_id)
            if booking_for_vip and booking_for_vip.vip_flag:
                is_vip = True

        if is_vip:
            preparation_items.append({"item": "VIP guest - ensure premium amenities and inspection", "completed": False})
            notes_items.append("VIP GUEST")

        # Create housekeeping task if there are any preparation items
        if preparation_items:
            housekeeping_task = HousekeepingTask(
                room_id=room.id,
                task_type="pre_arrival",
                priority="high" if precheckin.early_check_in or is_vip else "normal",
                status="pending",
                scheduled_for=datetime.utcnow(),
                estimated_duration=30,  # 30 minutes for preparation
                checklist=json.dumps(preparation_items),
                notes=f"Pre-arrival preparation for {guest_name}.\n" + "\n".join(notes_items),
            )
            session.add(housekeeping_task)
            logging.info(f"Created housekeeping pre-arrival task for room {room.number} with {len(preparation_items)} items")

        await session.commit()

    except Exception as e:
        logging.error(f"Failed to create housekeeping/maintenance tasks: {e}")
        await session.rollback()
        # Don't fail the main request

    # Get room type for response
    room_type_name = "Standard Room"
    if room.room_type_id:
        room_type = await session.get(RoomType, room.room_type_id)
        if room_type:
            room_type_name = room_type.name

    # Get confirmation code for email
    confirmation_code = None
    if reservation:
        confirmation_code = reservation.confirmation_code or f"RES-{reservation.id}"
    elif booking:
        confirmation_code = booking.confirmation_code or f"BK-{booking.id}"

    # Send confirmation email with digital key and QR code image (non-blocking)
    if guest_email:
        from app.services.background_email import send_precheckin_confirmation_email_bg
        background_tasks.add_task(
            send_precheckin_confirmation_email_bg,
            to_email=guest_email,
            guest_name=guest_name,
            booking_number=confirmation_code,
            room_number=room.number,
            room_type=room_type_name,
            check_in_date=arrival_date.strftime("%B %d, %Y"),
            check_out_date=departure_date.strftime("%B %d, %Y"),
            digital_key_id=digital_key_id,
            qr_code=qr_code,
            qr_image_base64=qr_image_base64,
        )
        # Mark digital key email as sent
        try:
            await digital_key_service.mark_email_sent(digital_key_id)
        except Exception as e:
            logging.error(f"Failed to mark digital key email as sent: {e}")

    return {
        "success": True,
        "message": "Pre-check-in completed successfully",
        "precheckin_id": precheckin.id,
        "reservation_id": reservation_id,
        "room": {
            "id": room.id,
            "number": room.number,
            "type": room_type_name,
            "floor": room.floor,
            "view": room.view_type,
        },
        "digital_key": {
            "id": digital_key.id,
            "key_code": digital_key_id,
            "activated": True,
            "qr_data": qr_code,
            "qr_image_base64": qr_image_base64,
            "valid_from": digital_key.valid_from.isoformat(),
            "valid_until": digital_key.valid_until.isoformat(),
        },
        "check_in_date": arrival_date.isoformat(),
        "check_out_date": departure_date.isoformat(),
        "email_sent": bool(guest_email),
    }


@router.get("/reservation/{reservation_id}", response_model=Optional[PreCheckInRead])
async def get_precheckin_by_reservation(
    reservation_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Get pre-checkin by reservation ID - allows guest access without authentication"""
    precheckin = (await session.exec(
        select(PreCheckIn).where(PreCheckIn.reservation_id == reservation_id)
    )).first()
    
    if not precheckin:
        return None
    
    return PreCheckInRead.model_validate(precheckin.__dict__)


@router.post("/{precheckin_id}/recommend-rooms")
async def recommend_rooms(
    precheckin_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """AI room recommendation based on preferences - allows guest access"""
    from app.models.reservations import Booking

    precheckin = await session.get(PreCheckIn, precheckin_id)
    if not precheckin:
        raise HTTPException(status_code=404, detail="Pre-checkin not found")

    if not precheckin.reservation_id:
        raise HTTPException(
            status_code=400,
            detail="Pre-checkin is not linked to a reservation"
        )

    # Check both Reservation and Booking tables
    reservation = await session.get(Reservation, precheckin.reservation_id)
    booking = None

    if not reservation:
        # Try the newer Booking model
        booking = await session.get(Booking, precheckin.reservation_id)
        if not booking:
            raise HTTPException(status_code=404, detail="Reservation not found")

    # Use either reservation or booking data
    arrival_date = reservation.arrival_date if reservation else booking.arrival_date
    departure_date = reservation.departure_date if reservation else booking.departure_date
    room_type_id = reservation.room_type_id if reservation else booking.room_type_id
    adults_count = (reservation.adults if reservation else booking.adults) or 1

    # Validate required reservation data
    if not arrival_date or not departure_date:
        raise HTTPException(
            status_code=400,
            detail="Reservation is missing arrival or departure dates"
        )

    # Get room type from reservation/booking
    from app.services.reservation_service import check_availability
    import logging

    booked_room_type_name = None
    booked_room_type = None
    if room_type_id:
        booked_room_type = await session.get(RoomType, room_type_id)
        if booked_room_type:
            booked_room_type_name = booked_room_type.name

    # Get available rooms for the reservation dates (filtered by booked room type)
    adults = adults_count  # Default to 1 if not specified
    try:
        available_rooms = await check_availability(
            session=session,
            arrival_date=arrival_date,
            departure_date=departure_date,
            room_type=booked_room_type_name,
            adults=adults
        )
    except Exception as e:
        logging.error(f"Error in check_availability: {e}")
        available_rooms = []

    if not available_rooms:
        # If no rooms available for exact type, get all rooms that aren't blocked/out of service
        # Use broader status filter - only exclude rooms that can't be used
        try:
            all_rooms_result = await session.execute(
                select(Room).where(
                    Room.status.notin_(["out_of_order", "out_of_service", "maintenance"])
                )
            )
            all_rooms = all_rooms_result.scalars().all()
        except Exception as e:
            import logging
            logging.error(f"Error fetching rooms: {e}")
            all_rooms = []

        # Filter out rooms with conflicting reservations AND bookings
        available_rooms = []
        for room in all_rooms:
            has_conflict = False
            try:
                # Check legacy Reservation table
                conflicts_result = await session.execute(
                    select(Reservation).where(
                        and_(
                            Reservation.room_id == room.id,
                            Reservation.status.in_(["booked", "confirmed", "checked_in"]),
                            Reservation.arrival_date < departure_date,
                            Reservation.departure_date > arrival_date
                        )
                    )
                )
                if conflicts_result.scalars().all():
                    has_conflict = True
            except Exception as e:
                import logging
                logging.error(f"Error checking reservation conflicts for room {room.id}: {e}")

            if not has_conflict:
                try:
                    # Check Booking table (V2.0 model)
                    booking_conflicts_result = await session.execute(
                        select(Booking).where(
                            and_(
                                Booking.room_id == room.id,
                                Booking.status.in_(["booked", "confirmed", "checked_in", "pending"]),
                                Booking.arrival_date < departure_date,
                                Booking.departure_date > arrival_date
                            )
                        )
                    )
                    if booking_conflicts_result.scalars().all():
                        has_conflict = True
                except Exception as e:
                    import logging
                    logging.error(f"Error checking booking conflicts for room {room.id}: {e}")

            if not has_conflict:
                available_rooms.append(room)

    # AI Room Scoring Algorithm
    scored_rooms = []
    for room in available_rooms:
        try:
            # Get room type info
            room_type_name = "Standard Room"
            room_type_price = 0
            if room.room_type_id:
                rt = await session.get(RoomType, room.room_type_id)
                if rt:
                    room_type_name = rt.name
                    room_type_price = rt.base_price or 0

            # Initialize scoring
            score = 0
            max_score = 100
            reasoning = []
            match_details = []

            # ==================== FLOOR PREFERENCE (25 points max) ====================
            floor_score = 0
            room_floor = room.floor or 1

            if precheckin.floor_preference and precheckin.floor_preference != "any":
                if precheckin.floor_preference == "high":
                    if room_floor >= 15:
                        floor_score = 25
                        reasoning.append(f"Perfect high floor match (Floor {room_floor})")
                    elif room_floor >= 10:
                        floor_score = 15
                        reasoning.append(f"Good upper floor (Floor {room_floor})")
                    else:
                        floor_score = 5
                        match_details.append(f"Floor {room_floor} - you preferred high floors")
                elif precheckin.floor_preference == "mid":
                    if 8 <= room_floor < 15:
                        floor_score = 25
                        reasoning.append(f"Perfect mid-floor match (Floor {room_floor})")
                    else:
                        floor_score = 10
                elif precheckin.floor_preference == "low":
                    if room_floor < 8:
                        floor_score = 25
                        reasoning.append(f"Perfect low floor for easy access (Floor {room_floor})")
                    else:
                        floor_score = 10
            else:
                floor_score = 15  # No preference = neutral score

            score += floor_score

            # ==================== VIEW PREFERENCE (25 points max) ====================
            view_score = 0
            room_view = (room.view_type or "").lower()

            if precheckin.view_preference and precheckin.view_preference != "any":
                pref_view = precheckin.view_preference.lower()
                if pref_view in room_view or room_view in pref_view:
                    view_score = 25
                    reasoning.append(f"Matches your {precheckin.view_preference} view preference")
                elif room_view:
                    view_score = 10
                    match_details.append(f"Has {room.view_type} view (you preferred {precheckin.view_preference})")
                else:
                    view_score = 5
            else:
                view_score = 15
                if room_view:
                    reasoning.append(f"Features {room.view_type} view")

            score += view_score

            # ==================== BED TYPE PREFERENCE (20 points max) ====================
            bed_score = 0
            room_bed = (room.bed_type or "").lower()

            if precheckin.bed_type_preference and precheckin.bed_type_preference != "any":
                pref_bed = precheckin.bed_type_preference.lower()
                if pref_bed in room_bed or room_bed in pref_bed:
                    bed_score = 20
                    reasoning.append(f"Has your preferred {room.bed_type} bed")
                elif room_bed:
                    bed_score = 8
                    match_details.append(f"Has {room.bed_type} bed (you preferred {precheckin.bed_type_preference})")
                else:
                    bed_score = 5
            else:
                bed_score = 12
                if room_bed:
                    reasoning.append(f"Equipped with {room.bed_type} bed")

            score += bed_score

            # ==================== QUIETNESS PREFERENCE (15 points max) ====================
            quiet_score = 0
            if precheckin.quietness_preference and precheckin.quietness_preference != "any":
                if precheckin.quietness_preference == "quiet":
                    # Rooms away from elevators/stairs, higher floors, end of corridor are quieter
                    if room_floor >= 10:
                        quiet_score = 15
                        reasoning.append("Quiet high floor location")
                    elif room.number and (room.number.endswith("01") or room.number.endswith("10")):
                        quiet_score = 12
                        reasoning.append("End-of-corridor room for privacy")
                    else:
                        quiet_score = 8
                else:
                    quiet_score = 12
            else:
                quiet_score = 10

            score += quiet_score

            # ==================== ROOM TYPE MATCH (15 points max) ====================
            type_score = 0
            if booked_room_type_name:
                if room_type_name.lower() == booked_room_type_name.lower():
                    type_score = 15
                    reasoning.append(f"Exact {room_type_name} as booked")
                else:
                    type_score = 5
                    match_details.append(f"Room type: {room_type_name}")
            else:
                type_score = 10

            score += type_score

            # ==================== VIP GUEST BONUS ====================
            # VIP guests get priority for premium rooms (high floor, best views)
            vip_bonus = 0
            is_vip_guest = False

            # Check if guest is VIP - use precheckin.guest_id which is always set
            guest = await session.get(Guest, precheckin.guest_id)
            if guest and guest.vip_status:
                is_vip_guest = True

            # Also check booking vip_flag if we have a booking
            if booking:
                if booking.vip_flag:
                    is_vip_guest = True

            if is_vip_guest:
                # VIP guests get bonus points for premium features
                if room_floor >= 15:
                    vip_bonus += 5
                    reasoning.append("VIP priority: Premium high floor")
                if room.view_type and ("ocean" in room.view_type.lower() or "city" in room.view_type.lower() or "garden" in room.view_type.lower()):
                    vip_bonus += 5
                    reasoning.append("VIP priority: Premium view")
                if "suite" in room_type_name.lower() or "deluxe" in room_type_name.lower():
                    vip_bonus += 5
                    reasoning.append("VIP priority: Premium room category")

            score += vip_bonus

            # Normalize score to percentage
            final_score = min(100, round((score / max_score) * 100))

            # Get room amenities
            amenities = []
            if room.amenities:
                try:
                    amenities = json.loads(room.amenities) if isinstance(room.amenities, str) else room.amenities
                except:
                    amenities = []

            # Get room images
            images = []
            if room.images:
                try:
                    images = json.loads(room.images) if isinstance(room.images, str) else room.images
                except:
                    images = []

            scored_rooms.append({
                "room_id": room.id,
                "room_number": room.number,
                "room_type": room_type_name,
                "floor": room_floor,
                "view": room.view_type or "Standard",
                "bed_type": room.bed_type or "King",
                "size": room.size_sqft or 300,
                "max_occupancy": room.max_occupancy or 2,
                "amenities": amenities[:5] if amenities else ["WiFi", "TV", "Mini Bar"],
                "images": images,
                "price": room_type_price,
                "score": final_score,
                "ai_score": final_score,
                "reasoning": reasoning if reasoning else ["Good room option based on availability"],
                "match_details": match_details,
                "recommendation_level": "excellent" if final_score >= 85 else "good" if final_score >= 70 else "suitable" if final_score >= 50 else "available",
            })
        except Exception as e:
            logging.error(f"Error scoring room {room.id}: {e}")
            continue  # Skip this room if scoring fails

    # Sort by score descending
    scored_rooms.sort(key=lambda x: x["score"], reverse=True)

    # Mark top recommendations
    for i, room in enumerate(scored_rooms):
        if i == 0:
            room["is_top_pick"] = True
            room["badge"] = "Best Match"
        elif i == 1:
            room["badge"] = "Great Choice"
        elif i == 2:
            room["badge"] = "Good Option"

    return {
        "recommended_rooms": scored_rooms[:10],  # Top 10 recommendations
        "total_available": len(scored_rooms),
        "preferences_used": {
            "floor": precheckin.floor_preference,
            "view": precheckin.view_preference,
            "bed_type": precheckin.bed_type_preference,
            "quietness": precheckin.quietness_preference,
        }
    }


@router.get("/rooms/browse")
async def browse_all_rooms(
    reservation_id: int = Query(..., description="Reservation ID to check availability"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """Browse all available rooms for a reservation - allows guest access"""
    from app.models.reservations import Booking

    # Check both Reservation and Booking tables
    reservation = await session.get(Reservation, reservation_id)
    booking = None

    if not reservation:
        # Try the newer Booking model
        booking = await session.get(Booking, reservation_id)
        if not booking:
            raise HTTPException(status_code=404, detail="Reservation not found")

    # Use either reservation or booking data
    arrival_date = reservation.arrival_date if reservation else booking.arrival_date
    departure_date = reservation.departure_date if reservation else booking.departure_date

    # Get all rooms - use broader filter, only exclude rooms that can't be used
    all_rooms = (await session.exec(select(Room).where(Room.status.notin_(["out_of_order", "out_of_service", "maintenance"])))).all()

    # Filter out rooms with conflicting reservations AND bookings
    available_rooms = []
    for room in all_rooms:
        # Check legacy Reservation table
        res_conflicts = (await session.exec(
            select(Reservation).where(
                and_(
                    Reservation.room_id == room.id,
                    Reservation.status.in_(["booked", "confirmed", "checked_in"]),
                    Reservation.arrival_date < departure_date,
                    Reservation.departure_date > arrival_date
                )
            )
        )).all()
        # Check Booking table (V2.0 model)
        bk_conflicts = (await session.exec(
            select(Booking).where(
                and_(
                    Booking.room_id == room.id,
                    Booking.status.in_(["booked", "confirmed", "checked_in", "pending"]),
                    Booking.arrival_date < departure_date,
                    Booking.departure_date > arrival_date
                )
            )
        )).all()
        if not res_conflicts and not bk_conflicts:
            # Get room type
            room_type_name = "Standard Room"
            room_type_price = 0
            if room.room_type_id:
                rt = await session.get(RoomType, room.room_type_id)
                if rt:
                    room_type_name = rt.name
                    room_type_price = rt.base_price or 0

            # Get amenities
            amenities = []
            if room.amenities:
                try:
                    amenities = json.loads(room.amenities) if isinstance(room.amenities, str) else room.amenities
                except:
                    amenities = []

            available_rooms.append({
                "room_id": room.id,
                "room_number": room.number,
                "room_type": room_type_name,
                "floor": room.floor or 1,
                "view": room.view_type or "Standard",
                "bed_type": room.bed_type or "King",
                "size": room.size_sqft or 300,
                "max_occupancy": room.max_occupancy or 2,
                "amenities": amenities[:5] if amenities else ["WiFi", "TV", "Mini Bar"],
                "price": room_type_price,
                "status": room.status,
            })

    return {
        "rooms": available_rooms,
        "total": len(available_rooms),
        "reservation_dates": {
            "check_in": arrival_date.isoformat(),
            "check_out": departure_date.isoformat(),
        }
    }


# ============== DOCUMENT VERIFICATION ==============

class DocumentVerifyRequest(BaseModel):
    precheckin_id: Optional[int] = None
    image_url: str  # Base64 encoded image or URL
    expected_name: str
    id_type: str = "passport"  # passport, drivers-license, national-id


class DocumentVerifyResponse(BaseModel):
    verified: bool
    confidence: float
    extracted_name: Optional[str] = None
    id_type_detected: Optional[str] = None
    id_number: Optional[str] = None
    expiry_date: Optional[str] = None
    message: str
    details: Optional[dict] = None


@router.post("/verify-document", response_model=DocumentVerifyResponse)
async def verify_document(
    payload: DocumentVerifyRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user_optional)
):
    """Verify ID document using OpenAI Vision API - allows guest access"""
    from app.core.config import settings
    import base64
    import httpx

    # Get all valid names to check against:
    # 1. The expected name from the booking/guest record (passed in payload)
    # 2. The current user's profile name (in case they updated it recently)
    valid_names = [payload.expected_name.lower().strip()]

    if current_user and current_user.full_name:
        user_profile_name = current_user.full_name.lower().strip()
        if user_profile_name and user_profile_name not in valid_names:
            valid_names.append(user_profile_name)

    # Check if OpenAI API key is configured
    if not settings.openai_api_key:
        # Fallback to mock verification if no API key
        return _mock_document_verification(payload)

    try:
        # Prepare the image for OpenAI
        image_content = payload.image_url

        # If it's a base64 string, prepare for API
        if image_content.startswith("data:image"):
            # Already in correct format
            image_data = image_content
        elif image_content.startswith("http"):
            # It's a URL, download the image
            async with httpx.AsyncClient() as client:
                response = await client.get(image_content)
                if response.status_code == 200:
                    image_bytes = response.content
                    image_b64 = base64.b64encode(image_bytes).decode()
                    content_type = response.headers.get("content-type", "image/jpeg")
                    image_data = f"data:{content_type};base64,{image_b64}"
                else:
                    return DocumentVerifyResponse(
                        verified=False,
                        confidence=0,
                        message="Failed to download image from URL"
                    )
        else:
            # Assume it's raw base64
            image_data = f"data:image/jpeg;base64,{image_content}"

        # Call OpenAI Vision API
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o-mini",  # Use vision-capable model
                    "messages": [
                        {
                            "role": "system",
                            "content": """You are a strict ID document verification assistant for a hotel check-in system. Your job is to verify that the uploaded image is a REAL, VALID government-issued ID document.

IMPORTANT: You must be STRICT in verification. Only approve documents that are clearly legitimate government IDs.

Analyze the image and determine:
1. Is this actually a government-issued ID document? (passport, driver's license, national ID card)
   - If it's a random image, screenshot, meme, or non-ID document, mark is_valid_document as FALSE
   - If you cannot clearly see ID document features (photo, name, document number, official seals/holograms), mark as FALSE
2. The full name exactly as it appears on the document
3. The type of ID (passport, driver's license, national ID)
4. The ID/document number if visible
5. The expiry date if visible (check if expired)
6. Your confidence level (0.0-1.0) - be conservative, use lower values if unsure

REJECTION CRITERIA (mark is_valid_document as FALSE if ANY apply):
- Image is not an ID document (random photo, screenshot, meme, etc.)
- Cannot clearly read the name on the document
- Document appears to be a photocopy or digital reproduction
- Document features are not visible (no photo, no official markings)
- Document appears tampered or fake
- Document is expired

Respond ONLY in JSON format:
{
    "name": "extracted full name or null if not readable",
    "id_type": "passport/drivers_license/national_id/not_an_id",
    "id_number": "document number or null",
    "expiry_date": "YYYY-MM-DD or null",
    "is_valid_document": true/false,
    "confidence": 0.0-1.0,
    "issues": ["list of any issues found"],
    "rejection_reason": "reason if rejected or null"
}"""
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"Please analyze this ID document. The guest claims their name is '{payload.expected_name}'. Verify if the name on the document matches and extract the document details."
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": image_data
                                    }
                                }
                            ]
                        }
                    ],
                    "max_tokens": 500
                },
                timeout=30.0
            )

            if response.status_code != 200:
                # Fallback to mock if API fails
                return _mock_document_verification(payload)

            result = response.json()
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

            # Parse the JSON response
            try:
                # Extract JSON from the response
                import re
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    doc_data = json.loads(json_match.group())
                else:
                    return _mock_document_verification(payload)

                extracted_name = doc_data.get("name") or ""
                extracted_name_lower = extracted_name.lower().strip()
                # Note: valid_names list was built at the start of this function
                # It includes both the booking guest name AND the user's profile name

                # Check if this is actually an ID document
                id_type_detected = doc_data.get("id_type", "").lower()
                is_valid = doc_data.get("is_valid_document", False)  # Default to False for safety
                confidence = doc_data.get("confidence", 0.0)
                rejection_reason = doc_data.get("rejection_reason")

                # Reject if not a valid ID document
                if id_type_detected == "not_an_id" or not is_valid:
                    return DocumentVerifyResponse(
                        verified=False,
                        confidence=confidence,
                        extracted_name=extracted_name if extracted_name else None,
                        id_type_detected=id_type_detected,
                        message=rejection_reason or "The uploaded image is not a valid government-issued ID document. Please upload a clear photo of your passport, driver's license, or national ID card.",
                        details={
                            "issues": doc_data.get("issues", []),
                            "rejection_reason": rejection_reason
                        }
                    )

                # Reject if name is not readable
                if not extracted_name_lower:
                    return DocumentVerifyResponse(
                        verified=False,
                        confidence=confidence,
                        extracted_name=None,
                        id_type_detected=id_type_detected,
                        message="Could not read the name on the document. Please upload a clearer image.",
                        details={
                            "issues": ["Name not readable on document"]
                        }
                    )

                # Check name match (flexible matching with fuzzy comparison)
                # Check against ALL valid names (booking name + profile name)
                name_parts_extracted = extracted_name_lower.split()

                def fuzzy_match(s1: str, s2: str, threshold: float = 0.70) -> bool:
                    """Check if two strings are similar using Levenshtein distance ratio"""
                    if s1 == s2:
                        return True
                    if not s1 or not s2:
                        return False

                    len1, len2 = len(s1), len(s2)
                    if abs(len1 - len2) > 3:  # Length difference too big
                        return False

                    # Calculate Levenshtein distance
                    # This properly handles transpositions like Agrawal/Agarwal
                    if len1 < len2:
                        s1, s2 = s2, s1
                        len1, len2 = len2, len1

                    # Create distance matrix
                    previous_row = list(range(len2 + 1))
                    for i, c1 in enumerate(s1):
                        current_row = [i + 1]
                        for j, c2 in enumerate(s2):
                            # Cost is 0 if characters match, 1 otherwise
                            insertions = previous_row[j + 1] + 1
                            deletions = current_row[j] + 1
                            substitutions = previous_row[j] + (0 if c1 == c2 else 1)
                            current_row.append(min(insertions, deletions, substitutions))
                        previous_row = current_row

                    distance = previous_row[-1]
                    max_len = max(len1, len2)
                    similarity = 1 - (distance / max_len)

                    # For debugging
                    import logging
                    logging.debug(f"Fuzzy match '{s1}' vs '{s2}': distance={distance}, similarity={similarity:.2f}, threshold={threshold}")

                    return similarity >= threshold

                def names_match(extracted_parts: list, expected_parts: list) -> bool:
                    """Check if names match with fuzzy matching for spelling variations"""
                    # Exact match on sets
                    if set(extracted_parts) == set(expected_parts):
                        return True

                    # Check if first names match (fuzzy) - most important
                    first_name_match = False
                    if extracted_parts and expected_parts:
                        first_name_match = fuzzy_match(extracted_parts[0], expected_parts[0])

                    # Check last names match (fuzzy)
                    last_name_match = False
                    if len(extracted_parts) > 1 and len(expected_parts) > 1:
                        last_name_match = fuzzy_match(extracted_parts[-1], expected_parts[-1])
                    elif len(extracted_parts) == 1 or len(expected_parts) == 1:
                        # Single name case - first name match is enough
                        last_name_match = True

                    # Both first and last name should fuzzy match
                    if first_name_match and last_name_match:
                        return True

                    # Check for any exact matches (at least one part)
                    common_exact = set(extracted_parts) & set(expected_parts)
                    if len(common_exact) >= 1:
                        # If we have at least one exact match, check if others are close
                        remaining_extracted = [p for p in extracted_parts if p not in common_exact]
                        remaining_expected = [p for p in expected_parts if p not in common_exact]

                        if not remaining_extracted or not remaining_expected:
                            return True  # All parts matched

                        # Check if remaining parts fuzzy match
                        for ext_part in remaining_extracted:
                            for exp_part in remaining_expected:
                                if fuzzy_match(ext_part, exp_part, 0.75):
                                    return True

                    # Full string containment
                    extracted_full = ''.join(extracted_parts)
                    expected_full = ''.join(expected_parts)
                    if extracted_full in expected_full or expected_full in extracted_full:
                        return True

                    return False

                # Check against all valid names (booking guest name + user profile name)
                name_match = False
                matched_against = None
                for valid_name in valid_names:
                    name_parts_expected = valid_name.split()
                    if names_match(name_parts_extracted, name_parts_expected):
                        name_match = True
                        matched_against = valid_name
                        break

                # Log for debugging
                import logging
                logging.info(f"ID Verification - Valid names: {valid_names}, Extracted: '{extracted_name}', Match: {name_match} (against: {matched_against}), Valid: {is_valid}, Confidence: {confidence}")

                if name_match and is_valid and confidence >= 0.5:
                    # Update precheckin with verified info if precheckin_id is provided
                    if payload.precheckin_id:
                        precheckin = await session.get(PreCheckIn, payload.precheckin_id)
                        if precheckin:
                            precheckin.id_verified = True
                            precheckin.id_type = doc_data.get("id_type", payload.id_type)
                            await session.commit()

                    return DocumentVerifyResponse(
                        verified=True,
                        confidence=confidence,
                        extracted_name=doc_data.get("name"),
                        id_type_detected=doc_data.get("id_type"),
                        id_number=doc_data.get("id_number"),
                        expiry_date=doc_data.get("expiry_date"),
                        message=f"Document verified successfully. Name matches your profile.",
                        details={
                            "issues": doc_data.get("issues", []),
                            "name_match": True,
                            "matched_against": matched_against,
                            "valid_names_checked": valid_names
                        }
                    )
                else:
                    issues = doc_data.get("issues", [])

                    # Build detailed failure message
                    failure_reasons = []
                    if not is_valid:
                        failure_reasons.append("document not recognized as valid ID")
                    if not name_match:
                        names_str = "' or '".join(valid_names)
                        failure_reasons.append(f"name '{extracted_name}' doesn't match '{names_str}'")
                    if confidence < 0.5:
                        failure_reasons.append(f"low confidence ({confidence*100:.0f}%)")

                    failure_msg = f"Verification failed: {', '.join(failure_reasons)}." if failure_reasons else "Document verification failed."

                    return DocumentVerifyResponse(
                        verified=False,
                        confidence=confidence,
                        extracted_name=doc_data.get("name"),
                        id_type_detected=doc_data.get("id_type"),
                        id_number=doc_data.get("id_number"),
                        message=failure_msg,
                        details={
                            "issues": issues,
                            "valid_names_checked": valid_names,
                            "name_match": name_match,
                            "is_valid_document": is_valid
                        }
                    )

            except json.JSONDecodeError:
                return _mock_document_verification(payload)

    except Exception as e:
        # Fallback to mock verification on any error
        return _mock_document_verification(payload)


def _mock_document_verification(payload: DocumentVerifyRequest) -> DocumentVerifyResponse:
    """Mock document verification when OpenAI API is not available.
    Allows the pre-checkin flow to continue with a provisional verification,
    while flagging for manual check at the front desk."""
    return DocumentVerifyResponse(
        verified=True,
        confidence=0.6,
        extracted_name=payload.expected_name,
        id_type_detected=payload.id_type or "government_id",
        id_number=None,
        expiry_date=None,
        message="Document uploaded successfully. Provisional verification granted. Please bring your ID for confirmation at the front desk during check-in.",
        details={
            "note": "Automated AI verification is not available. Provisional approval granted to allow pre-checkin completion.",
            "verification_type": "provisional",
            "action_required": "Confirm ID at front desk during check-in"
        }
    )


@router.post("/{precheckin_id}/upload-document")
async def upload_document(
    precheckin_id: int,
    document_type: str = Query(..., description="front or back"),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Upload ID document for verification"""
    import base64
    import os

    precheckin = await session.get(PreCheckIn, precheckin_id)
    if not precheckin:
        raise HTTPException(status_code=404, detail="Pre-checkin not found")

    # Read file content
    content = await file.read()
    file_size = len(content)

    # Validate file size (max 5MB)
    if file_size > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 5MB.")

    # Validate file type
    allowed_types = ["image/jpeg", "image/png", "image/jpg", "application/pdf"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Allowed: JPEG, PNG, PDF")

    # Create uploads directory if it doesn't exist
    upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "uploads", "documents")
    os.makedirs(upload_dir, exist_ok=True)

    # Generate filename
    import uuid
    ext = file.filename.split(".")[-1] if file.filename else "jpg"
    filename = f"precheckin_{precheckin_id}_{document_type}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = os.path.join(upload_dir, filename)

    # Save file
    with open(filepath, "wb") as f:
        f.write(content)

    # Generate URL (relative path)
    file_url = f"/uploads/documents/{filename}"

    # Update precheckin
    if document_type == "front":
        precheckin.id_front_url = file_url
    else:
        precheckin.id_back_url = file_url

    precheckin.updated_at = datetime.utcnow()
    await session.commit()

    # Return base64 for immediate display and verification
    b64_content = base64.b64encode(content).decode()

    return {
        "success": True,
        "file_url": file_url,
        "file_name": filename,
        "document_type": document_type,
        "base64": f"data:{file.content_type};base64,{b64_content}",
        "message": f"Document {document_type} uploaded successfully"
    }

