import secrets
from datetime import datetime, date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.reservations import Reservation, Booking, Guest, ReservationHistory
from app.models.operations import Folio, FolioLineItem, Payment, KeyCard, GuestCommunication, NightAudit, ShiftHandover, HotelConfig, ChargeRoutingRule, CashierSession
from app.core.business_date import get_business_date, advance_business_date
from app.core.tax import apply_tax_to_line_item
from app.models.user import User
from app.models.inventory import Room, RoomType

router = APIRouter()


class CheckInRequest(BaseModel):
    room_id: Optional[int] = None
    id_verified: bool = False
    id_type: Optional[str] = None
    id_number: Optional[str] = None
    notes: Optional[str] = None


class CheckOutRequest(BaseModel):
    final_balance: Optional[float] = None
    notes: Optional[str] = None


class PaymentCreate(BaseModel):
    amount: float
    method: str = "card"
    payment_type: str = "full_payment"
    transaction_id: Optional[str] = None
    card_last4: Optional[str] = None
    card_brand: Optional[str] = None
    notes: Optional[str] = None


class FolioLineItemCreate(BaseModel):
    item_type: str
    description: str
    quantity: float = 1.0
    unit_price: float
    amount: float
    notes: Optional[str] = None


def generate_folio_number() -> str:
    return f"FOL-{secrets.token_urlsafe(6).upper().replace('_', '').replace('-', '')[:6]}"


def generate_keycard_number() -> str:
    return f"KC{secrets.token_hex(4).upper()}"


@router.post("/checkin/{reservation_id}")
async def check_in(
    reservation_id: int,
    payload: CheckInRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    # BUG-010 FIX: Check Booking table FIRST (primary system), then fall back
    # to legacy Reservation table. Previously checked Reservation first, which
    # caused ID collisions (e.g. Reservation #14 blocking Booking #14).
    booking = await session.get(Booking, reservation_id)
    if booking:
        if booking.status not in ("booked", "confirmed"):
            raise HTTPException(status_code=400, detail="Booking not eligible for check-in")

        # Validate date — cannot check in before arrival or after departure
        today = await get_business_date(session)
        if booking.arrival_date > today:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot check in before arrival date ({booking.arrival_date})"
            )
        if booking.departure_date <= today:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot check in — booking has expired (checkout was {booking.departure_date}). Mark as No Show instead."
            )

        # Update guest ID verification if provided
        if payload.id_verified and booking.guest_id:
            guest = await session.get(Guest, booking.guest_id)
            if guest:
                guest.id_verified = payload.id_verified
                if payload.id_type:
                    guest.id_type = payload.id_type
                if payload.id_number:
                    guest.id_number = payload.id_number

        # Assign room if specified
        if payload.room_id:
            # Validate room type matches the booking's room type
            room_to_assign = await session.get(Room, payload.room_id)
            if not room_to_assign:
                raise HTTPException(status_code=404, detail="Room not found")
            # Validate room status - dirty/occupied rooms cannot be assigned
            if room_to_assign.status not in ["available", "clean", "inspected"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"Room {room_to_assign.number} is not available for assignment (status: {room_to_assign.status}). "
                           f"Only rooms with status 'available', 'clean', or 'inspected' can be assigned."
                )
            if booking.room_type_id and room_to_assign.room_type_id != booking.room_type_id:
                booked_type = await session.get(RoomType, booking.room_type_id)
                assigned_type = await session.get(RoomType, room_to_assign.room_type_id)
                booked_name = booked_type.name if booked_type else "the booked type"
                assigned_name = assigned_type.name if assigned_type else "Unknown"
                raise HTTPException(
                    status_code=400,
                    detail=f"Room type mismatch: Guest booked {booked_name} but Room {room_to_assign.number} is {assigned_name}. "
                           f"Please assign a room that matches the booked room type."
                )
            booking.room_id = payload.room_id

        # Ensure room is assigned before check-in
        if not booking.room_id:
            raise HTTPException(status_code=400, detail="No room assigned to this booking. Please assign a room before check-in.")

        # Process check-in for Booking record
        booking.status = "checked_in"
        booking.check_in_date = datetime.utcnow()

        # BUG-010 FIX: Mark room as "occupied" on check-in
        room_id = booking.room_id
        if room_id:
            room = await session.get(Room, room_id)
            if room:
                room.status = "occupied"
                room.occupancy_status = "occupied"
                room.cleaning_status = "clean"

        # Create folio if none exists and post ALL charges upfront
        existing_folio = (await session.exec(
            select(Folio).where(Folio.booking_id == booking.id)
        )).first()

        if not existing_folio:
            folio = Folio(
                booking_id=booking.id,
                reservation_id=booking.id,  # Use booking_id as fallback
                folio_number=generate_folio_number(),
                total_charges=0.0,
                total_payments=0.0,
                balance=0.0,
            )
            session.add(folio)
            await session.flush()

            # POST ALL CHARGES AT CHECK-IN (not per-night via night audit)
            # This removes night audit dependency for billing
            import logging
            from datetime import date
            from app.services.billing_engine import calculate_stay_charges
            from app.services.billing_service import (
                get_effective_nightly_rate,
                create_room_charge_line_item,
                recalculate_folio_totals,
            )

            # Use stored nightly_rate from booking (set at booking creation)
            # This ensures consistency between what guest was quoted and what they're charged
            nightly_rate = booking.nightly_rate

            # Fallback: get effective rate from booking/room type
            if not nightly_rate or nightly_rate <= 0:
                nightly_rate = await get_effective_nightly_rate(session, booking)

            # Additional fallback to room type base price
            if nightly_rate <= 0 and booking.room_type_id:
                from app.models.inventory import RoomType
                rt = await session.get(RoomType, booking.room_type_id)
                if rt and rt.base_price:
                    nightly_rate = float(rt.base_price)

            if nightly_rate <= 0 and booking.room_id:
                from app.models.inventory import Room as RoomModel, RoomType
                room_obj = await session.get(RoomModel, booking.room_id)
                if room_obj and room_obj.room_type_id:
                    rt = await session.get(RoomType, room_obj.room_type_id)
                    if rt and rt.base_price:
                        nightly_rate = float(rt.base_price)

            if nightly_rate <= 0:
                nightly_rate = 1000.0  # Emergency fallback

            # Calculate charges for ENTIRE stay using billing_engine
            total_nights = booking.nights or 1
            charges = calculate_stay_charges(nightly_rate, total_nights)

            check_in_date = booking.check_in_date.date() if booking.check_in_date else booking.arrival_date
            check_out_date = booking.departure_date

            # Post full room charge for all nights at once
            description = f"Room charges – {check_in_date.isoformat()} to {check_out_date.isoformat()} ({total_nights} night(s) @ ₹{nightly_rate:.2f}/night)"
            room_charge, tax_item = await create_room_charge_line_item(
                folio_id=folio.id,
                per_night_rate=nightly_rate,
                nights=total_nights,
                posted_by=current_user.id,
                description=description,
                charge_date=check_in_date,
            )
            session.add(room_charge)
            session.add(tax_item)

            await recalculate_folio_totals(session, folio)
            logging.info(f"Folio created for booking {booking.id} with ALL charges ({total_nights} nights): ₹{float(charges.total_amount):.2f}")

        await session.commit()
        await session.refresh(booking)

        return {
            "message": "Guest checked in successfully",
            "booking_id": booking.id,
            "status": "checked_in",
            "check_in_time": booking.check_in_date.isoformat() if booking.check_in_date else None,
        }

    # Fall back to legacy Reservation table
    res = await session.get(Reservation, reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")

    if res.status != "booked":
        raise HTTPException(status_code=400, detail="Reservation not eligible for check-in")

    # Validate date
    today = await get_business_date(session)
    if hasattr(res, 'arrival_date') and res.arrival_date and res.arrival_date > today:
        raise HTTPException(status_code=400, detail=f"Cannot check in before arrival date ({res.arrival_date})")

    # Update guest ID verification if provided
    if payload.id_verified and res.guest_id:
        guest = await session.get(Guest, res.guest_id)
        if guest:
            guest.id_verified = payload.id_verified
            if payload.id_type:
                guest.id_type = payload.id_type
            if payload.id_number:
                guest.id_number = payload.id_number
    
    # Assign room if specified
    if payload.room_id:
        from app.services.reservation_service import assign_room
        await assign_room(session, reservation_id, payload.room_id, auto_assign=False)
    
    # Create or get folio
    folio = (await session.exec(
        select(Folio).where(Folio.reservation_id == reservation_id)
    )).first()

    # Try to find associated Booking (for folio linking)
    associated_booking = None
    if hasattr(res, 'confirmation_code') and res.confirmation_code:
        associated_booking = (await session.exec(
            select(Booking).where(Booking.confirmation_code == res.confirmation_code)
        )).first()

    if not folio:
        # Create folio and post first night's charge (standard hotel practice)
        folio = Folio(
            booking_id=associated_booking.id if associated_booking else None,
            reservation_id=res.id,
            folio_number=generate_folio_number(),
            total_charges=0.0,
            total_payments=0.0,
            balance=0.0,
        )
        session.add(folio)
        await session.flush()

        # Post first night's room charge immediately
        import logging
        from datetime import date as date_module
        from app.services.billing_service import (
            create_room_charge_line_item,
            recalculate_folio_totals,
        )

        # Get nightly rate from reservation or associated booking
        nightly_rate = 0.0
        if associated_booking:
            from app.services.billing_service import get_effective_nightly_rate
            nightly_rate = await get_effective_nightly_rate(session, associated_booking)

        # Fallback: try to get from reservation fields
        if nightly_rate <= 0 and hasattr(res, 'base_price') and res.base_price:
            nights = res.nights or 1
            nightly_rate = float(res.base_price) / nights

        if nightly_rate <= 0 and hasattr(res, 'total_amount') and res.total_amount:
            nights = res.nights or 1
            nightly_rate = float(res.total_amount) / 1.12 / nights  # Reverse tax

        if nightly_rate <= 0:
            nightly_rate = 1000.0  # Emergency fallback

        # Post first night's room charge (use date-based description for duplicate detection)
        check_in_date = res.check_in_date.date() if hasattr(res, 'check_in_date') and res.check_in_date else (res.arrival_date if hasattr(res, 'arrival_date') and res.arrival_date else date_module.today())
        charge_date_str = check_in_date.isoformat() if hasattr(check_in_date, 'isoformat') else str(check_in_date)
        room_charge, tax_item = await create_room_charge_line_item(
            folio_id=folio.id,
            per_night_rate=nightly_rate,
            nights=1,
            posted_by=current_user.id,
            description=f"Room charge – {charge_date_str} @ ₹{nightly_rate:.2f}",
            charge_date=check_in_date,
        )
        session.add(room_charge)
        session.add(tax_item)

        await recalculate_folio_totals(session, folio)
        logging.info(f"Folio {folio.folio_number} created for reservation {res.id} with first night charge ({charge_date_str}): ₹{nightly_rate}")
    elif not folio.booking_id and associated_booking:
        # Link existing folio to booking
        folio.booking_id = associated_booking.id
        import logging
        logging.info(f"Linked folio {folio.id} to booking {associated_booking.id}")
    
    # Update reservation status
    res.status = "checked_in"
    
    # Create history entry
    history = ReservationHistory(
        reservation_id=reservation_id,
        action="checked_in",
        changed_by=current_user.id,
        notes=payload.notes or "Guest checked in"
    )
    session.add(history)
    
    await session.commit()
    await session.refresh(res)
    return {"status": "checked_in", "reservation_id": res.id, "folio_id": folio.id}


@router.post("/checkout/{reservation_id}")
async def check_out(
    reservation_id: int,
    payload: CheckOutRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    res = await session.get(Reservation, reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if res.status != "checked_in":
        raise HTTPException(status_code=400, detail="Reservation not eligible for check-out")
    
    # Get folio
    folio = (await session.exec(
        select(Folio).where(Folio.reservation_id == reservation_id)
    )).first()
    
    if folio and folio.balance > 0:
        raise HTTPException(status_code=400, detail=f"Outstanding balance: {folio.balance}. Please settle payment first.")

    # Update room status to dirty after checkout
    if res.room_id:
        room = await session.get(Room, res.room_id)
        if room:
            room.status = "dirty"
            room.occupancy_status = "vacant"
            room.cleaning_status = "dirty"
            room.updated_at = datetime.utcnow()

    res.status = "checked_out"

    if folio:
        folio.status = "closed"
        folio.closed_at = datetime.utcnow()
        folio.closed_by = current_user.id
    
    # Deactivate key cards
    key_cards = (await session.exec(
        select(KeyCard).where(
            and_(
                KeyCard.reservation_id == reservation_id,
                KeyCard.status == "active"
            )
        )
    )).all()
    
    for kc in key_cards:
        kc.status = "deactivated"
        kc.deactivated_at = datetime.utcnow()
        kc.deactivated_by = current_user.id
    
    # Create history entry
    history = ReservationHistory(
        reservation_id=reservation_id,
        action="checked_out",
        changed_by=current_user.id,
        notes=payload.notes or "Guest checked out"
    )
    session.add(history)
    
    await session.commit()
    await session.refresh(res)
    return {"status": "checked_out", "reservation_id": res.id}


@router.get("/folio/{reservation_id}")
async def get_folio(
    reservation_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    folio = (await session.exec(
        select(Folio).where(Folio.reservation_id == reservation_id)
    )).first()
    
    if not folio:
        raise HTTPException(status_code=404, detail="Folio not found")
    
    # Get line items
    line_items = (await session.exec(
        select(FolioLineItem)
        .where(FolioLineItem.folio_id == folio.id)
        .order_by(FolioLineItem.posted_at.desc())
    )).all()
    
    # Get payments
    payments = (await session.exec(
        select(Payment)
        .where(Payment.folio_id == folio.id)
        .order_by(Payment.processed_at.desc())
    )).all()
    
    return {
        "folio": {
            "id": folio.id,
            "folio_number": folio.folio_number,
            "total_charges": folio.total_charges,
            "total_payments": folio.total_payments,
            "balance": folio.balance,
            "status": folio.status
        },
        "line_items": [{"id": li.id, "item_type": li.item_type, "description": li.description,
                        "quantity": li.quantity, "unit_price": li.unit_price, "amount": li.amount,
                        "posted_at": li.posted_at} for li in line_items],
        "payments": [{"id": p.id, "amount": p.amount, "method": p.method, "status": p.status,
                      "processed_at": p.processed_at} for p in payments]
    }


@router.post("/folio/{reservation_id}/line-items", status_code=status.HTTP_201_CREATED)
async def add_folio_line_item(
    reservation_id: int,
    payload: FolioLineItemCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    folio = (await session.exec(
        select(Folio).where(Folio.reservation_id == reservation_id)
    )).first()
    
    if not folio:
        raise HTTPException(status_code=404, detail="Folio not found")
    
    line_item = FolioLineItem(
        folio_id=folio.id,
        item_type=payload.item_type,
        description=payload.description,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        amount=payload.amount,
        posted_by=current_user.id,
        notes=payload.notes
    )
    await apply_tax_to_line_item(session, line_item)
    session.add(line_item)

    # Update folio totals
    folio.total_charges += payload.amount
    folio.balance = folio.total_charges - folio.total_payments
    folio.updated_at = datetime.utcnow()
    
    await session.commit()
    await session.refresh(line_item)
    return {"id": line_item.id, "status": "created"}


@router.post("/folio/{reservation_id}/payments", status_code=status.HTTP_201_CREATED)
async def process_payment(
    reservation_id: int,
    payload: PaymentCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    folio = (await session.exec(
        select(Folio).where(Folio.reservation_id == reservation_id)
    )).first()

    if not folio:
        raise HTTPException(status_code=404, detail="Folio not found")

    # Check if this is a child booking - payments must go through parent
    if folio.booking_id:
        booking = await session.get(Booking, folio.booking_id)
        if booking and booking.parent_booking_id:
            parent = await session.get(Booking, booking.parent_booking_id)
            raise HTTPException(
                status_code=400,
                detail=f"This is a child booking in a group. Payments must be made on the parent booking "
                       f"({parent.booking_number if parent else booking.parent_booking_id})"
            )
    
    payment = Payment(
        folio_id=folio.id,
        amount=payload.amount,
        method=payload.method,
        payment_type=payload.payment_type,
        transaction_id=payload.transaction_id,
        card_last4=payload.card_last4,
        card_brand=payload.card_brand,
        status="captured",
        processed_by=current_user.id,
        notes=payload.notes
    )
    session.add(payment)
    
    # Add payment as line item
    payment_line = FolioLineItem(
        folio_id=folio.id,
        item_type="payment",
        description=f"Payment via {payload.method}",
        quantity=1.0,
        unit_price=-payload.amount,  # Negative for payment
        amount=-payload.amount,
        posted_by=current_user.id,
        reference_id=payment.id
    )
    session.add(payment_line)
    
    # Update folio totals
    folio.total_payments += payload.amount
    folio.balance = folio.total_charges - folio.total_payments
    folio.updated_at = datetime.utcnow()
    
    await session.commit()
    await session.refresh(payment)
    return {"id": payment.id, "status": "processed", "balance": folio.balance}


@router.post("/keycard/{reservation_id}")
async def issue_keycard(
    reservation_id: int,
    room_id: Optional[int] = None,
    valid_until: Optional[datetime] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    res = await session.get(Reservation, reservation_id)
    if not res:
        raise HTTPException(status_code=404, detail="Reservation not found")
    
    if not room_id:
        room_id = res.room_id
    
    if not room_id:
        raise HTTPException(status_code=400, detail="Room not assigned to reservation")
    
    room = await session.get(Room, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="Room not found")
    
    # Deactivate existing key cards for this reservation
    existing = (await session.exec(
        select(KeyCard).where(
            and_(
                KeyCard.reservation_id == reservation_id,
                KeyCard.status == "active"
            )
        )
    )).all()
    
    for kc in existing:
        kc.status = "deactivated"
        kc.deactivated_at = datetime.utcnow()
        kc.deactivated_by = current_user.id
    
    # Create new key card
    if not valid_until:
        valid_until = datetime.combine(res.departure_date, datetime.max.time())
    
    keycard = KeyCard(
        reservation_id=reservation_id,
        card_number=generate_keycard_number(),
        room_id=room_id,
        issued_by=current_user.id,
        valid_from=datetime.utcnow(),
        valid_until=valid_until
    )
    session.add(keycard)
    await session.commit()
    await session.refresh(keycard)
    
    return {"card_number": keycard.card_number, "room_number": room.number, "valid_until": keycard.valid_until}


@router.get("/arrivals")
async def get_arrivals(
    date_filter: Optional[date] = Query(None, alias="date"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    target_date = date_filter or await get_business_date(session)
    arrivals = (await session.exec(
        select(Booking)
        .where(
            and_(
                Booking.arrival_date == target_date,
                Booking.status.in_(["booked", "confirmed", "checked_in"])
            )
        )
        .order_by(Booking.arrival_date)
    )).all()
    
    # Get guest and room info
    result = []
    for r in arrivals:
        guest = await session.get(Guest, r.guest_id) if r.guest_id else None
        room = await session.get(Room, r.room_id) if r.room_id else None
        result.append({
            "id": r.id,
            "confirmation_code": r.confirmation_code,
            "guest_id": r.guest_id,
            "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
            "arrival_date": r.arrival_date,
            "status": r.status,
            "room_id": r.room_id,
            "room_number": room.number if room else None
        })
    return result


@router.get("/departures")
async def get_departures(
    date_filter: Optional[date] = Query(None, alias="date"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    target_date = date_filter or await get_business_date(session)
    departures = (await session.exec(
        select(Booking)
        .where(
            and_(
                Booking.departure_date == target_date,
                Booking.status.in_(["checked_in"])
            )
        )
        .order_by(Booking.departure_date)
    )).all()
    
    # Get guest and room info
    result = []
    for r in departures:
        guest = await session.get(Guest, r.guest_id) if r.guest_id else None
        room = await session.get(Room, r.room_id) if r.room_id else None
        result.append({
            "id": r.id,
            "confirmation_code": r.confirmation_code,
            "guest_id": r.guest_id,
            "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
            "departure_date": r.departure_date,
            "status": r.status,
            "room_id": r.room_id,
            "room_number": room.number if room else None
        })
    return result


@router.get("/night-audit/status")
async def get_night_audit_status(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Check night audit status for today.

    Returns:
    - can_run: Whether night audit can be run now
    - status: pending, completed, running
    - business_date: Current business date
    - calendar_date: Today's calendar date
    - last_audit: Details of last completed audit (if any)
    - message: Human-readable status message
    """
    today = date.today()
    business_date = await get_business_date(session)

    # Check today's audit status
    todays_audit = (await session.exec(
        select(NightAudit).where(NightAudit.audit_date == today)
    )).first()

    # Check if any audit is currently running
    running_audit = (await session.exec(
        select(NightAudit).where(NightAudit.status == "running")
    )).first()

    # Get last completed audit
    last_completed = (await session.exec(
        select(NightAudit)
        .where(NightAudit.status == "completed")
        .order_by(NightAudit.audit_date.desc())
        .limit(1)
    )).first()

    # Determine status
    if running_audit:
        run_age = (datetime.utcnow() - running_audit.run_at).total_seconds() if running_audit.run_at else 0
        return {
            "can_run": False,
            "status": "running",
            "business_date": str(business_date),
            "calendar_date": str(today),
            "message": f"Night audit is currently running for {running_audit.audit_date} (started {int(run_age)}s ago)",
            "running_audit": {
                "audit_date": str(running_audit.audit_date),
                "started_at": running_audit.run_at.isoformat() if running_audit.run_at else None,
            }
        }

    if todays_audit and todays_audit.status == "completed":
        return {
            "can_run": False,
            "status": "completed",
            "business_date": str(business_date),
            "calendar_date": str(today),
            "message": f"Night audit for {today} already completed. Next audit available tomorrow.",
            "completed_audit": {
                "audit_date": str(todays_audit.audit_date),
                "completed_at": todays_audit.completed_at.isoformat() if todays_audit.completed_at else None,
                "occupancy_rate": todays_audit.occupancy_rate,
                "revenue": todays_audit.revenue,
            }
        }

    if business_date > today:
        # Business date ahead but no completed audit for today - edge case
        return {
            "can_run": False,
            "status": "date_mismatch",
            "business_date": str(business_date),
            "calendar_date": str(today),
            "message": f"Business date ({business_date}) is ahead of calendar. Use override endpoint to correct.",
        }

    # Normal case: ready to run
    return {
        "can_run": True,
        "status": "pending",
        "business_date": str(business_date),
        "calendar_date": str(today),
        "message": f"Night audit ready to run for {business_date}",
        "last_completed": {
            "audit_date": str(last_completed.audit_date) if last_completed else None,
            "completed_at": last_completed.completed_at.isoformat() if last_completed and last_completed.completed_at else None,
        } if last_completed else None
    }


@router.post("/night-audit", status_code=status.HTTP_201_CREATED)
async def run_night_audit(
    audit_date: Optional[date] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """
    Night Audit — Opera PMS-standard algorithm.

    Based on Oracle Hospitality Opera PMS night audit procedures.
    Executes in 4 phases with step-level procedure tracking.

    Phase 0: Safety Guards
      - One audit per business date (no double-posting)
      - Chronological order enforcement
      - Concurrent-run prevention (status="running" check)

    Phase 1: Pre-flight Blockers (informational — auto-resolved where possible)
      - Due-ins not checked in → marked no-show
      - Due-outs still checked in → auto-checkout
      - Pending room moves → must resolve manually
      - Open cashier sessions → must close
      - Unclosed POS outlets → must confirm closure
      - Expired authorization holds → flagged as warning

    Phase 2: End-of-Day Sequence (ordered steps)
      Step 1: Process No-Shows
      Step 2: Auto-Checkout Overdue Departures
      Step 3: Post Room & Tax Charges
      Step 4: Sync Room Statuses (occupied → dirty for housekeeping)
      Step 5: Return OOO/OOS Rooms (past return date)
      Step 6: Update AR Aging (mark overdue postings)
      Step 7: Flag Expired Authorization Holds
      Step 8: Calculate Revenue Day Totals
      Step 9: Calculate Statistics (ADR, RevPAR)

    Phase 3: Close Business Date
      - Auto-create sign-off chain (duty_manager → GM → finance)
      - Advance business date to next day
    """
    import json
    from datetime import timedelta

    target_date = audit_date or await get_business_date(session)
    procedure_log = []  # tracks each step's status and timing
    today = date.today()

    # ══════════════════════════════════════════════════════════════════
    # PRE-CHECK: Handle "already completed for today" scenario gracefully
    # ══════════════════════════════════════════════════════════════════
    #
    # When business_date > today, it typically means:
    # - Night audit for today was already completed successfully
    # - Business date was advanced to tomorrow as expected
    # - User is trying to run again on the same calendar day
    #
    # This is NOT an error - just inform the user audit is done for today.

    if target_date > today:
        # Check if night audit was completed for today's calendar date
        todays_audit = (await session.exec(
            select(NightAudit).where(
                NightAudit.audit_date == today,
                NightAudit.status == "completed"
            )
        )).first()

        if todays_audit:
            # Normal case: audit already done for today
            # Return HTTP 409 Conflict so frontend can easily detect this
            completed_time = todays_audit.completed_at.strftime("%H:%M") if todays_audit.completed_at else "earlier"
            raise HTTPException(
                status_code=409,  # Conflict - resource already exists
                detail={
                    "code": "AUDIT_ALREADY_COMPLETED",
                    "message": f"Night audit for {today} was already completed at {completed_time}.",
                    "audit_date": str(today),
                    "next_audit_date": str(target_date),
                    "hint": "Next night audit can be run tomorrow after the calendar date advances.",
                    "audit_id": todays_audit.id,
                    "completed_at": todays_audit.completed_at.isoformat() if todays_audit.completed_at else None,
                }
            )
        else:
            # Edge case: business date drifted without a completed audit record
            # This could happen due to manual override or data issues
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "BUSINESS_DATE_MISMATCH",
                    "message": f"Business date mismatch: business date ({target_date}) is ahead of calendar date ({today}), but no completed audit found.",
                    "business_date": str(target_date),
                    "calendar_date": str(today),
                    "hint": "Use POST /v1/config/override-business-date to correct the business date."
                }
            )

    def _log_step(step_name: str, status: str, detail: str = "", count: int = 0):
        procedure_log.append({
            "step": step_name,
            "status": status,
            "detail": detail,
            "count": count,
            "timestamp": datetime.utcnow().isoformat(),
        })

    # ══════════════════════════════════════════════════════════════════
    # PHASE 0 — SAFETY GUARDS
    # ══════════════════════════════════════════════════════════════════

    # Guard 1: Prevent double-run (completed audit for this date)
    existing = (await session.exec(
        select(NightAudit).where(NightAudit.audit_date == target_date)
    )).first()
    if existing and existing.status == "completed":
        completed_time = existing.completed_at.strftime("%H:%M") if existing.completed_at else "earlier"
        raise HTTPException(
            status_code=409,  # Conflict - resource already exists
            detail={
                "code": "AUDIT_ALREADY_COMPLETED",
                "message": f"Night audit for {target_date} was already completed at {completed_time}.",
                "audit_date": str(target_date),
                "audit_id": existing.id,
                "completed_at": existing.completed_at.isoformat() if existing.completed_at else None,
                "hint": "Night audit can only run once per business date."
            }
        )

    # Guard 2: Concurrent-run prevention (another audit is running)
    if existing and existing.status == "running":
        run_age = (datetime.utcnow() - existing.run_at).total_seconds() if existing.run_at else 0
        if run_age < 600:  # 10 minutes — assume still in progress
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "AUDIT_IN_PROGRESS",
                    "message": f"Night audit is already running for {target_date}.",
                    "audit_date": str(target_date),
                    "started_at": existing.run_at.isoformat() if existing.run_at else None,
                    "elapsed_seconds": int(run_age),
                    "hint": "Please wait for the current audit to complete."
                }
            )
        # Stale running record (>10 min) — mark as failed and allow retry
        existing.status = "failed"
        existing.errors = "Timed out after 10 minutes — marked failed for retry"
        existing.completed_at = datetime.utcnow()
        await session.flush()

    # Guard 3: Chronological order — ensure no future audit exists
    future_audit = (await session.exec(
        select(NightAudit).where(
            NightAudit.audit_date > target_date,
            NightAudit.status == "completed"
        )
    )).first()
    if future_audit:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot run audit for {target_date} — a later audit "
                   f"({future_audit.audit_date}) is already completed. "
                   f"Night audit must run in chronological order."
        )

    # If a previous failed run exists for this date, delete it
    if existing and existing.status == "failed":
        await session.delete(existing)
        await session.flush()

    _log_step("safety_guards", "passed", "All safety checks passed")

    # ── Create audit record with running status ────────────────────
    audit = NightAudit(
        audit_date=target_date,
        run_by=current_user.id,
        status="running"
    )
    session.add(audit)
    await session.flush()

    try:
        # ══════════════════════════════════════════════════════════════
        # PHASE 1 — PRE-FLIGHT CHECKS & DATA COLLECTION
        # ══════════════════════════════════════════════════════════════

        # --- Inventory snapshot ---
        all_rooms = (await session.exec(select(Room))).all()
        total_rooms = len([r for r in all_rooms if r.status != "out_of_order"])
        ooo_rooms = [r for r in all_rooms if r.status == "out_of_order"]
        available_rooms = total_rooms  # excludes OOO

        # --- In-house guests (staying through tonight) ---
        checked_in_bookings = (await session.exec(
            select(Booking).where(
                and_(
                    Booking.arrival_date <= target_date,
                    Booking.departure_date > target_date,
                    Booking.status == "checked_in"
                )
            )
        )).all()
        occupied = len(checked_in_bookings)

        # --- Today's movements ---
        arrivals_count = len((await session.exec(
            select(Booking).where(
                and_(
                    Booking.arrival_date == target_date,
                    Booking.status.in_(["booked", "confirmed", "checked_in"])
                )
            )
        )).all())

        departures_count = len((await session.exec(
            select(Booking).where(
                and_(
                    Booking.departure_date == target_date,
                    Booking.status == "checked_out"
                )
            )
        )).all())

        # --- Due-ins not checked in ---
        pending_arrivals = (await session.exec(
            select(Booking).where(
                and_(
                    Booking.arrival_date <= target_date,
                    Booking.status.in_(["booked", "confirmed", "pending"])
                )
            )
        )).all()

        # --- Due-outs still checked in ---
        overdue_departures = (await session.exec(
            select(Booking).where(
                and_(
                    Booking.departure_date <= target_date,
                    Booking.status == "checked_in"
                )
            )
        )).all()

        # Helper to label bookings for blocker details
        async def _booking_label(b):
            name = f"Booking #{b.id}"
            if b.guest_id:
                g = await session.get(Guest, b.guest_id)
                if g:
                    name = f"{g.first_name or ''} {g.last_name or ''}".strip() or name
            rm = None
            if b.room_id:
                r = await session.get(Room, b.room_id)
                if r:
                    rm = r.number
            return name, rm

        blockers = []

        # Blocker: Pending arrivals (informational — will auto-mark no-show)
        if pending_arrivals:
            pa_details = []
            for b in pending_arrivals[:20]:
                gn, rn = await _booking_label(b)
                pa_details.append({"id": b.id, "guest_name": gn, "arrival_date": str(b.arrival_date), "room": rn})
            blockers.append({
                "type": "pending_arrivals",
                "count": len(pending_arrivals),
                "auto_resolved": True,
                "message": f"{len(pending_arrivals)} booking(s) not checked in — marking as No-Show.",
                "bookings": pa_details,
            })

        # Blocker: Overdue departures (informational — will auto-checkout)
        if overdue_departures:
            od_details = []
            for b in overdue_departures[:20]:
                gn, rn = await _booking_label(b)
                od_details.append({"id": b.id, "guest_name": gn, "departure_date": str(b.departure_date), "room": rn})
            blockers.append({
                "type": "overdue_departures",
                "count": len(overdue_departures),
                "auto_resolved": True,
                "message": f"{len(overdue_departures)} guest(s) past checkout — auto-checking out.",
                "bookings": od_details,
            })

        # Blocker: Pending room moves (HARD blocker — B-04)
        from app.models.operations import ScheduledRoomMove, AuditSignOff
        pending_moves = (await session.exec(
            select(ScheduledRoomMove).where(
                ScheduledRoomMove.status == "scheduled",
                ScheduledRoomMove.scheduled_date <= target_date,
            )
        )).all()
        if pending_moves:
            move_details = []
            for m in pending_moves[:20]:
                from_room = await session.get(Room, m.from_room_id)
                to_room = await session.get(Room, m.to_room_id)
                move_details.append({
                    "id": m.id,
                    "booking_id": m.booking_id,
                    "from_room": from_room.number if from_room else str(m.from_room_id),
                    "to_room": to_room.number if to_room else str(m.to_room_id),
                    "reason": m.move_reason,
                })
            blockers.append({
                "type": "pending_room_moves",
                "count": len(pending_moves),
                "auto_resolved": False,
                "message": f"{len(pending_moves)} scheduled room move(s) not executed. Complete or cancel before audit.",
                "moves": move_details,
            })

        # Blocker: Open cashier sessions (HARD blocker — B-05)
        open_cashier_sessions = (await session.exec(
            select(CashierSession).where(CashierSession.status == "open")
        )).all()
        if open_cashier_sessions:
            cs_details = [{"id": cs.id, "staff_id": cs.staff_id, "workstation_id": cs.workstation_id} for cs in open_cashier_sessions]
            blockers.append({
                "type": "open_cashier_sessions",
                "count": len(open_cashier_sessions),
                "auto_resolved": False,
                "message": f"{len(open_cashier_sessions)} cashier session(s) still open. Close all before audit.",
                "sessions": cs_details,
            })

        # Blocker: POS closure (HARD blocker — B-19)
        from app.models.operations import PosOutlet, PosClosure
        active_outlets = (await session.exec(
            select(PosOutlet).where(PosOutlet.status == "active")
        )).all()
        if active_outlets:
            unconfirmed = []
            for outlet in active_outlets:
                closure = (await session.exec(
                    select(PosClosure).where(
                        PosClosure.pos_outlet_id == outlet.id,
                        PosClosure.audit_date == target_date,
                        PosClosure.close_status == "confirmed",
                    )
                )).first()
                if not closure:
                    unconfirmed.append({
                        "outlet_id": outlet.id,
                        "outlet_code": outlet.outlet_code,
                        "outlet_name": outlet.outlet_name,
                    })
            if unconfirmed:
                blockers.append({
                    "type": "unconfirmed_pos_closures",
                    "count": len(unconfirmed),
                    "auto_resolved": False,
                    "message": f"{len(unconfirmed)} POS outlet(s) not closed. Confirm closure before audit.",
                    "outlets": unconfirmed,
                })

        # Blocker: Expired authorization holds (WARNING — not a hard blocker)
        from app.models.operations import AuthorizationHold
        expiring_holds = (await session.exec(
            select(AuthorizationHold).where(
                AuthorizationHold.status == "authorized",
                AuthorizationHold.expires_at <= datetime.utcnow(),
            )
        )).all()
        if expiring_holds:
            hold_details = []
            for h in expiring_holds[:20]:
                hold_details.append({
                    "id": h.id,
                    "booking_id": h.booking_id,
                    "amount": h.hold_amount,
                    "card_last4": h.card_last4,
                    "expired_at": h.expires_at.isoformat() if h.expires_at else None,
                })
            blockers.append({
                "type": "expired_auth_holds",
                "count": len(expiring_holds),
                "auto_resolved": True,
                "severity": "warning",
                "message": f"{len(expiring_holds)} authorization hold(s) have expired. Will be flagged.",
                "holds": hold_details,
            })

        _log_step("pre_flight_checks", "completed",
                   f"{len(blockers)} blocker type(s) found", len(blockers))

        # ══════════════════════════════════════════════════════════════
        # PHASE 2 — END-OF-DAY SEQUENCE (ordered steps)
        # ══════════════════════════════════════════════════════════════

        # ── STEP 1: Process No-Shows ─────────────────────────────────
        no_show_count = 0
        for booking in pending_arrivals:
            booking.status = "no_show"
            if booking.room_id:
                room = await session.get(Room, booking.room_id)
                if room and room.occupancy_status == "occupied":
                    room.status = "dirty"
                    room.occupancy_status = "vacant"
                    room.cleaning_status = "dirty"
                booking.room_id = None
            no_show_count += 1

        _log_step("process_no_shows", "completed",
                   f"Marked {no_show_count} booking(s) as no-show", no_show_count)

        # ── STEP 2: Auto-Checkout Overdue Departures ─────────────────
        auto_checkout_count = 0
        for booking in overdue_departures:
            booking.status = "checked_out"
            booking.check_out_date = datetime.combine(booking.departure_date, datetime.min.time())
            if booking.room_id:
                room = await session.get(Room, booking.room_id)
                if room:
                    room.status = "dirty"
                    room.occupancy_status = "vacant"
                    room.cleaning_status = "dirty"
            history = ReservationHistory(
                reservation_id=booking.id,
                action="checked_out",
                changed_by=current_user.id,
                old_value="checked_in",
                new_value="checked_out (night audit auto-checkout)",
                created_at=datetime.utcnow()
            )
            session.add(history)
            auto_checkout_count += 1

        _log_step("auto_checkout_overdue", "completed",
                   f"Auto-checked-out {auto_checkout_count} overdue departure(s)", auto_checkout_count)

        # ── STEP 3: Verify Room Charges (charges now posted at check-in) ──────────────────────────
        # NOTE: Room charges are now posted at check-in (all nights at once).
        # Night audit only verifies charges exist and calculates revenue for reporting.
        # This removes the night audit dependency for billing consistency.
        room_charges_verified = 0
        room_charge_revenue = 0.0
        charge_errors = []
        bookings_missing_charges = []

        for booking in checked_in_bookings:
            try:
                # Find folio
                primary_folio = (await session.exec(
                    select(Folio).where(
                        and_(
                            Folio.booking_id == booking.id,
                            Folio.status == "open"
                        )
                    )
                )).first()

                if not primary_folio:
                    charge_errors.append(f"Booking #{booking.id}: no open folio found")
                    continue

                # Check for existing room charges
                existing_charges = (await session.exec(
                    select(FolioLineItem).where(
                        and_(
                            FolioLineItem.folio_id == primary_folio.id,
                            FolioLineItem.item_type == "room_charge",
                            FolioLineItem.is_voided == False,
                        )
                    )
                )).all()

                if not existing_charges:
                    # No charges found - flag for manual review
                    bookings_missing_charges.append(booking.id)
                    charge_errors.append(f"Booking #{booking.id}: no room charges posted (check-in may have failed)")
                    continue

                # Calculate revenue from existing charges
                for charge in existing_charges:
                    room_charge_revenue += (charge.amount or 0) + (charge.tax_amount or 0)

                room_charges_verified += 1

            except Exception as e:
                charge_errors.append(f"Booking #{booking.id}: {str(e)}")

        _log_step("verify_room_charges", "completed",
                   f"Verified {room_charges_verified} booking(s) with charges, revenue ₹{room_charge_revenue:,.2f}. "
                   f"Missing: {len(bookings_missing_charges)}, Errors: {len(charge_errors)}",
                   room_charges_verified)

        # Track for backward compatibility
        room_charges_posted = 0  # No longer posting charges at night audit

        # ── STEP 4: Sync Room Statuses (Opera: FO→HK status sync) ───
        # In Opera, all occupied rooms are set to "dirty" at night audit
        # so housekeeping knows which rooms need servicing next morning.
        rooms_set_dirty = 0
        for booking in checked_in_bookings:
            if booking.room_id:
                room = await session.get(Room, booking.room_id)
                if room and room.cleaning_status != "dirty":
                    room.cleaning_status = "dirty"
                    rooms_set_dirty += 1

        _log_step("sync_room_statuses", "completed",
                   f"Set {rooms_set_dirty} occupied room(s) to dirty for housekeeping", rooms_set_dirty)

        # ── STEP 5: Return OOO/OOS Rooms Past Return Date ────────────
        # Opera auto-returns rooms where ooo_expected_end has passed.
        rooms_returned_from_ooo = 0
        for room in ooo_rooms:
            if room.ooo_expected_end and room.ooo_expected_end.date() <= target_date:
                room.status = "available"
                room.occupancy_status = "vacant"
                room.cleaning_status = "dirty"  # needs inspection after maintenance
                room.ooo_reason = None
                room.ooo_category = None
                room.ooo_start_date = None
                room.ooo_expected_end = None
                rooms_returned_from_ooo += 1

        _log_step("return_ooo_rooms", "completed",
                   f"Returned {rooms_returned_from_ooo} room(s) from OOO/OOS to available",
                   rooms_returned_from_ooo)

        # ── STEP 6: Update AR Aging ──────────────────────────────────
        # Mark overdue AR postings (past due_date and still pending).
        ar_postings_aged = 0
        try:
            from app.models.ar import ARPosting
            overdue_postings = (await session.exec(
                select(ARPosting).where(
                    and_(
                        ARPosting.status == "pending",
                        ARPosting.due_date != None,
                        ARPosting.due_date < target_date,
                        ARPosting.posting_type == "charge",
                    )
                )
            )).all()
            for posting in overdue_postings:
                if posting.status != "overdue":
                    posting.status = "overdue"
                    ar_postings_aged += 1
        except Exception:
            pass  # AR module might not be initialized

        _log_step("update_ar_aging", "completed",
                   f"Aged {ar_postings_aged} AR posting(s) to overdue", ar_postings_aged)

        # ── STEP 7: Flag Expired Authorization Holds ─────────────────
        # Expired holds are marked so front desk can re-authorize or release.
        expired_auth_holds_count = 0
        for hold in expiring_holds:
            hold.status = "expired"
            hold.notes = (hold.notes or "") + f" | Auto-expired by night audit {target_date}"
            expired_auth_holds_count += 1

        _log_step("flag_expired_auth_holds", "completed",
                   f"Flagged {expired_auth_holds_count} expired authorization hold(s)",
                   expired_auth_holds_count)

        # ── STEP 8: Calculate Revenue Day Totals ─────────────────────
        # Sum all charges and payments posted today (not just room charges).
        all_day_charges = (await session.exec(
            select(FolioLineItem).where(
                FolioLineItem.is_voided == False,
            )
        )).all()
        # Filter to charges posted on audit date
        day_charges = [c for c in all_day_charges
                       if c.posted_at and c.posted_at.date() == target_date]

        total_room_revenue = sum(c.amount for c in day_charges if c.item_type == "room_charge" and c.amount > 0)
        total_fnb_revenue = sum(c.amount for c in day_charges if c.item_type in ("restaurant", "minibar", "bar") and c.amount > 0)
        total_other_revenue = sum(c.amount for c in day_charges
                                  if c.item_type not in ("room_charge", "restaurant", "minibar", "bar", "payment")
                                  and c.amount > 0)
        total_tax_collected = sum((c.tax_amount or 0) for c in day_charges if c.amount > 0)

        # Payments received today
        day_payments = (await session.exec(select(Payment))).all()
        day_payments = [p for p in day_payments if p.created_at and p.created_at.date() == target_date]
        total_payments_received = sum(p.amount for p in day_payments)

        _log_step("calculate_revenue_totals", "completed",
                   f"Room: ₹{total_room_revenue:,.2f}, F&B: ₹{total_fnb_revenue:,.2f}, "
                   f"Other: ₹{total_other_revenue:,.2f}, Tax: ₹{total_tax_collected:,.2f}, "
                   f"Payments: ₹{total_payments_received:,.2f}")

        # ── STEP 9: Calculate Statistics (ADR, RevPAR) ───────────────
        # ADR = Total Room Revenue / Number of Rooms Sold
        # RevPAR = Total Room Revenue / Total Available Rooms
        # (Industry standard: Opera PMS V5 / STR Global definitions)
        rooms_sold = occupied  # rooms occupied tonight
        adr = round(total_room_revenue / rooms_sold, 2) if rooms_sold > 0 else 0.0
        revpar = round(total_room_revenue / available_rooms, 2) if available_rooms > 0 else 0.0

        _log_step("calculate_statistics", "completed",
                   f"ADR: ₹{adr:,.2f}, RevPAR: ₹{revpar:,.2f}, "
                   f"Occupancy: {round(occupied / available_rooms * 100, 1) if available_rooms > 0 else 0}%")

        # ══════════════════════════════════════════════════════════════
        # FINALIZE AUDIT RECORD
        # ══════════════════════════════════════════════════════════════

        audit.occupancy_rate = round((occupied / available_rooms * 100), 2) if available_rooms > 0 else 0
        audit.revenue = round(total_room_revenue + total_fnb_revenue + total_other_revenue, 2)
        audit.arrivals = arrivals_count
        audit.departures = departures_count
        audit.in_house = occupied
        audit.no_shows = no_show_count
        audit.auto_checkouts = auto_checkout_count
        audit.room_charges_posted = room_charges_posted
        audit.room_charge_revenue = round(room_charge_revenue, 2)
        # Opera PMS statistics
        audit.adr = adr
        audit.revpar = revpar
        audit.total_room_revenue = round(total_room_revenue, 2)
        audit.total_fnb_revenue = round(total_fnb_revenue, 2)
        audit.total_other_revenue = round(total_other_revenue, 2)
        audit.total_tax_collected = round(total_tax_collected, 2)
        audit.total_payments_received = round(total_payments_received, 2)
        audit.rooms_returned_from_ooo = rooms_returned_from_ooo
        audit.expired_auth_holds_count = expired_auth_holds_count
        audit.ar_postings_aged = ar_postings_aged
        audit.rooms_set_dirty = rooms_set_dirty
        audit.status = "completed"
        audit.completed_at = datetime.utcnow()

        notes_parts = []
        if no_show_count:
            notes_parts.append(f"No-shows: {no_show_count}")
        if auto_checkout_count:
            notes_parts.append(f"Auto-checkouts: {auto_checkout_count}")
        notes_parts.append(f"Room charges: {room_charges_posted}")
        if rooms_set_dirty:
            notes_parts.append(f"Rooms→dirty: {rooms_set_dirty}")
        if rooms_returned_from_ooo:
            notes_parts.append(f"OOO returned: {rooms_returned_from_ooo}")
        if ar_postings_aged:
            notes_parts.append(f"AR aged: {ar_postings_aged}")
        if expired_auth_holds_count:
            notes_parts.append(f"Auth holds expired: {expired_auth_holds_count}")
        if charge_errors:
            notes_parts.append(f"Errors: {len(charge_errors)}")
            audit.errors = "; ".join(charge_errors[:10])
        audit.notes = ", ".join(notes_parts)

        _log_step("finalize_audit_record", "completed", "Audit record populated")
        audit.procedure_log = json.dumps(procedure_log)

        await session.commit()
        await session.refresh(audit)

        # ══════════════════════════════════════════════════════════════
        # PHASE 3 — CLOSE BUSINESS DATE
        # ══════════════════════════════════════════════════════════════

        # Auto-create sign-off chain (B-18)
        existing_signoffs = (await session.exec(
            select(AuditSignOff).where(AuditSignOff.audit_id == audit.id)
        )).first()
        if not existing_signoffs:
            for role, order in [("duty_manager", 1), ("general_manager", 2), ("finance_controller", 3)]:
                session.add(AuditSignOff(audit_id=audit.id, role=role, sign_order=order))
            await session.commit()

        # Advance business date
        next_business_date = target_date + timedelta(days=1)
        await advance_business_date(session, next_business_date, current_user.id)

        _log_step("close_business_date", "completed",
                   f"Business date advanced to {next_business_date}")

        return {
            "id": audit.id,
            "audit_date": str(audit.audit_date),
            "status": audit.status,
            # Occupancy
            "occupancy_rate": audit.occupancy_rate,
            "in_house": audit.in_house,
            "total_rooms": total_rooms,
            "ooo_rooms": len(ooo_rooms),
            # Movements
            "arrivals": audit.arrivals,
            "departures": audit.departures,
            "no_shows": audit.no_shows,
            "auto_checkouts": auto_checkout_count,
            # Room charges
            "room_charges_posted": room_charges_posted,
            "room_charge_revenue": round(room_charge_revenue, 2),
            # Revenue totals (Opera-style)
            "revenue": {
                "room": round(total_room_revenue, 2),
                "fnb": round(total_fnb_revenue, 2),
                "other": round(total_other_revenue, 2),
                "tax": round(total_tax_collected, 2),
                "total": round(total_room_revenue + total_fnb_revenue + total_other_revenue, 2),
                "payments_received": round(total_payments_received, 2),
            },
            # Statistics (Opera PMS standard)
            "statistics": {
                "adr": adr,
                "revpar": revpar,
            },
            # Housekeeping & maintenance
            "rooms_set_dirty": rooms_set_dirty,
            "rooms_returned_from_ooo": rooms_returned_from_ooo,
            # Financial
            "expired_auth_holds": expired_auth_holds_count,
            "ar_postings_aged": ar_postings_aged,
            # Blockers & errors
            "blockers_resolved": blockers,
            "charge_errors": charge_errors[:10] if charge_errors else [],
            "notes": audit.notes,
            # Procedure tracking
            "procedure_log": procedure_log,
            # Next date
            "new_business_date": str(next_business_date),
        }

    except HTTPException:
        raise  # Re-raise HTTP exceptions as-is
    except Exception as e:
        # If the audit fails mid-run, mark it as failed (not "running" forever)
        audit.status = "failed"
        audit.errors = str(e)[:500]
        audit.completed_at = datetime.utcnow()
        audit.procedure_log = json.dumps(procedure_log)
        await session.commit()
        raise HTTPException(
            status_code=500,
            detail=f"Night audit failed at step {procedure_log[-1]['step'] if procedure_log else 'unknown'}: {str(e)}"
        )


@router.get("/night-audit/{audit_date}/report")
async def get_night_audit_report(
    audit_date: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Post-audit report — occupancy, revenue, arrivals, departures, cashier summary, no-shows."""
    # Find the audit record
    result = await session.exec(
        select(NightAudit).where(NightAudit.audit_date == audit_date)
    )
    audit = result.first()
    if not audit:
        raise HTTPException(404, "No night audit found for this date")

    # Room statistics
    total_rooms = (await session.exec(select(Room))).all()
    occupied = [r for r in total_rooms if r.occupancy_status == "occupied"]
    vacant = [r for r in total_rooms if r.occupancy_status in ("vacant", None)]
    ooo_rooms = [r for r in total_rooms if r.status == "out_of_order"]

    # Revenue from folio charges on audit date
    charges = (await session.exec(
        select(FolioLineItem).where(
            FolioLineItem.is_voided == False,
        )
    )).all()
    day_charges = [c for c in charges if c.posted_at and str(c.posted_at.date()) == audit_date]
    room_revenue = sum(c.amount for c in day_charges if c.item_type == "room_charge")
    fnb_revenue = sum(c.amount for c in day_charges if c.item_type in ("restaurant", "minibar"))
    other_revenue = sum(c.amount for c in day_charges if c.item_type not in ("room_charge", "restaurant", "minibar"))
    total_tax = sum((c.tax_amount or 0) for c in day_charges)

    # Payments received on audit date
    payments = (await session.exec(select(Payment))).all()
    day_payments = [p for p in payments if p.created_at and str(p.created_at.date()) == audit_date]
    payment_by_method = {}
    for p in day_payments:
        method = p.method or "unknown"
        payment_by_method[method] = round(payment_by_method.get(method, 0) + p.amount, 2)

    # Cashier sessions for the date
    cashier_sessions = (await session.exec(
        select(CashierSession).where(CashierSession.session_date == audit_date)
    )).all()
    cashier_summary = []
    for cs in cashier_sessions:
        cashier_summary.append({
            "id": cs.id,
            "staff_id": cs.staff_id,
            "status": cs.status,
            "opening_balance": cs.opening_balance,
            "closing_balance": cs.closing_balance,
            "expected_balance": cs.expected_balance,
            "variance": cs.variance,
            "transaction_count": cs.transaction_count,
        })

    # Bookings that arrived/departed on this date
    all_bookings = (await session.exec(select(Booking))).all()
    arrivals = [b for b in all_bookings if str(b.arrival_date) == audit_date and b.status in ("checked_in",)]
    departures = [b for b in all_bookings if b.check_out_date and str(b.check_out_date.date()) == audit_date]
    no_shows = [b for b in all_bookings if str(b.arrival_date) == audit_date and b.status == "no_show"]

    # Parse procedure log if available
    import json as json_lib
    proc_log = None
    if audit.procedure_log:
        try:
            proc_log = json_lib.loads(audit.procedure_log)
        except Exception:
            proc_log = None

    return {
        "audit_date": audit_date,
        "audit_record": {
            "id": audit.id,
            "status": audit.status,
            "run_at": audit.run_at.isoformat() if audit.run_at else None,
            "completed_at": audit.completed_at.isoformat() if audit.completed_at else None,
        },
        "occupancy": {
            "total_rooms": len(total_rooms),
            "occupied": len(occupied),
            "vacant": len(vacant),
            "out_of_order": len(ooo_rooms),
            "occupancy_rate": round(len(occupied) / max(len(total_rooms) - len(ooo_rooms), 1) * 100, 1),
        },
        "revenue": {
            "room_revenue": round(room_revenue, 2),
            "fnb_revenue": round(fnb_revenue, 2),
            "other_revenue": round(other_revenue, 2),
            "total_revenue": round(room_revenue + fnb_revenue + other_revenue, 2),
            "total_tax_collected": round(total_tax, 2),
        },
        "payments": {
            "by_method": payment_by_method,
            "total_collected": round(sum(payment_by_method.values()), 2),
        },
        "movements": {
            "arrivals": len(arrivals),
            "departures": len(departures),
            "no_shows": len(no_shows),
            "in_house": audit.in_house or 0,
        },
        "statistics": {
            "adr": audit.adr or 0.0,
            "revpar": audit.revpar or 0.0,
            "rooms_set_dirty": audit.rooms_set_dirty or 0,
            "rooms_returned_from_ooo": audit.rooms_returned_from_ooo or 0,
            "expired_auth_holds": audit.expired_auth_holds_count or 0,
            "ar_postings_aged": audit.ar_postings_aged or 0,
        },
        "cashier_sessions": cashier_summary,
        "procedure_log": proc_log,
    }


@router.get("/guest-bill/{booking_id}")
async def get_guest_bill(
    booking_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Guest-facing bill summary — shows all charges, payments, and balance for a booking."""
    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    guest = await session.get(Guest, booking.guest_id) if booking.guest_id else None

    # Get all folios
    folios = (await session.exec(
        select(Folio).where(Folio.booking_id == booking_id)
    )).all()

    folio_details = []
    total_charges = 0.0
    total_tax = 0.0
    total_payments = 0.0

    for f in folios:
        items = (await session.exec(
            select(FolioLineItem).where(
                FolioLineItem.folio_id == f.id,
                FolioLineItem.is_voided == False,
            ).order_by(FolioLineItem.posted_at)
        )).all()

        payments = (await session.exec(
            select(Payment).where(Payment.folio_id == f.id)
        )).all()

        folio_charges = []
        for item in items:
            folio_charges.append({
                "date": item.posted_at.strftime("%Y-%m-%d") if item.posted_at else None,
                "description": item.description,
                "category": item.item_type,
                "amount": item.amount,
                "tax": item.tax_amount or 0,
                "total": round(item.amount + (item.tax_amount or 0), 2),
            })
            total_charges += item.amount
            total_tax += (item.tax_amount or 0)

        folio_payments = []
        for p in payments:
            folio_payments.append({
                "date": p.created_at.strftime("%Y-%m-%d") if p.created_at else None,
                "method": p.method,
                "amount": p.amount,
                "reference": p.transaction_id,
            })
            total_payments += p.amount

        folio_details.append({
            "folio_id": f.id,
            "window": f.window_label,
            "type": f.folio_type,
            "status": f.status,
            "invoice_number": f.invoice_number,
            "charges": folio_charges,
            "payments": folio_payments,
            "balance": f.balance,
        })

    # Use stored values from booking for consistency across the app
    # Booking model stores: base_price, taxes, service_fee, total_price (all calculated at creation)
    booking_total_price = booking.total_price or 0
    booking_room_rate = booking.base_price or 0
    booking_tax_stored = booking.taxes or 0
    booking_service_fee = 0.0  # Service fee removed
    booking_nights = booking.nights or 1

    # If base_price is not stored but total_price exists, reverse-calculate the breakdown
    # This handles older bookings that only stored total_price
    if booking_room_rate == 0 and booking_total_price > 0:
        # Total = Base + Tax (GST%)
        # Total = Base × (1 + GST%)
        # For 12% GST: Total = Base × 1.12, so Base = Total / 1.12
        # For 18% GST: Total = Base × 1.18, so Base = Total / 1.18
        # We need to guess which slab - use 12% as default for lower amounts
        estimated_base_per_night = booking_total_price / booking_nights / 1.12
        if estimated_base_per_night > 7500:
            # Recalculate with 18% GST
            gst_rate = 0.18
            divisor = 1.18  # 1 + 0.18
        else:
            gst_rate = 0.12
            divisor = 1.12  # 1 + 0.12

        booking_room_rate = round(booking_total_price / divisor, 2)
        booking_tax_stored = round(booking_room_rate * gst_rate, 2)

    # If still no pricing data, try to get from room type
    if booking_room_rate == 0 and booking_total_price == 0 and booking.room_type_id:
        from app.models.inventory import RoomType
        room_type = await session.get(RoomType, booking.room_type_id)
        if room_type and room_type.base_price is not None and room_type.base_price > 0:
            rt_price = room_type.base_price
            booking_room_rate = rt_price * booking_nights
            gst_rate = 0.18 if rt_price > 7500 else 0.12
            booking_tax_stored = round(booking_room_rate * gst_rate, 2)
            booking_total_price = round(booking_room_rate + booking_tax_stored, 2)

    # Final fallback: if booking is paid and has deposit_amount, use that as total
    if booking_room_rate == 0 and booking_total_price == 0:
        deposit = booking.deposit_amount or 0
        if deposit > 0:
            booking_total_price = deposit
            # Reverse calculate the breakdown from deposit (which equals total when paid)
            estimated_base_per_night = deposit / booking_nights / 1.12
            if estimated_base_per_night > 7500:
                gst_rate = 0.18
                divisor = 1.18
            else:
                gst_rate = 0.12
                divisor = 1.12
            booking_room_rate = round(deposit / divisor, 2)
            booking_tax_stored = round(booking_room_rate * gst_rate, 2)

    # Additional fallback: Get price from Room if assigned
    if booking_room_rate == 0 and booking_total_price == 0 and booking.room_id:
        from app.models.inventory import Room
        room_obj = await session.get(Room, booking.room_id)
        if room_obj and room_obj.price_per_night and room_obj.price_per_night > 0:
            rt_price = room_obj.price_per_night
            booking_room_rate = rt_price * booking_nights
            gst_rate = 0.18 if rt_price > 7500 else 0.12
            booking_tax_stored = round(booking_room_rate * gst_rate, 2)
            booking_total_price = round(booking_room_rate + booking_tax_stored, 2)

    # Ultimate fallback: Query any room of the same type for price
    if booking_room_rate == 0 and booking_total_price == 0 and booking.room_type_id:
        from app.models.inventory import Room as RoomModel
        # Get any room of this type that has a price
        rooms_of_type = (await session.exec(
            select(RoomModel).where(
                RoomModel.room_type_id == booking.room_type_id,
                RoomModel.price_per_night > 0
            ).limit(1)
        )).all()
        if rooms_of_type and rooms_of_type[0].price_per_night:
            rt_price = rooms_of_type[0].price_per_night
            booking_room_rate = rt_price * booking_nights
            gst_rate = 0.18 if rt_price > 7500 else 0.12
            booking_tax_stored = round(booking_room_rate * gst_rate, 2)
            booking_total_price = round(booking_room_rate + booking_tax_stored, 2)

    # Calculate per-night rate for display purposes
    per_night_rate = booking_room_rate / booking_nights if booking_nights > 0 and booking_room_rate > 0 else 0

    # Calculate GST rate - prefer actual rate from stored values for accuracy
    if booking.taxes and booking.base_price and booking.base_price > 0:
        # Derive actual GST percentage from stored values
        actual_gst_pct = round((booking.taxes / booking.base_price) * 100)
        # Use if it's a valid Indian GST rate (12% or 18%)
        if actual_gst_pct in [12, 18]:
            gst_rate = actual_gst_pct / 100
        else:
            gst_rate = 0.18 if per_night_rate > 7500 else 0.12
    else:
        gst_rate = 0.18 if per_night_rate > 7500 else 0.12

    # If no charges posted yet, show booking amount as expected charge
    if total_charges == 0 and (booking_room_rate > 0 or booking_total_price > 0):
        # Use stored values from booking (no recalculation)
        total_charges = booking_room_rate
        total_tax = booking_tax_stored

        # Add booking room charge to show in UI
        folio_details.append({
            "folio_id": 0,
            "window": "Room Charges",
            "type": "room",
            "status": "pending",
            "invoice_number": None,
            "charges": [{
                "date": str(booking.arrival_date),
                "description": f"Room Charges ({booking_nights} night{'s' if booking_nights > 1 else ''} @ ₹{per_night_rate:.0f}/night)",
                "category": "room",
                "amount": booking_room_rate,
                "tax": booking_tax_stored,
                "service_fee": 0.0,
                "total": booking_total_price,
            }],
            "payments": [],
            "balance": booking_total_price,
        })

    # Get room number if assigned
    room_number = None
    if booking.room_id:
        from app.models.inventory import Room
        room = await session.get(Room, booking.room_id)
        if room:
            room_number = room.number

    # For SUMMARY section, prioritize stored booking values for consistency with booking drawer
    # The folio_details still shows actual posted charges, but summary should match booking totals

    # Use booking's stored total_price as the authoritative grand total
    grand_total = booking.total_price if booking.total_price and booking.total_price > 0 else round(total_charges + total_tax, 2)

    # Use booking's stored values for summary breakdown when available
    summary_room_charges = booking.base_price if booking.base_price and booking.base_price > 0 else total_charges
    summary_tax = booking.taxes if booking.taxes and booking.taxes > 0 else total_tax
    summary_service_fee = 0.0  # Service fee removed

    # Always check deposit_amount for payments (not just when payment_status is "paid")
    # This ensures partial payments are also shown
    if total_payments == 0:
        deposit = booking.deposit_amount or 0
        if deposit > 0:
            total_payments = deposit
        elif booking.payment_status == "paid" and grand_total > 0:
            # If marked as paid but no deposit recorded, assume fully paid
            total_payments = grand_total

    # Use booking's stored balance_due if available, otherwise calculate
    balance_due = booking.balance_due if booking.balance_due is not None else round(grand_total - total_payments, 2)
    # Ensure balance_due is not negative
    if balance_due < 0:
        balance_due = 0.0

    return {
        "booking_id": booking.id,
        "booking_number": booking.booking_number,
        "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Guest",
        "room_number": room_number,
        "arrival_date": str(booking.arrival_date),
        "departure_date": str(booking.departure_date),
        "nights": booking.nights,
        "room_rate": per_night_rate,
        "gst_rate": gst_rate,
        "gst_percent": int(gst_rate * 100),
        "folios": folio_details,
        "summary": {
            "total_charges": round(summary_room_charges, 2),
            "total_tax": round(summary_tax, 2),
            "service_fee": round(summary_service_fee, 2),
            "grand_total": round(grand_total, 2),
            "total_payments": round(total_payments, 2),
            "balance_due": round(balance_due, 2),
        },
    }

