"""
Billing Service - Wrapper around billing_engine for async DB operations

This service wraps the billing_engine (single source of truth) and adds
async database operations for folios, bookings, and room lookups.

NOTE: All calculation logic is in billing_engine.py. This module only
handles DB interactions and delegates to billing_engine for calculations.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List
from decimal import Decimal, ROUND_HALF_UP

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.reservations import Booking
from app.models.inventory import Room, RoomType
from app.models.operations import Folio, FolioLineItem

# Import billing_engine as the SINGLE SOURCE OF TRUTH for calculations
from app.services.billing_engine import (
    calculate_stay_charges,
    calculate_tax,
    calculate_extension,
    calculate_early_checkout,
    calculate_nights,
    get_tax_rate,
    TAX_THRESHOLD,
    TAX_RATE_LOW,
    TAX_RATE_HIGH,
    MINIMUM_NIGHTS,
    StayCharges,
    TaxBreakdown,
)

logger = logging.getLogger(__name__)


# ============== CONSTANTS (imported from billing_engine) ==============

# Re-export for backward compatibility
ROOM_TAX_THRESHOLD = float(TAX_THRESHOLD)
ROOM_TAX_RATE_LOW = float(TAX_RATE_LOW)
ROOM_TAX_RATE_HIGH = float(TAX_RATE_HIGH)
MINIMUM_BILLABLE_NIGHTS = MINIMUM_NIGHTS


# ============== TAX CALCULATIONS (delegated to billing_engine) ==============

def get_gst_rate(per_night_rate: float) -> float:
    """
    Get GST rate based on per-night room rate.
    DELEGATES TO: billing_engine.get_tax_rate()
    """
    rate, _ = get_tax_rate(Decimal(str(per_night_rate)))
    return float(rate)


def calculate_tax_components(base_amount: float, per_night_rate: float) -> Dict[str, float]:
    """
    Calculate GST components (CGST + SGST) for a given base amount.
    DELEGATES TO: billing_engine.calculate_tax()
    """
    tax = calculate_tax(base_amount, per_night_rate)
    return {
        "tax_rate": float(tax.tax_rate),
        "tax_rate_pct": tax.tax_rate_percent,
        "tax_amount": float(tax.tax_amount),
        "cgst": float(tax.cgst),
        "sgst": float(tax.sgst),
        "cgst_rate": float(tax.cgst_rate),
        "sgst_rate": float(tax.sgst_rate),
    }


# ============== NIGHT CALCULATIONS ==============

def calculate_billable_nights(
    check_in_date: date,
    check_out_date: date,
    original_nights: int = 0
) -> Tuple[int, bool]:
    """
    Calculate billable nights for a stay.

    Rules:
    - Minimum 1 night for any stay (even same-day checkout)
    - Early checkout: charge only for actual nights
    - Late checkout: additional charges handled separately

    Args:
        check_in_date: Date of check-in
        check_out_date: Date of check-out
        original_nights: Originally booked nights (for early checkout detection)

    Returns:
        Tuple of (billable_nights, is_early_checkout)
    """
    raw_nights = (check_out_date - check_in_date).days

    # Minimum 1 night for any stay
    billable_nights = max(MINIMUM_BILLABLE_NIGHTS, raw_nights)

    # Detect early checkout
    is_early_checkout = original_nights > 0 and billable_nights < original_nights

    logger.debug(
        f"Billable nights: raw={raw_nights}, billable={billable_nights}, "
        f"original={original_nights}, early_checkout={is_early_checkout}"
    )

    return billable_nights, is_early_checkout


# ============== ROOM CHARGE CALCULATIONS (delegated to billing_engine) ==============

def calculate_room_charges(
    per_night_rate: float,
    nights: int,
    include_tax: bool = True
) -> Dict[str, float]:
    """
    Calculate room charges for a stay.
    DELEGATES TO: billing_engine.calculate_stay_charges()

    Args:
        per_night_rate: Rate per night (before tax)
        nights: Number of nights
        include_tax: Whether to calculate tax

    Returns:
        Dict with base_amount, tax details, and total
    """
    charges = calculate_stay_charges(per_night_rate, nights)

    result = {
        "per_night_rate": float(charges.nightly_rate),
        "nights": charges.nights,
        "base_amount": float(charges.base_amount),
        "tax_amount": float(charges.tax_amount) if include_tax else 0,
        "cgst": float(charges.cgst) if include_tax else 0,
        "sgst": float(charges.sgst) if include_tax else 0,
        "tax_rate": float(charges.tax_rate) if include_tax else 0,
        "total_amount": float(charges.total_amount) if include_tax else float(charges.base_amount),
    }

    return result


async def get_effective_nightly_rate(
    session: AsyncSession,
    booking: Booking,
    room: Optional[Room] = None,
    raise_if_zero: bool = False
) -> float:
    """
    Get the effective nightly rate for a booking.
    PRIORITY: booking.nightly_rate (stored at booking time) > room_type.base_price > calculated

    Args:
        session: Database session
        booking: Booking object
        room: Optional Room object (fetched if not provided)
        raise_if_zero: If True, raises ValueError if rate cannot be determined

    Returns:
        Effective per-night rate (never 0 unless raise_if_zero=False and no rate found)
    """
    rate = 0.0

    # PRIORITY 1: Use stored nightly_rate (set at booking creation for consistency)
    if booking.nightly_rate and booking.nightly_rate > 0:
        rate = float(booking.nightly_rate)
        logger.debug(f"Booking {booking.id}: nightly rate from stored nightly_rate = {rate}")
        return rate

    # PRIORITY 2: Use room type base price (direct per-night rate)
    room_type_id = booking.room_type_id
    if not room_type_id and booking.room_id:
        if not room:
            room = await session.get(Room, booking.room_id)
        if room:
            room_type_id = room.room_type_id

    if room_type_id:
        room_type = await session.get(RoomType, room_type_id)
        if room_type and room_type.base_price and room_type.base_price > 0:
            rate = float(room_type.base_price)
            logger.debug(f"Booking {booking.id}: nightly rate from room_type = {rate}")
            return rate

    # PRIORITY 3: Use booking's base_price divided by nights
    # Note: base_price is TOTAL for all nights, so divide by nights to get per-night
    if booking.base_price and booking.base_price > 0:
        nights = max(1, booking.nights or 1)
        rate = round(booking.base_price / nights, 2)
        logger.debug(f"Booking {booking.id}: nightly rate from base_price = {rate} (base={booking.base_price}, nights={nights})")
        if rate > 0:
            return rate

    # PRIORITY 4: Use booking's total_price divided by nights (reverse tax using stored tax_rate)
    if booking.total_price and booking.total_price > 0:
        nights = max(1, booking.nights or 1)
        # Use stored tax_rate if available, else default to 12%
        tax_rate = booking.tax_rate if booking.tax_rate and booking.tax_rate > 0 else 0.12
        base_estimate = booking.total_price / (1 + tax_rate)
        rate = round(base_estimate / nights, 2)
        logger.debug(f"Booking {booking.id}: nightly rate from total_price = {rate}")
        if rate > 0:
            return rate

    # No rate found
    logger.warning(
        f"Could not determine nightly rate for booking {booking.id}: "
        f"nightly_rate={booking.nightly_rate}, base_price={booking.base_price}, "
        f"total_price={booking.total_price}, room_type_id={booking.room_type_id}"
    )

    if raise_if_zero:
        raise ValueError(f"Cannot determine nightly rate for booking {booking.id}")

    return 0


# ============== BOOKING PRICING ==============

async def calculate_booking_price(
    session: AsyncSession,
    room_type_id: int,
    check_in: date,
    check_out: date,
    override_rate: Optional[float] = None
) -> Dict[str, float]:
    """
    Calculate total price for a booking.
    Uses dynamic pricing if available, otherwise base room type price.

    Args:
        session: Database session
        room_type_id: Room type ID
        check_in: Check-in date
        check_out: Check-out date
        override_rate: Optional override for per-night rate

    Returns:
        Dict with pricing breakdown
    """
    nights = max(MINIMUM_BILLABLE_NIGHTS, (check_out - check_in).days)

    # Get per-night rate
    if override_rate and override_rate > 0:
        per_night_rate = override_rate
    else:
        room_type = await session.get(RoomType, room_type_id)
        if room_type and room_type.base_price:
            per_night_rate = float(room_type.base_price)
        else:
            logger.warning(f"Room type {room_type_id} has no base price")
            per_night_rate = 0

    # Try to use dynamic pricing service
    try:
        from app.services.pricing_service import calculate_effective_price
        room_type = await session.get(RoomType, room_type_id)
        if room_type:
            effective_price, _ = await calculate_effective_price(
                session=session,
                room_type_name=room_type.name,
                room_type_id=room_type_id,
                base_price=per_night_rate,
                check_in=check_in,
                check_out=check_out,
            )
            per_night_rate = effective_price
    except Exception as e:
        logger.debug(f"Dynamic pricing not available: {e}")

    return calculate_room_charges(per_night_rate, nights, include_tax=True)


# ============== EARLY CHECKOUT BILLING ==============

async def calculate_early_checkout_adjustment(
    session: AsyncSession,
    booking: Booking,
    actual_checkout_date: date
) -> Dict[str, Any]:
    """
    Calculate billing adjustment for early checkout.

    Args:
        session: Database session
        booking: Original booking
        actual_checkout_date: Actual checkout date

    Returns:
        Dict with adjustment details including new charges and refund amount
    """
    check_in_date = (
        booking.check_in_date.date()
        if booking.check_in_date
        else booking.arrival_date
    )

    original_nights = booking.nights or (booking.departure_date - booking.arrival_date).days
    billable_nights, is_early = calculate_billable_nights(
        check_in_date,
        actual_checkout_date,
        original_nights
    )

    # Get effective nightly rate
    nightly_rate = await get_effective_nightly_rate(session, booking)

    # Calculate new charges
    new_charges = calculate_room_charges(nightly_rate, billable_nights)

    # Calculate original charges
    original_charges = calculate_room_charges(nightly_rate, original_nights)

    # Calculate adjustment
    adjustment = {
        "is_early_checkout": is_early,
        "original_nights": original_nights,
        "billable_nights": billable_nights,
        "nights_reduced": original_nights - billable_nights,
        "nightly_rate": nightly_rate,
        "original_base": original_charges["base_amount"],
        "original_tax": original_charges["tax_amount"],
        "original_total": original_charges["total_amount"],
        "new_base": new_charges["base_amount"],
        "new_tax": new_charges["tax_amount"],
        "new_total": new_charges["total_amount"],
        "refund_amount": round(
            original_charges["total_amount"] - new_charges["total_amount"], 2
        ),
        "tax_details": {
            "cgst": new_charges["cgst"],
            "sgst": new_charges["sgst"],
            "rate": new_charges["tax_rate"],
        }
    }

    logger.info(
        f"Early checkout adjustment for booking {booking.id}: "
        f"{original_nights} -> {billable_nights} nights, "
        f"refund: {adjustment['refund_amount']}"
    )

    return adjustment


# ============== FOLIO OPERATIONS ==============

async def create_room_charge_line_item(
    folio_id: int,
    per_night_rate: float,
    nights: int,
    posted_by: int,
    description: Optional[str] = None,
    charge_date: Optional[date] = None
) -> Tuple[FolioLineItem, FolioLineItem]:
    """
    Create room charge and tax line items for folio posting.

    Args:
        folio_id: Target folio ID
        per_night_rate: Rate per night
        nights: Number of nights
        posted_by: User ID posting the charge
        description: Optional custom description
        charge_date: Optional date for the charge

    Returns:
        Tuple of (room_charge_item, tax_item)
    """
    charges = calculate_room_charges(per_night_rate, nights)

    if not description:
        # Use date-based description if charge_date provided (for duplicate detection)
        if charge_date:
            charge_date_str = charge_date.isoformat() if hasattr(charge_date, 'isoformat') else str(charge_date)
            description = f"Room charge – {charge_date_str} @ ₹{per_night_rate:.2f}"
        else:
            description = f"Room charges - {nights} night(s) @ ₹{per_night_rate:.2f}/night"

    # Create room charge line item
    room_charge = FolioLineItem(
        folio_id=folio_id,
        item_type="room_charge",
        description=description,
        quantity=nights,
        unit_price=round(per_night_rate, 2),
        amount=charges["base_amount"],
        tax_rate_pct=charges["tax_rate"] * 100,
        tax_amount=charges["tax_amount"],
        tax_component_1_name="CGST",
        tax_component_1_amount=charges["cgst"],
        tax_component_2_name="SGST",
        tax_component_2_amount=charges["sgst"],
        posted_by=posted_by,
    )

    # Create separate tax line item
    tax_description = f"GST @ {charges['tax_rate'] * 100:.1f}% on room charges"
    if charge_date:
        tax_description = f"GST @ {charges['tax_rate'] * 100:.1f}% - {charge_date}"

    tax_item = FolioLineItem(
        folio_id=folio_id,
        item_type="tax",
        description=tax_description,
        quantity=1,
        unit_price=charges["tax_amount"],
        amount=charges["tax_amount"],
        tax_amount=charges["tax_amount"],
        tax_component_1_name="CGST",
        tax_component_1_amount=charges["cgst"],
        tax_component_2_name="SGST",
        tax_component_2_amount=charges["sgst"],
        posted_by=posted_by,
    )

    return room_charge, tax_item


async def adjust_folio_for_early_checkout(
    session: AsyncSession,
    booking: Booking,
    folio: Folio,
    actual_checkout_date: date,
    user_id: int
) -> Dict[str, Any]:
    """
    Adjust folio charges for early checkout.

    AUDIT TRAIL APPROACH:
    - Keep original charges visible (full stay charges posted at check-in)
    - Add CREDIT line items for unused nights (negative amounts)
    - Folio shows: Original Charges - Early Checkout Credit = Final Amount
    - This preserves complete evidence of the transaction

    Args:
        session: Database session
        booking: Booking being checked out
        folio: Primary folio to adjust
        actual_checkout_date: Actual checkout date
        user_id: User performing the checkout

    Returns:
        Dict with adjustment summary
    """
    # Calculate adjustment using billing_engine
    adjustment = await calculate_early_checkout_adjustment(
        session, booking, actual_checkout_date
    )

    if not adjustment["is_early_checkout"]:
        return {"adjusted": False, "reason": "Not an early checkout"}

    # Get dates for description
    check_in_date = (
        booking.check_in_date.date() if booking.check_in_date
        else booking.arrival_date
    )
    original_departure = booking.departure_date

    # Calculate credit amounts for unused nights
    unused_nights = adjustment["original_nights"] - adjustment["billable_nights"]
    nightly_rate = adjustment["nightly_rate"]

    # Credit amount = unused nights × nightly rate
    credit_base = round(nightly_rate * unused_nights, 2)

    # Determine tax rate based on nightly rate
    tax_rate = 0.18 if nightly_rate > 7500 else 0.12
    credit_tax = round(credit_base * tax_rate, 2)
    credit_total = round(credit_base + credit_tax, 2)

    # Post CREDIT line item for unused room charges (negative amount)
    credit_description = (
        f"Early checkout credit – {unused_nights} unused night(s) @ ₹{nightly_rate:.2f}/night "
        f"(departed {actual_checkout_date}, originally {original_departure})"
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
        posted_by=user_id,
        notes=f"Early checkout: {adjustment['original_nights']} → {adjustment['billable_nights']} nights",
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
        posted_by=user_id,
    )
    session.add(tax_credit)

    logger.info(
        f"Early checkout: Posted credit of ₹{credit_total:.2f} for {unused_nights} unused nights "
        f"(booking {booking.id}, folio {folio.id})"
    )

    # Recalculate folio totals
    await session.flush()
    await recalculate_folio_totals(session, folio)

    adjustment["adjusted"] = True
    adjustment["credit_amount"] = credit_total
    adjustment["credit_base"] = credit_base
    adjustment["credit_tax"] = credit_tax
    adjustment["unused_nights"] = unused_nights

    return adjustment


async def recalculate_folio_totals(session: AsyncSession, folio: Folio) -> None:
    """
    Recalculate folio totals from non-voided line items.

    Args:
        session: Database session
        folio: Folio to recalculate
    """
    items = (await session.exec(
        select(FolioLineItem).where(
            FolioLineItem.folio_id == folio.id,
            FolioLineItem.is_voided == False
        )
    )).all()

    charges = sum(li.amount for li in items if li.amount > 0)
    payments = sum(abs(li.amount) for li in items if li.amount < 0)

    folio.total_charges = round(charges, 2)
    folio.total_payments = round(payments, 2)
    folio.balance = round(charges - payments, 2)
    folio.updated_at = datetime.utcnow()

    logger.debug(
        f"Folio {folio.id} recalculated: "
        f"charges={folio.total_charges}, payments={folio.total_payments}, "
        f"balance={folio.balance}"
    )


# ============== NIGHT AUDIT SUPPORT ==============

async def post_nightly_room_charge(
    session: AsyncSession,
    booking: Booking,
    folio: Folio,
    charge_date: date,
    user_id: int
) -> Optional[Tuple[FolioLineItem, FolioLineItem]]:
    """
    Post a single night's room charge to folio (used by Night Audit).

    Args:
        session: Database session
        booking: Booking to charge
        folio: Target folio
        charge_date: Date for this charge
        user_id: User/system posting the charge

    Returns:
        Tuple of (room_charge, tax_item) or None if already posted
    """
    # Check for duplicate - look for charge with this date
    charge_date_str = charge_date.isoformat()
    existing = (await session.exec(
        select(FolioLineItem).where(
            FolioLineItem.folio_id == folio.id,
            FolioLineItem.item_type == "room_charge",
            FolioLineItem.is_voided == False,
            FolioLineItem.description.contains(charge_date_str),
        )
    )).first()

    if existing:
        logger.debug(f"Room charge for {charge_date} already posted to folio {folio.id}")
        return None

    # Get nightly rate
    nightly_rate = await get_effective_nightly_rate(session, booking)

    if nightly_rate <= 0:
        logger.warning(f"Cannot post room charge: nightly rate is {nightly_rate}")
        return None

    # Create charge for 1 night
    description = f"Room charge – {charge_date_str} @ ₹{nightly_rate:.2f}"

    room_charge, tax_item = await create_room_charge_line_item(
        folio_id=folio.id,
        per_night_rate=nightly_rate,
        nights=1,
        posted_by=user_id,
        description=description,
        charge_date=charge_date,
    )

    session.add(room_charge)
    session.add(tax_item)

    logger.info(
        f"Posted nightly charge for {charge_date} to folio {folio.id}: "
        f"₹{nightly_rate} + ₹{room_charge.tax_amount} tax"
    )

    return room_charge, tax_item


# ============== SYNC FUNCTIONS (for non-async contexts) ==============

def calculate_booking_taxes_sync(
    base_price_per_night: float,
    nights: int
) -> Dict[str, float]:
    """
    Synchronous version for booking creation.
    Maintains compatibility with existing sync code.

    Args:
        base_price_per_night: Per-night room rate
        nights: Number of nights

    Returns:
        Dict with calculated_base, tax_rate, taxes, service_fee, total_price
    """
    nights = max(MINIMUM_BILLABLE_NIGHTS, nights)
    charges = calculate_room_charges(base_price_per_night, nights)

    return {
        "calculated_base": charges["base_amount"],
        "tax_rate": charges["tax_rate"],
        "taxes": charges["tax_amount"],
        "service_fee": 0,  # Deprecated, always 0
        "total_price": charges["total_amount"],
        "cgst": charges["cgst"],
        "sgst": charges["sgst"],
    }


# ============== GROUP/MULTI-ROOM BOOKING HELPERS ==============

def is_child_booking(booking: Booking) -> bool:
    """
    Check if a booking is a child booking (part of a multi-room group).
    Child bookings have a parent_booking_id set.
    """
    return booking.parent_booking_id is not None


def is_parent_booking(booking: Booking) -> bool:
    """
    Check if a booking is a parent booking (main booking in a multi-room group).
    Parent bookings have is_group_booking=True and no parent_booking_id.
    """
    return booking.is_group_booking and booking.parent_booking_id is None


async def get_parent_booking(
    session: AsyncSession,
    booking: Booking
) -> Optional[Booking]:
    """
    Get the parent booking for a child booking.
    Returns None if booking is not a child or parent not found.
    """
    if not booking.parent_booking_id:
        return None
    return await session.get(Booking, booking.parent_booking_id)


async def get_group_bookings(
    session: AsyncSession,
    booking: Booking
) -> List[Booking]:
    """
    Get all bookings in a group (including parent and all children).
    Works whether called with parent or child booking.
    """
    from sqlmodel import select

    # Determine group_booking_id
    group_id = booking.group_booking_id
    if not group_id:
        return [booking]  # Not a group booking

    # Get all bookings with same group_booking_id
    result = await session.exec(
        select(Booking).where(Booking.group_booking_id == group_id)
    )
    return list(result.all())


async def get_group_total_charges(
    session: AsyncSession,
    booking: Booking
) -> Dict[str, float]:
    """
    Calculate total charges for entire group.
    Returns consolidated totals across all group bookings.
    """
    from sqlmodel import select
    from app.models.operations import Folio, FolioLineItem

    group_bookings = await get_group_bookings(session, booking)

    total_charges = 0.0
    total_payments = 0.0
    total_balance = 0.0

    for grp_booking in group_bookings:
        # Get folio for this booking
        folio = (await session.exec(
            select(Folio).where(
                Folio.booking_id == grp_booking.id,
                Folio.status == "open"
            )
        )).first()

        if folio:
            total_charges += folio.total_charges or 0
            total_payments += folio.total_payments or 0
            total_balance += folio.balance or 0

    return {
        "total_charges": round(total_charges, 2),
        "total_payments": round(total_payments, 2),
        "total_balance": round(total_balance, 2),
        "booking_count": len(group_bookings),
    }


async def get_child_booking_display_balance(
    session: AsyncSession,
    booking: Booking
) -> Dict[str, Any]:
    """
    Get display values for a child booking.
    Child bookings show ₹0 payable (charges routed to parent).

    Returns:
        Dict with display values and routing info
    """
    if not is_child_booking(booking):
        return {"is_child": False, "display_balance": None}

    parent = await get_parent_booking(session, booking)

    return {
        "is_child": True,
        "parent_booking_id": booking.parent_booking_id,
        "parent_booking_number": parent.booking_number if parent else None,
        "display_balance": 0.0,  # Child bookings show ₹0
        "balance_note": "Charges consolidated to main booking",
        "actual_charges": booking.total_price,  # Internal tracking
    }
