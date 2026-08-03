"""
Folio/Billing API endpoints for hotel cashiering system.
All endpoints are nested under /v1/bookings/{booking_id}/folios.
"""

import re
import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.v1.auth import get_current_user
from app.models.reservations import Booking, Reservation
from app.models.inventory import Room, RoomType
from app.models.operations import Folio, FolioLineItem, Payment, ChargeRoutingRule, AuditLog, PaymasterAccount, PaymasterPosting
from app.models.ar import ARAccount, ARPosting
from app.models.user import User
from app.core.tax import calculate_tax, get_tax_category_for_item, apply_tax_to_line_item, copy_tax_fields
from app.schemas.folio import (
    PostChargeRequest, PostPaymentRequest, PostRefundRequest,
    AdjustChargeRequest, SplitChargeRequest, TransferChargeRequest,
    CrossBookingTransferRequest, MoveToPaymasterRequest,
    CreateFolioRequest, SettleFolioRequest, RoutingRuleRequest,
)

router = APIRouter()


def generate_folio_number() -> str:
    return f"FOL-{secrets.token_urlsafe(6).upper().replace('_', '').replace('-', '')[:6]}"


async def recalculate_folio(session: AsyncSession, folio: Folio):
    """Recalculate folio totals from non-voided line items.

    Charge types:
    - room_charge, tax, service, minibar, etc (positive) → charges
    - adjustment (negative) → credits that REDUCE charges (not payments)
    - payment (negative) → actual guest payments
    """
    items = (await session.exec(
        select(FolioLineItem).where(
            FolioLineItem.folio_id == folio.id,
            FolioLineItem.is_voided == False
        )
    )).all()

    # Separate charges, credits (adjustments), and payments
    gross_charges = sum(li.amount for li in items if li.amount > 0)

    # Credits are negative adjustments that reduce the bill (NOT payments)
    credits = sum(abs(li.amount) for li in items if li.amount < 0 and li.item_type == "adjustment")

    # Payments are actual money received from guest
    payments = sum(abs(li.amount) for li in items if li.amount < 0 and li.item_type == "payment")

    # Net charges = gross charges minus credits
    net_charges = gross_charges - credits

    folio.total_charges = round(net_charges, 2)
    folio.total_payments = round(payments, 2)
    folio.balance = round(net_charges - payments, 2)
    folio.updated_at = datetime.utcnow()


async def sync_booking_payment(session: AsyncSession, booking: Booking):
    """Sync folio totals back to booking payment fields for backward compat"""
    folios = (await session.exec(
        select(Folio).where(Folio.booking_id == booking.id)
    )).all()

    total_charges = sum(f.total_charges for f in folios)
    total_payments = sum(f.total_payments for f in folios)
    total_balance = sum(f.balance for f in folios)

    # Determine payment status
    if total_payments <= 0:
        booking.payment_status = "pending"
    elif total_balance <= 0:
        booking.payment_status = "paid"
    else:
        booking.payment_status = "partial"

    booking.balance_due = max(0, total_balance)
    booking.deposit_amount = total_payments


def serialize_line_item(li: FolioLineItem) -> dict:
    result = {
        "id": li.id,
        "folio_id": li.folio_id,
        "item_type": li.item_type,
        "description": li.description,
        "quantity": li.quantity,
        "unit_price": li.unit_price,
        "amount": li.amount,
        "posted_at": li.posted_at.isoformat() if li.posted_at else None,
        "posted_by": li.posted_by,
        "reference_id": li.reference_id,
        "notes": li.notes,
        "is_voided": li.is_voided,
        "original_line_item_id": li.original_line_item_id,
        "source_folio_id": li.source_folio_id,
        "created_at": li.created_at.isoformat() if li.created_at else None,
    }
    # Tax breakdown — flat fields for frontend + nested for backward compat
    result["tax_amount"] = li.tax_amount
    result["tax_rate_pct"] = li.tax_rate_pct
    result["tax_component_1_name"] = li.tax_component_1_name
    result["tax_component_1_pct"] = li.tax_component_1_pct
    result["tax_component_1_amount"] = li.tax_component_1_amount
    result["tax_component_2_name"] = li.tax_component_2_name
    result["tax_component_2_pct"] = li.tax_component_2_pct
    result["tax_component_2_amount"] = li.tax_component_2_amount
    if li.tax_amount is not None:
        result["tax"] = {
            "rate_pct": li.tax_rate_pct,
            "amount": li.tax_amount,
            "components": [
                {"name": li.tax_component_1_name, "rate_pct": li.tax_component_1_pct, "amount": li.tax_component_1_amount},
                {"name": li.tax_component_2_name, "rate_pct": li.tax_component_2_pct, "amount": li.tax_component_2_amount},
            ]
        }
    return result


def serialize_payment(p: Payment) -> dict:
    return {
        "id": p.id,
        "folio_id": p.folio_id,
        "amount": p.amount,
        "currency": p.currency,
        "method": p.method,
        "payment_type": p.payment_type,
        "transaction_id": p.transaction_id,
        "authorization_code": p.authorization_code,
        "card_last4": p.card_last4,
        "card_brand": p.card_brand,
        "status": p.status,
        "processed_by": p.processed_by,
        "processed_at": p.processed_at.isoformat() if p.processed_at else None,
        "refund_reason": p.refund_reason,
        "notes": p.notes,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def serialize_folio(folio: Folio, line_items=None, payments=None) -> dict:
    result = {
        "id": folio.id,
        "booking_id": folio.booking_id,
        "folio_number": folio.folio_number,
        "window_label": folio.window_label,
        "folio_type": folio.folio_type,
        "total_charges": folio.total_charges,
        "total_payments": folio.total_payments,
        "balance": folio.balance,
        "currency": folio.currency,
        "status": folio.status,
        "invoice_number": folio.invoice_number,
        "is_settled": folio.is_settled,
        "print_count": folio.print_count,
        "created_at": folio.created_at.isoformat() if folio.created_at else None,
        "closed_at": folio.closed_at.isoformat() if folio.closed_at else None,
    }
    if line_items is not None:
        result["line_items"] = [serialize_line_item(li) for li in line_items]
    if payments is not None:
        result["payments"] = [serialize_payment(p) for p in payments]
    return result


# ─── FOLIO CRUD ─────────────────────────────────────────────────────────────────

@router.get("/{booking_id}/folios")
async def list_folios(
    booking_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List all folios for a booking.

    For group bookings:
    - If this is a child booking (has parent_booking_id), redirect to parent's folio
    - Parent booking holds the consolidated folio for all rooms
    """
    import logging
    logger = logging.getLogger(__name__)

    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    # ─── GROUP BOOKING: REDIRECT CHILD TO PARENT ────────────────────────────────
    # Child bookings don't have their own folios - all charges on parent folio
    if booking.parent_booking_id:
        parent_booking = await session.get(Booking, booking.parent_booking_id)
        if parent_booking:
            logger.info(f"Redirecting child booking {booking_id} folio request to parent {parent_booking.id}")
            # Query parent's folios instead
            booking_id = parent_booking.id
            booking = parent_booking

    folios = (await session.exec(
        select(Folio).where(Folio.booking_id == booking_id).order_by(Folio.window_label)
    )).all()

    # Also check via legacy reservation_id (same confirmation_code)
    if not folios and booking.confirmation_code:
        legacy_res = (await session.exec(
            select(Reservation).where(
                Reservation.confirmation_code == booking.confirmation_code
            )
        )).first()
        if legacy_res:
            folios = list((await session.exec(
                select(Folio).where(
                    Folio.reservation_id == legacy_res.id
                ).order_by(Folio.window_label)
            )).all())
            # Link folios to booking for future queries
            for folio in folios:
                if not folio.booking_id:
                    folio.booking_id = booking_id

    # Self-heal stale folios on list
    for folio in folios:
        await _repair_folio_if_needed(session, folio, booking, current_user)

    # ============== POST NIGHTLY CHARGES (PER ROOM, PER NIGHT) ==============
    # Standard hotel billing: post individual nightly charges
    # - On check-in day: post only the first night's charge (per room)
    # - Subsequent nights: added by Night Audit
    # - On checkout/folio view: reconcile consumed nights only (not future nights)
    # - Multi-room bookings: each room gets its own charges
    if booking.status == "checked_in":
        from app.services.billing_service import (
            get_effective_nightly_rate,
            create_room_charge_line_item,
            recalculate_folio_totals,
            is_parent_booking as check_is_parent,
            get_group_bookings as get_all_group_bookings,
        )
        from datetime import date, timedelta

        today = date.today()

        # For group bookings, process all room folios (parent + children)
        # For single bookings, process just this booking's folio
        bookings_to_process = []
        if check_is_parent(booking):
            # Get all bookings in the group (parent + children)
            bookings_to_process = await get_all_group_bookings(session, booking)
            logger.info(f"Group booking {booking.id}: Processing charges for {len(bookings_to_process)} room(s)")
        else:
            bookings_to_process = [booking]

        for bk in bookings_to_process:
            # Skip if booking is not checked in
            if bk.status != "checked_in":
                continue

            check_in_date = bk.check_in_date.date() if bk.check_in_date else bk.arrival_date

            # Get this booking's open folio
            bk_folios = (await session.exec(
                select(Folio).where(
                    Folio.booking_id == bk.id,
                    Folio.status == "open"
                )
            )).all()

            for folio in bk_folios:
                # Get all existing room charges to find which nights are already posted
                existing_charges = (await session.exec(
                    select(FolioLineItem).where(
                        FolioLineItem.folio_id == folio.id,
                        FolioLineItem.item_type == "room_charge",
                        FolioLineItem.is_voided == False,
                    )
                )).all()

                # Extract dates from existing charge descriptions (format: "Room charge – YYYY-MM-DD @ ₹...")
                posted_dates = set()
                has_old_format_charges = False
                old_format_total = 0.0
                for charge in existing_charges:
                    if charge.description:
                        date_match = re.search(r'\d{4}-\d{2}-\d{2}', charge.description)
                        if date_match:
                            posted_dates.add(date_match.group())
                        else:
                            # Old format charge (no date) - flag it and track total
                            has_old_format_charges = True
                            old_format_total += charge.amount

                # For SAME-DAY checkout (checkout on check-in day), only 1 night should be charged
                # This is a day-use scenario: guest checks in AND checks out on the same day
                # NOTE: today == check_in_date just means it's check-in day, NOT same-day checkout
                departure_date = bk.departure_date
                is_same_day_checkout = (departure_date == check_in_date)  # Actual same-day checkout

                # If there are old-format charges (bulk charges from booking creation):
                # - For same-day checkout: void old charges and post correct 1-night charge
                # - For multi-night stays: keep old charges (they're already covering the stay)
                if has_old_format_charges:
                    if is_same_day_checkout:
                        # Same-day checkout but old charges might be for multiple nights - need to correct
                        # Get the expected 1-night charge to compare
                        expected_nightly_rate = await get_effective_nightly_rate(session, bk)
                        if expected_nightly_rate <= 0 and bk.room_type_id:
                            rt = await session.get(RoomType, bk.room_type_id)
                            if rt and rt.base_price:
                                expected_nightly_rate = float(rt.base_price)

                        # If old charges are significantly more than 1 night, void and repost
                        if expected_nightly_rate > 0 and old_format_total > expected_nightly_rate * 1.5:
                            logger.warning(
                                f"Folio {folio.id} (Booking {bk.id}): Same-day checkout but old charges "
                                f"(₹{old_format_total}) exceed 1-night rate (₹{expected_nightly_rate}). "
                                f"Voiding old charges and posting correct amount."
                            )
                            # Void old charges
                            for charge in existing_charges:
                                if charge.description and not re.search(r'\d{4}-\d{2}-\d{2}', charge.description):
                                    charge.is_voided = True
                                    charge.voided_at = datetime.utcnow()
                                    charge.voided_by = current_user.id
                                    # Add note to description instead of void_reason
                                    charge.notes = (charge.notes or "") + " [Voided: Same-day checkout correction]"

                            # Also void any tax items associated with old charges
                            old_tax_items = (await session.exec(
                                select(FolioLineItem).where(
                                    FolioLineItem.folio_id == folio.id,
                                    FolioLineItem.item_type == "tax",
                                    FolioLineItem.is_voided == False,
                                )
                            )).all()
                            for tax_item in old_tax_items:
                                # Only void if it doesn't have a date (old format)
                                if tax_item.description and not re.search(r'\d{4}-\d{2}-\d{2}', tax_item.description or ""):
                                    tax_item.is_voided = True
                                    tax_item.voided_at = datetime.utcnow()
                                    tax_item.voided_by = current_user.id
                                    tax_item.notes = (tax_item.notes or "") + " [Voided: Same-day checkout correction]"

                            # Clear existing_charges so we'll post fresh charges below
                            existing_charges = []
                            posted_dates = set()
                            has_old_format_charges = False
                        else:
                            logger.info(f"Folio {folio.id} (Booking {bk.id}): Has old-format charges, skipping nightly posting")
                            continue
                    else:
                        logger.info(f"Folio {folio.id} (Booking {bk.id}): Has old-format charges, skipping nightly posting")
                        continue

                # Determine which nights to post:
                # - Same-day (check-in day): post first night only
                # - Later days: post only CONSUMED nights (up to yesterday)
                # - Never post future/unconsumed nights
                nights_to_post = []
                is_checkin_day = (today == check_in_date)

                if not existing_charges:
                    if is_checkin_day:
                        # Check-in day with no charges - post first night only
                        nights_to_post.append(check_in_date)
                        logger.info(f"Folio {folio.id} (Booking {bk.id}): Check-in day, posting first night ({check_in_date})")
                    else:
                        # Later day with no charges - reconcile consumed nights only
                        # "Consumed" = nights that have passed (check_in_date to yesterday)
                        current_date = check_in_date
                        yesterday = today - timedelta(days=1)
                        while current_date <= yesterday:
                            nights_to_post.append(current_date)
                            current_date += timedelta(days=1)
                        if nights_to_post:
                            logger.info(f"Folio {folio.id} (Booking {bk.id}): Reconciling {len(nights_to_post)} consumed night(s)")
                else:
                    # Charges exist - check for missing consumed nights only
                    # (Night audit will post current night at end of day)
                    current_date = check_in_date
                    yesterday = today - timedelta(days=1) if today > check_in_date else check_in_date

                    while current_date <= yesterday:
                        date_str = current_date.isoformat()
                        if date_str not in posted_dates:
                            nights_to_post.append(current_date)
                        current_date += timedelta(days=1)

                    if nights_to_post:
                        logger.info(f"Folio {folio.id} (Booking {bk.id}): Found {len(nights_to_post)} missing consumed night(s)")

                if not nights_to_post:
                    continue

                # Get nightly rate for this specific booking
                nightly_rate = await get_effective_nightly_rate(session, bk)

                # Fallback 1: try room type from booking
                if nightly_rate <= 0 and bk.room_type_id:
                    rt = await session.get(RoomType, bk.room_type_id)
                    if rt and rt.base_price:
                        nightly_rate = float(rt.base_price)
                        logger.info(f"Folio {folio.id}: Using room_type base_price fallback: ₹{nightly_rate}")

                # Fallback 2: try room's room_type
                if nightly_rate <= 0 and bk.room_id:
                    room_obj = await session.get(Room, bk.room_id)
                    if room_obj and room_obj.room_type_id:
                        rt = await session.get(RoomType, room_obj.room_type_id)
                        if rt and rt.base_price:
                            nightly_rate = float(rt.base_price)
                            logger.info(f"Folio {folio.id}: Using room->room_type fallback: ₹{nightly_rate}")

                # Fallback 3: Emergency fallback rate
                if nightly_rate <= 0:
                    nightly_rate = 1000.0
                    logger.warning(
                        f"Folio {folio.id}: Using emergency fallback rate ₹{nightly_rate} for booking {bk.id}"
                    )

                # Post individual nightly charges (1 charge per night)
                for charge_date in nights_to_post:
                    charge_date_str = charge_date.isoformat()
                    description = f"Room charge – {charge_date_str} @ ₹{nightly_rate:.2f}"

                    logger.info(f"Folio {folio.id} (Booking {bk.id}): Posting charge for {charge_date_str} @ ₹{nightly_rate}")

                    room_charge, tax_item = await create_room_charge_line_item(
                        folio_id=folio.id,
                        per_night_rate=nightly_rate,
                        nights=1,
                        posted_by=current_user.id,
                        description=description,
                        charge_date=charge_date,
                    )
                    session.add(room_charge)
                    session.add(tax_item)

                await session.flush()
                await recalculate_folio_totals(session, folio)

        # Commit all changes after processing all bookings
        await session.commit()
        logger.info(f"Booking {booking.id}: Completed nightly charge posting")

    # Check if this is a child or parent booking (part of multi-room group)
    from app.services.billing_service import (
        is_child_booking, is_parent_booking, get_parent_booking,
        get_group_bookings, get_group_total_charges
    )

    is_child = is_child_booking(booking)
    is_parent = is_parent_booking(booking)
    parent_info = None
    group_totals = None
    linked_room_folios = []

    if is_child:
        parent = await get_parent_booking(session, booking)
        parent_info = {
            "parent_booking_id": booking.parent_booking_id,
            "parent_booking_number": parent.booking_number if parent else None,
            "balance_note": "Charges consolidated to main booking",
        }

    # For ALL group bookings (parent OR child), calculate consolidated group totals
    if is_parent or is_child:
        group_totals = await get_group_total_charges(session, booking)

        # Get all linked room folios for display breakdown
        group_bookings = await get_group_bookings(session, booking)
        for grp_booking in group_bookings:
            # Fetch room and room_type info
            room_number = None
            room_type_name = None
            if grp_booking.room_id:
                room = await session.get(Room, grp_booking.room_id)
                if room:
                    room_number = room.number
            if grp_booking.room_type_id:
                room_type = await session.get(RoomType, grp_booking.room_type_id)
                if room_type:
                    room_type_name = room_type.name

            room_folios = (await session.exec(
                select(Folio).where(
                    Folio.booking_id == grp_booking.id,
                    Folio.status == "open"
                )
            )).all()

            for rf in room_folios:
                linked_room_folios.append({
                    "booking_id": grp_booking.id,
                    "booking_number": grp_booking.booking_number,
                    "room_number": room_number,
                    "room_type": room_type_name,
                    "is_parent": grp_booking.id == booking.id,
                    "folio_id": rf.id,
                    "folio_number": rf.folio_number,
                    "total_charges": rf.total_charges or 0,
                    "total_payments": rf.total_payments or 0,
                    "balance": rf.balance or 0,
                    "status": grp_booking.status,
                })

    result = []
    for folio in folios:
        li_count = len((await session.exec(
            select(FolioLineItem).where(FolioLineItem.folio_id == folio.id)
        )).all())
        data = serialize_folio(folio)
        data["line_item_count"] = li_count

        # For child bookings, override display balance to 0
        if is_child:
            data["actual_balance"] = data.get("balance", 0)  # Keep actual for internal tracking
            data["balance"] = 0  # Display balance is 0 for child bookings
            data["display_balance"] = 0
            data["is_child_booking"] = True
            data["parent_info"] = parent_info
        elif is_parent:
            # For parent bookings, show group totals
            data["is_parent_booking"] = True
            data["is_group_master"] = True
            # Override balance to show consolidated group balance
            data["individual_balance"] = data.get("balance", 0)  # Keep individual for reference
            data["balance"] = group_totals["total_balance"] if group_totals else data.get("balance", 0)
            data["display_balance"] = group_totals["total_balance"] if group_totals else data.get("balance", 0)
        else:
            data["is_child_booking"] = False
            data["is_parent_booking"] = False
            data["display_balance"] = data.get("balance", 0)

        result.append(data)

    response = {
        "success": True,
        "folios": result,
        "booking_id": booking_id,
        "is_child_booking": is_child,
        "is_parent_booking": is_parent,
        "is_group_booking": is_child or is_parent,
    }

    if is_child and parent_info:
        response["parent_info"] = parent_info

    # Include group totals for ALL group bookings (parent OR child)
    # This ensures consolidated totals show regardless of which room's folio is opened
    if (is_parent or is_child) and group_totals:
        response["is_group_master"] = is_parent  # Only parent is the master
        response["group_totals"] = group_totals
        response["linked_room_folios"] = linked_room_folios
        response["room_count"] = group_totals.get("booking_count", 1)

    # ============== EARLY CHECKOUT PREVIEW ==============
    # If booking is checked in and checkout would be early, calculate adjusted balance
    # This helps frontend show correct amount due before checkout
    if booking.status == "checked_in":
        from datetime import date
        from app.services.billing_service import (
            calculate_early_checkout_adjustment,
            get_effective_nightly_rate,
        )

        today = date.today()
        original_nights = booking.nights or max(1, (booking.departure_date - booking.arrival_date).days)
        check_in_date = booking.check_in_date.date() if booking.check_in_date else booking.arrival_date

        # Calculate actual stayed nights (minimum 1)
        actual_nights = max(1, (today - check_in_date).days)
        is_early_checkout = actual_nights < original_nights

        if is_early_checkout:
            try:
                adjustment = await calculate_early_checkout_adjustment(
                    session, booking, today
                )

                # Calculate what the actual balance should be after early checkout credits
                current_total_balance = sum(f.get("balance", 0) for f in result)
                credit_amount = adjustment.get("refund_amount", 0)
                adjusted_balance = round(current_total_balance - credit_amount, 2)

                response["early_checkout_preview"] = {
                    "is_early_checkout": True,
                    "original_nights": original_nights,
                    "actual_nights": actual_nights,
                    "unused_nights": original_nights - actual_nights,
                    "nightly_rate": adjustment.get("nightly_rate", 0),
                    "original_total": adjustment.get("original_total", current_total_balance),
                    "adjusted_total": adjustment.get("new_total", adjusted_balance),
                    "credit_amount": credit_amount,
                    "current_folio_balance": current_total_balance,
                    "adjusted_balance": max(0, adjusted_balance),  # Amount due after credits
                    "note": f"Early checkout: {actual_nights} of {original_nights} nights. Credit of ₹{credit_amount:.2f} will be applied.",
                }

                # Also update individual folio display balances for frontend
                if result and len(result) > 0:
                    # Distribute credit proportionally or to first folio
                    result[0]["early_checkout_adjusted_balance"] = max(0, adjusted_balance)

                logger.info(f"Early checkout preview for booking {booking_id}: {actual_nights}/{original_nights} nights, credit: ₹{credit_amount}")
            except Exception as e:
                logger.error(f"Failed to calculate early checkout preview: {e}")
                response["early_checkout_preview"] = {
                    "is_early_checkout": True,
                    "error": str(e),
                }
        else:
            response["early_checkout_preview"] = {
                "is_early_checkout": False,
                "original_nights": original_nights,
                "actual_nights": actual_nights,
            }

    return response


@router.post("/{booking_id}/folios", status_code=status.HTTP_201_CREATED)
async def create_folio(
    booking_id: int,
    payload: CreateFolioRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new folio window for a booking"""
    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    # Auto-assign next window label
    existing = (await session.exec(
        select(Folio).where(Folio.booking_id == booking_id).order_by(Folio.window_label.desc())
    )).all()

    if payload.window_label:
        label = payload.window_label
    elif existing:
        last = existing[0].window_label
        label = chr(ord(last) + 1) if last.isalpha() else chr(ord("A") + len(existing))
    else:
        label = "A"

    # Find reservation for this booking
    reservation = (await session.exec(
        select(Reservation).where(Reservation.confirmation_code == booking.confirmation_code)
    )).first()

    folio = Folio(
        booking_id=booking_id,
        reservation_id=reservation.id if reservation else None,  # No fallback - booking_id is the primary key
        folio_number=generate_folio_number(),
        window_label=label,
        folio_type=payload.folio_type,
    )
    session.add(folio)
    await session.commit()
    await session.refresh(folio)

    return {"success": True, "folio": serialize_folio(folio)}


async def _repair_folio_if_needed(
    session: AsyncSession, folio: Folio, booking, current_user
) -> bool:
    """Fix folios created before the tax-line-item / deposit fix.

    Checks:
    1. Empty group folio - add charges for all rooms
    2. Missing tax line item when room_charge exists
    3. Payment amount doesn't match base_price + taxes

    Returns True if any repairs were made.
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        repaired = False
        items = (await session.exec(
            select(FolioLineItem).where(
                FolioLineItem.folio_id == folio.id,
                FolioLineItem.is_voided == False,
            )
        )).all()

        room_charges = [li for li in items if li.item_type == "room_charge"]
        tax_items = [li for li in items if li.item_type == "tax"]
        has_room_charge = len(room_charges) > 0
        has_tax_item = len(tax_items) > 0
        logger.info(f"[folio-repair] Folio {folio.id}: room_charges={len(room_charges)}, tax_items={len(tax_items)}, base={booking.base_price}, taxes={booking.taxes}, payment_status={booking.payment_status}")

        # ─── REPAIR EMPTY GROUP FOLIOS ──────────────────────────────────────────────
        # If this is a group booking parent with an empty folio, add charges for all rooms
        is_group_parent = booking.is_group_booking and booking.parent_booking_id is None
        if not has_room_charge and is_group_parent and booking.group_booking_id:
            from app.services.billing_service import (
                get_effective_nightly_rate,
                create_room_charge_line_item,
            )

            # Get all bookings in this group
            group_bookings = (await session.exec(
                select(Booking).where(Booking.group_booking_id == booking.group_booking_id)
            )).all()

            logger.info(f"[folio-repair] Repairing empty group folio {folio.id} - posting charges for {len(group_bookings)} room(s)")

            for grp_booking in group_bookings:
                # Get rate for this booking
                nightly_rate = await get_effective_nightly_rate(session, grp_booking)

                # Fallback rate logic
                if nightly_rate <= 0 and grp_booking.room_type_id:
                    rt = await session.get(RoomType, grp_booking.room_type_id)
                    if rt and rt.base_price:
                        nightly_rate = float(rt.base_price)

                if nightly_rate <= 0 and grp_booking.room_id:
                    room_obj = await session.get(Room, grp_booking.room_id)
                    if room_obj and room_obj.room_type_id:
                        rt = await session.get(RoomType, room_obj.room_type_id)
                        if rt and rt.base_price:
                            nightly_rate = float(rt.base_price)

                if nightly_rate <= 0:
                    nightly_rate = 1000.0  # Emergency fallback

                booking_nights = grp_booking.nights or max(1, (grp_booking.departure_date - grp_booking.arrival_date).days)
                check_in_date = grp_booking.check_in_date.date() if grp_booking.check_in_date else grp_booking.arrival_date

                # Get room info for description
                room_info = ""
                if grp_booking.room_id:
                    room_obj = await session.get(Room, grp_booking.room_id)
                    if room_obj:
                        room_info = f"Room {room_obj.number} - "

                # Get room type name
                room_type_name = ""
                if grp_booking.room_type_id:
                    rt = await session.get(RoomType, grp_booking.room_type_id)
                    if rt:
                        room_type_name = f"{rt.name} "

                room_label = f"{room_info}{room_type_name}".strip() or f"Room"
                description = f"{room_label} – {booking_nights} night(s) @ ₹{nightly_rate:.2f}/night"

                room_charge, tax_item = await create_room_charge_line_item(
                    folio_id=folio.id,
                    per_night_rate=nightly_rate,
                    nights=booking_nights,
                    posted_by=current_user.id,
                    description=description,
                    charge_date=check_in_date,
                )
                session.add(room_charge)
                session.add(tax_item)
                logger.info(f"[folio-repair] Posted {room_label}: ₹{nightly_rate}/night × {booking_nights} nights")

            repaired = True
            # Refresh lists after adding charges
            items = (await session.exec(
                select(FolioLineItem).where(
                    FolioLineItem.folio_id == folio.id,
                    FolioLineItem.is_voided == False,
                )
            )).all()
            room_charges = [li for li in items if li.item_type == "room_charge"]
            tax_items = [li for li in items if li.item_type == "tax"]
            has_room_charge = len(room_charges) > 0

        # ─── REPAIR EMPTY SINGLE BOOKING FOLIOS ─────────────────────────────────────
        # If this is a single booking with an empty folio, add the room charge
        if not has_room_charge and not is_group_parent and booking.base_price and booking.base_price > 0:
            from app.services.billing_service import (
                get_effective_nightly_rate,
                create_room_charge_line_item,
            )

            nightly_rate = await get_effective_nightly_rate(session, booking)
            if nightly_rate <= 0:
                nightly_rate = booking.base_price / max(1, booking.nights or 1)

            booking_nights = booking.nights or max(1, (booking.departure_date - booking.arrival_date).days)
            check_in_date = booking.check_in_date.date() if booking.check_in_date else booking.arrival_date

            description = f"Room charges – {booking_nights} night(s) @ ₹{nightly_rate:.2f}/night"

            room_charge, tax_item = await create_room_charge_line_item(
                folio_id=folio.id,
                per_night_rate=nightly_rate,
                nights=booking_nights,
                posted_by=current_user.id,
                description=description,
                charge_date=check_in_date,
            )
            session.add(room_charge)
            session.add(tax_item)
            logger.info(f"[folio-repair] Posted single booking charges: ₹{nightly_rate}/night × {booking_nights} nights")
            repaired = True

            # Refresh lists
            items = (await session.exec(
                select(FolioLineItem).where(
                    FolioLineItem.folio_id == folio.id,
                    FolioLineItem.is_voided == False,
                )
            )).all()
            room_charges = [li for li in items if li.item_type == "room_charge"]
            tax_items = [li for li in items if li.item_type == "tax"]
            has_room_charge = len(room_charges) > 0

        # 1. Add missing tax line items for room charges that don't have one
        if has_room_charge and booking.base_price and booking.base_price > 0:
            # Check each room_charge to see if it has a matching tax line item
            for room_item in room_charges:
                # A room_charge has tax data from apply_tax_to_line_item but may lack a separate tax line item
                tax_amount = room_item.tax_amount or 0
                if tax_amount <= 0:
                    # Try fallback from booking-level taxes (for bulk room charge at check-in)
                    if len(room_charges) == 1 and not has_tax_item:
                        tax_amount = booking.taxes or 0
                    else:
                        continue

                # Check if a tax line item already exists for this room charge
                # Match by description or by rough amount
                desc_snippet = room_item.description or ""
                has_matching_tax = any(
                    t for t in tax_items
                    if (desc_snippet and desc_snippet in (t.description or ""))
                    or (t.amount == tax_amount)
                ) if tax_items else False

                # For single room_charge + single tax, consider it matched
                if len(room_charges) == 1 and len(tax_items) == 1:
                    has_matching_tax = True

                if not has_matching_tax and tax_amount > 0:
                    tax_item = FolioLineItem(
                        folio_id=folio.id,
                        item_type="tax",
                        description=f"GST @ {room_item.tax_rate_pct or 0}% on room charges" if room_item else "GST on room charges",
                        quantity=1,
                        unit_price=tax_amount,
                        amount=tax_amount,
                        posted_by=current_user.id,
                        tax_category_id=getattr(room_item, 'tax_category_id', None),
                        tax_rate_pct=getattr(room_item, 'tax_rate_pct', None),
                        tax_amount=tax_amount,
                        tax_component_1_name=getattr(room_item, 'tax_component_1_name', None),
                        tax_component_1_pct=getattr(room_item, 'tax_component_1_pct', None),
                        tax_component_1_amount=getattr(room_item, 'tax_component_1_amount', None),
                        tax_component_2_name=getattr(room_item, 'tax_component_2_name', None),
                        tax_component_2_pct=getattr(room_item, 'tax_component_2_pct', None),
                        tax_component_2_amount=getattr(room_item, 'tax_component_2_amount', None),
                        notes="Auto-added: missing tax line item",
                    )
                    session.add(tax_item)
                    repaired = True
                    logger.info(f"[folio-repair] Added tax line item: {tax_amount}")

        if repaired:
            await recalculate_folio(session, folio)
            await session.commit()
            await session.refresh(folio)
            logger.info(f"[folio-repair] Folio {folio.id} repaired: charges={folio.total_charges}, payments={folio.total_payments}, balance={folio.balance}")

        return repaired
    except Exception as e:
        logger.error(f"[folio-repair] Error repairing folio {folio.id}: {e}")
        try:
            await session.rollback()
        except Exception:
            pass
        return False


@router.post("/{booking_id}/folios/auto-create")
async def auto_create_folio(
    booking_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Auto-create default Folio A with room charges for a booking.

    For group bookings (is_group_booking=True), this creates ONE consolidated folio
    on the parent booking with charges for ALL rooms in the group.
    Child bookings redirect to parent for folio creation.
    """
    import logging
    logger = logging.getLogger(__name__)

    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    # ─── GROUP BOOKING: REDIRECT CHILD TO PARENT ────────────────────────────────
    # Child bookings don't have their own folios - create on parent instead
    if booking.parent_booking_id:
        parent_booking = await session.get(Booking, booking.parent_booking_id)
        if parent_booking:
            logger.info(f"Redirecting child booking {booking_id} folio creation to parent {parent_booking.id}")
            booking_id = parent_booking.id
            booking = parent_booking

    # Check if folio already exists (on the correct booking - parent for groups)
    existing = (await session.exec(
        select(Folio).where(Folio.booking_id == booking_id)
    )).first()
    if existing:
        # Self-heal: fix folios created before tax line item fix
        repaired = await _repair_folio_if_needed(session, existing, booking, current_user)
        msg = "Folio repaired (tax/payment corrected)" if repaired else "Folio already exists"
        return {"success": True, "folio": serialize_folio(existing), "message": msg}

    # Find matching reservation
    reservation = (await session.exec(
        select(Reservation).where(Reservation.confirmation_code == booking.confirmation_code)
    )).first()

    folio = Folio(
        booking_id=booking_id,
        reservation_id=reservation.id if reservation else None,  # No fallback - booking_id is the primary key
        folio_number=generate_folio_number(),
        window_label="A",
        folio_type="guest",
    )
    session.add(folio)
    await session.flush()

    from app.services.billing_service import (
        get_effective_nightly_rate,
        create_room_charge_line_item,
    )
    from datetime import date
    import logging
    logger = logging.getLogger(__name__)

    # ─── GROUP BOOKING HANDLING ─────────────────────────────────────────────────
    # If this is a group/parent booking, post charges for ALL rooms in the group
    # Parent folio = consolidated folio with charges for all rooms
    # Child bookings do NOT get their own folios - all payments through parent

    is_group_parent = booking.is_group_booking and booking.parent_booking_id is None

    if is_group_parent and booking.group_booking_id:
        # Get all bookings in this group (parent + children)
        group_bookings = (await session.exec(
            select(Booking).where(Booking.group_booking_id == booking.group_booking_id)
        )).all()

        logger.info(f"Creating consolidated folio for group booking {booking.group_booking_id} with {len(group_bookings)} room(s)")

        total_rooms_posted = 0
        for grp_booking in group_bookings:
            # Get rate for this booking
            nightly_rate = await get_effective_nightly_rate(session, grp_booking)

            # Fallback rate logic
            if nightly_rate <= 0 and grp_booking.room_type_id:
                rt = await session.get(RoomType, grp_booking.room_type_id)
                if rt and rt.base_price:
                    nightly_rate = float(rt.base_price)

            if nightly_rate <= 0 and grp_booking.room_id:
                room_obj = await session.get(Room, grp_booking.room_id)
                if room_obj and room_obj.room_type_id:
                    rt = await session.get(RoomType, room_obj.room_type_id)
                    if rt and rt.base_price:
                        nightly_rate = float(rt.base_price)

            if nightly_rate <= 0:
                nightly_rate = 1000.0  # Emergency fallback
                logger.warning(f"Using emergency fallback rate for booking {grp_booking.id}")

            booking_nights = grp_booking.nights or max(1, (grp_booking.departure_date - grp_booking.arrival_date).days)
            check_in_date = grp_booking.check_in_date.date() if grp_booking.check_in_date else grp_booking.arrival_date

            # Get room info for description
            room_info = ""
            if grp_booking.room_id:
                room_obj = await session.get(Room, grp_booking.room_id)
                if room_obj:
                    room_info = f"Room {room_obj.number} - "

            # Get room type name
            room_type_name = ""
            if grp_booking.room_type_id:
                rt = await session.get(RoomType, grp_booking.room_type_id)
                if rt:
                    room_type_name = f"{rt.name} "

            # Build description with room details
            is_parent = grp_booking.parent_booking_id is None
            room_label = f"{room_info}{room_type_name}".strip()
            if not room_label:
                room_label = f"Room #{total_rooms_posted + 1}"

            description = f"{room_label} – {booking_nights} night(s) @ ₹{nightly_rate:.2f}/night"

            room_charge, tax_item = await create_room_charge_line_item(
                folio_id=folio.id,
                per_night_rate=nightly_rate,
                nights=booking_nights,
                posted_by=current_user.id,
                description=description,
                charge_date=check_in_date,
            )
            session.add(room_charge)
            session.add(tax_item)
            total_rooms_posted += 1

            logger.info(f"Posted {room_label}: ₹{nightly_rate}/night × {booking_nights} nights = ₹{nightly_rate * booking_nights} + tax")

        # Handle deposit (on parent booking)
        deposit_amount = booking.deposit_amount or 0
        if deposit_amount and deposit_amount > 0:
            payment = Payment(
                folio_id=folio.id,
                amount=deposit_amount,
                method=booking.payment_method or "card",
                payment_type="deposit",
                status="captured",
                processed_by=current_user.id,
            )
            session.add(payment)
            await session.flush()

            session.add(FolioLineItem(
                folio_id=folio.id,
                item_type="payment",
                description=f"Deposit via {booking.payment_method or 'card'}",
                quantity=1,
                unit_price=-deposit_amount,
                amount=-deposit_amount,
                posted_by=current_user.id,
                reference_id=payment.id,
            ))

        await recalculate_folio(session, folio)
        await session.commit()
        await session.refresh(folio)

        return {
            "success": True,
            "folio": serialize_folio(folio),
            "message": f"Group folio created with charges for {total_rooms_posted} room(s)"
        }

    # ─── SINGLE BOOKING HANDLING ────────────────────────────────────────────────
    # Standard single-room booking folio creation

    nightly_rate = await get_effective_nightly_rate(session, booking)

    # Fallback rate logic (same as list_folios and checkout)
    if nightly_rate <= 0 and booking.room_type_id:
        rt = await session.get(RoomType, booking.room_type_id)
        if rt and rt.base_price:
            nightly_rate = float(rt.base_price)

    if nightly_rate <= 0 and booking.room_id:
        room_obj = await session.get(Room, booking.room_id)
        if room_obj and room_obj.room_type_id:
            rt = await session.get(RoomType, room_obj.room_type_id)
            if rt and rt.base_price:
                nightly_rate = float(rt.base_price)

    if nightly_rate <= 0:
        nightly_rate = 1000.0  # Emergency fallback
        logger.warning(f"Using emergency fallback rate for booking {booking.id}")

    # Post ALL nights' room charges at folio creation
    # This ensures folio total matches booking total from the start
    # On early checkout, credits will be posted for unused nights (audit trail)
    booking_nights = booking.nights or max(1, (booking.departure_date - booking.arrival_date).days)
    check_in_date = booking.check_in_date.date() if booking.check_in_date else booking.arrival_date

    # Build description showing full stay
    description = f"Room charges – {booking_nights} night(s) @ ₹{nightly_rate:.2f}/night ({booking.arrival_date} to {booking.departure_date})"

    room_charge, tax_item = await create_room_charge_line_item(
        folio_id=folio.id,
        per_night_rate=nightly_rate,
        nights=booking_nights,  # Post ALL nights, not just 1
        posted_by=current_user.id,
        description=description,
        charge_date=check_in_date,
    )
    session.add(room_charge)
    session.add(tax_item)

    logger.info(f"Posted {booking_nights} night(s) charge to folio {folio.id}: ₹{nightly_rate}/night × {booking_nights} = ₹{nightly_rate * booking_nights} + tax")

    # Pre-existing deposit — use actual deposit_amount (what guest actually paid)
    deposit_amount = booking.deposit_amount or 0
    if deposit_amount and deposit_amount > 0:
        payment = Payment(
            folio_id=folio.id,
            amount=deposit_amount,
            method=booking.payment_method or "card",
            payment_type="deposit",
            status="captured",
            processed_by=current_user.id,
        )
        session.add(payment)
        await session.flush()

        session.add(FolioLineItem(
            folio_id=folio.id,
            item_type="payment",
            description=f"Deposit via {booking.payment_method or 'card'}",
            quantity=1,
            unit_price=-deposit_amount,
            amount=-deposit_amount,
            posted_by=current_user.id,
            reference_id=payment.id,
        ))

    await recalculate_folio(session, folio)
    await session.commit()
    await session.refresh(folio)

    return {"success": True, "folio": serialize_folio(folio), "message": f"Folio created with full stay charges ({booking_nights} nights)"}


@router.get("/{booking_id}/folios/{folio_id}")
async def get_folio(
    booking_id: int,
    folio_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get a single folio with all line items and payments"""
    folio = await session.get(Folio, folio_id)
    if not folio or folio.booking_id != booking_id:
        raise HTTPException(404, "Folio not found")

    # Self-heal stale folios (missing tax line items, wrong payment amounts)
    booking = await session.get(Booking, booking_id)
    if booking:
        await _repair_folio_if_needed(session, folio, booking, current_user)

    line_items = (await session.exec(
        select(FolioLineItem).where(FolioLineItem.folio_id == folio_id)
        .order_by(FolioLineItem.posted_at.desc())
    )).all()

    payments = (await session.exec(
        select(Payment).where(Payment.folio_id == folio_id)
        .order_by(Payment.processed_at.desc())
    )).all()

    return {"success": True, "folio": serialize_folio(folio, line_items, payments)}


# ─── POST CHARGES ────────────────────────────────────────────────────────────────

@router.post("/{booking_id}/folios/{folio_id}/charges", status_code=status.HTTP_201_CREATED)
async def post_charge(
    booking_id: int,
    folio_id: int,
    payload: PostChargeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Post a charge to a folio"""
    # Check if this is a child booking - charges must go through parent folio
    booking = await session.get(Booking, booking_id)
    if booking and booking.parent_booking_id:
        parent = await session.get(Booking, booking.parent_booking_id)
        raise HTTPException(
            400,
            f"This is a child booking in a group. Charges must be posted to the parent booking's folio "
            f"({parent.booking_number if parent else booking.parent_booking_id}). "
            f"Include room details in the charge description."
        )

    folio = await session.get(Folio, folio_id)
    if not folio or folio.booking_id != booking_id:
        raise HTTPException(404, "Folio not found")
    if folio.status == "closed":
        raise HTTPException(400, "Cannot post charges to a closed folio")
    if folio.is_settled:
        raise HTTPException(400, "Cannot modify a settled folio (GST invoice issued)")

    # Check routing rules — redirect to another folio if a rule exists
    rule = (await session.exec(
        select(ChargeRoutingRule).where(
            ChargeRoutingRule.booking_id == booking_id,
            ChargeRoutingRule.charge_category == payload.item_type,
        )
    )).first()

    target_folio = folio
    if rule and rule.target_folio_id != folio_id:
        routed_folio = await session.get(Folio, rule.target_folio_id)
        if routed_folio and routed_folio.status != "closed":
            target_folio = routed_folio

    amount = round(payload.quantity * payload.unit_price, 2)

    line_item = FolioLineItem(
        folio_id=target_folio.id,
        item_type=payload.item_type,
        description=payload.description,
        quantity=payload.quantity,
        unit_price=payload.unit_price,
        amount=amount,
        posted_by=current_user.id,
        notes=payload.notes,
    )

    await apply_tax_to_line_item(session, line_item)
    session.add(line_item)

    # Post tax as a separate line item so folio totals include tax
    tax_amount = line_item.tax_amount or 0
    if tax_amount > 0:
        tax_item = FolioLineItem(
            folio_id=target_folio.id,
            item_type="tax",
            description=f"GST @ {line_item.tax_rate_pct or 0}% on {payload.item_type}",
            quantity=1,
            unit_price=tax_amount,
            amount=tax_amount,
            posted_by=current_user.id,
            tax_category_id=line_item.tax_category_id,
            tax_rate_pct=line_item.tax_rate_pct,
            tax_amount=tax_amount,
            tax_component_1_name=line_item.tax_component_1_name,
            tax_component_1_pct=line_item.tax_component_1_pct,
            tax_component_1_amount=line_item.tax_component_1_amount,
            tax_component_2_name=line_item.tax_component_2_name,
            tax_component_2_pct=line_item.tax_component_2_pct,
            tax_component_2_amount=line_item.tax_component_2_amount,
        )
        session.add(tax_item)

    await recalculate_folio(session, target_folio)

    booking = await session.get(Booking, booking_id)
    if booking:
        await sync_booking_payment(session, booking)

    await session.commit()
    await session.refresh(line_item)

    return {
        "success": True,
        "line_item": serialize_line_item(line_item),
        "folio_balance": target_folio.balance,
        "routed_to_folio": target_folio.id if target_folio.id != folio_id else None,
    }


@router.post("/{booking_id}/folios/{folio_id}/room-charges")
async def post_room_charges(
    booking_id: int,
    folio_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Post nightly room charges (for night audit or manual posting)"""
    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    folio = await session.get(Folio, folio_id)
    if not folio or folio.booking_id != booking_id:
        raise HTTPException(404, "Folio not found")
    if folio.status == "closed":
        raise HTTPException(400, "Cannot post to a closed folio")

    nights = max(1, booking.nights or 1)
    nightly_rate = (booking.base_price or 0) / nights

    line_item = FolioLineItem(
        folio_id=folio.id,
        item_type="room_charge",
        description=f"Nightly room charge @ {nightly_rate:.2f}",
        quantity=1,
        unit_price=nightly_rate,
        amount=nightly_rate,
        posted_by=current_user.id,
    )

    await apply_tax_to_line_item(session, line_item)
    session.add(line_item)

    # Post tax as a separate line item so folio totals include tax
    tax_amount = line_item.tax_amount or 0
    if tax_amount > 0:
        tax_item = FolioLineItem(
            folio_id=folio.id,
            item_type="tax",
            description=f"GST @ {line_item.tax_rate_pct or 0}% on room charge",
            quantity=1,
            unit_price=tax_amount,
            amount=tax_amount,
            posted_by=current_user.id,
            tax_category_id=line_item.tax_category_id,
            tax_rate_pct=line_item.tax_rate_pct,
            tax_amount=tax_amount,
            tax_component_1_name=line_item.tax_component_1_name,
            tax_component_1_pct=line_item.tax_component_1_pct,
            tax_component_1_amount=line_item.tax_component_1_amount,
            tax_component_2_name=line_item.tax_component_2_name,
            tax_component_2_pct=line_item.tax_component_2_pct,
            tax_component_2_amount=line_item.tax_component_2_amount,
        )
        session.add(tax_item)

    await recalculate_folio(session, folio)
    await sync_booking_payment(session, booking)
    await session.commit()

    return {"success": True, "line_item": serialize_line_item(line_item), "folio_balance": folio.balance}


# ─── POST PAYMENTS ───────────────────────────────────────────────────────────────

@router.post("/{booking_id}/folios/{folio_id}/payments", status_code=status.HTTP_201_CREATED)
async def post_payment(
    booking_id: int,
    folio_id: int,
    payload: PostPaymentRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Record a payment on a folio"""
    folio = await session.get(Folio, folio_id)
    if not folio or folio.booking_id != booking_id:
        raise HTTPException(404, "Folio not found")
    if folio.status == "closed":
        raise HTTPException(400, "Cannot post payments to a closed folio")
    if payload.amount <= 0:
        raise HTTPException(400, "Payment amount must be positive")

    # Check if this is a child booking - payments must go through parent
    booking = await session.get(Booking, booking_id)
    if booking and booking.parent_booking_id:
        parent = await session.get(Booking, booking.parent_booking_id)
        raise HTTPException(
            400,
            f"This is a child booking in a group. Payments must be made on the parent booking "
            f"({parent.booking_number if parent else booking.parent_booking_id})"
        )

    payment = Payment(
        folio_id=folio.id,
        amount=payload.amount,
        method=payload.method,
        payment_type=payload.payment_type,
        transaction_id=payload.transaction_id,
        authorization_code=payload.authorization_code,
        card_last4=payload.card_last4,
        card_brand=payload.card_brand,
        upi_id=getattr(payload, 'upi_id', None),
        status="captured",
        processed_by=current_user.id,
        notes=payload.notes,
    )
    session.add(payment)
    await session.flush()

    # Payment method display name
    method_labels = {
        'card': 'Card', 'cash': 'Cash', 'bank_transfer': 'Bank Transfer',
        'upi': 'UPI', 'neft': 'NEFT', 'net_banking': 'Net Banking',
        'voucher': 'Voucher', 'comp': 'Complimentary', 'btc': 'Bill to Company',
    }
    method_label = method_labels.get(payload.method, payload.method)

    # Add payment as negative line item
    session.add(FolioLineItem(
        folio_id=folio.id,
        item_type="payment",
        description=f"Payment via {method_label}" + (f" ({payload.payment_type})" if payload.payment_type != "full_payment" else ""),
        quantity=1,
        unit_price=-payload.amount,
        amount=-payload.amount,
        posted_by=current_user.id,
        reference_id=payment.id,
        notes=payload.notes,
    ))

    await recalculate_folio(session, folio)

    booking = await session.get(Booking, booking_id)
    if booking:
        await sync_booking_payment(session, booking)

    await session.commit()
    await session.refresh(payment)

    return {
        "success": True,
        "payment": serialize_payment(payment),
        "folio_balance": folio.balance,
    }


@router.post("/{booking_id}/folios/{folio_id}/refunds", status_code=status.HTTP_201_CREATED)
async def post_refund(
    booking_id: int,
    folio_id: int,
    payload: PostRefundRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Process a refund on a folio"""
    folio = await session.get(Folio, folio_id)
    if not folio or folio.booking_id != booking_id:
        raise HTTPException(404, "Folio not found")
    if payload.amount <= 0:
        raise HTTPException(400, "Refund amount must be positive")

    # Check if this is a child booking - refunds must go through parent
    booking = await session.get(Booking, booking_id)
    if booking and booking.parent_booking_id:
        parent = await session.get(Booking, booking.parent_booking_id)
        raise HTTPException(
            400,
            f"This is a child booking in a group. Refunds must be processed on the parent booking "
            f"({parent.booking_number if parent else booking.parent_booking_id})"
        )

    method = payload.method or "card"
    if payload.original_payment_id:
        original = await session.get(Payment, payload.original_payment_id)
        if original:
            method = original.method

    payment = Payment(
        folio_id=folio.id,
        amount=-payload.amount,  # Negative for refund
        method=method,
        payment_type="refund",
        status="refunded",
        processed_by=current_user.id,
        refund_reason=payload.reason,
        notes=f"Refund: {payload.reason}",
    )
    session.add(payment)
    await session.flush()

    # Add refund as positive line item (reverses a payment)
    session.add(FolioLineItem(
        folio_id=folio.id,
        item_type="refund",
        description=f"Refund via {method} - {payload.reason}",
        quantity=1,
        unit_price=payload.amount,
        amount=payload.amount,
        posted_by=current_user.id,
        reference_id=payment.id,
    ))

    await recalculate_folio(session, folio)

    booking = await session.get(Booking, booking_id)
    if booking:
        await sync_booking_payment(session, booking)

    await session.commit()

    return {"success": True, "payment": serialize_payment(payment), "folio_balance": folio.balance}


# ─── ADJUSTMENTS / VOID / SPLIT / TRANSFER ──────────────────────────────────────

@router.post("/{booking_id}/folios/{folio_id}/charges/{item_id}/adjust")
async def adjust_charge(
    booking_id: int,
    folio_id: int,
    item_id: int,
    payload: AdjustChargeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Adjust a charge: voids the original and creates a corrected entry"""
    # Check if this is a child booking - adjustments must go through parent folio
    booking = await session.get(Booking, booking_id)
    if booking and booking.parent_booking_id:
        parent = await session.get(Booking, booking.parent_booking_id)
        raise HTTPException(
            400,
            f"This is a child booking. Adjustments must be made on the parent booking's folio "
            f"({parent.booking_number if parent else booking.parent_booking_id})"
        )

    original = await session.get(FolioLineItem, item_id)
    if not original or original.folio_id != folio_id:
        raise HTTPException(404, "Line item not found")

    folio = await session.get(Folio, folio_id)
    if not folio or folio.booking_id != booking_id:
        raise HTTPException(404, "Folio not found")
    if folio.status == "closed":
        raise HTTPException(400, "Cannot adjust charges on a closed folio")
    if folio.is_settled:
        raise HTTPException(400, "Cannot modify a settled folio (GST invoice issued)")
    if original.is_voided:
        raise HTTPException(400, "Cannot adjust a voided item")

    # Void original
    original.is_voided = True
    original.voided_by = current_user.id
    original.voided_at = datetime.utcnow()
    original.notes = (original.notes or "") + f" [Adjusted: {payload.reason}]"

    # Create corrected item with recalculated tax
    adjusted = FolioLineItem(
        folio_id=folio_id,
        item_type=original.item_type,
        description=f"{original.description} (adjusted)",
        quantity=original.quantity,
        unit_price=payload.new_amount / original.quantity if original.quantity else payload.new_amount,
        amount=payload.new_amount,
        posted_by=current_user.id,
        original_line_item_id=original.id,
        notes=f"Adjusted from {original.amount:.2f} to {payload.new_amount:.2f}: {payload.reason}",
    )
    await apply_tax_to_line_item(session, adjusted)
    session.add(adjusted)

    await recalculate_folio(session, folio)

    booking = await session.get(Booking, booking_id)
    if booking:
        await sync_booking_payment(session, booking)

    await session.commit()
    await session.refresh(adjusted)

    return {"success": True, "adjusted_item": serialize_line_item(adjusted), "folio_balance": folio.balance}


@router.post("/{booking_id}/folios/{folio_id}/charges/{item_id}/void")
async def void_charge(
    booking_id: int,
    folio_id: int,
    item_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Void a charge"""
    # Check if this is a child booking - voids must go through parent folio
    booking = await session.get(Booking, booking_id)
    if booking and booking.parent_booking_id:
        parent = await session.get(Booking, booking.parent_booking_id)
        raise HTTPException(
            400,
            f"This is a child booking. Voids must be made on the parent booking's folio "
            f"({parent.booking_number if parent else booking.parent_booking_id})"
        )

    item = await session.get(FolioLineItem, item_id)
    if not item or item.folio_id != folio_id:
        raise HTTPException(404, "Line item not found")

    folio = await session.get(Folio, folio_id)
    if not folio or folio.booking_id != booking_id:
        raise HTTPException(404, "Folio not found")
    if folio.status == "closed":
        raise HTTPException(400, "Cannot void charges on a closed folio")
    if item.is_voided:
        raise HTTPException(400, "Item is already voided")

    item.is_voided = True
    item.voided_by = current_user.id
    item.voided_at = datetime.utcnow()

    await recalculate_folio(session, folio)

    booking = await session.get(Booking, booking_id)
    if booking:
        await sync_booking_payment(session, booking)

    # G-01: Audit log for void
    session.add(AuditLog(
        user_id=current_user.id,
        action="void_charge",
        entity_type="folio",
        entity_id=folio.id,
        description=f"Voided charge #{item_id} ({item.item_type}: {item.description}) on folio {folio.folio_number}",
        old_value={"amount": item.amount, "item_type": item.item_type},
    ))

    await session.commit()

    return {"success": True, "message": "Charge voided", "folio_balance": folio.balance}


@router.post("/{booking_id}/folios/{folio_id}/charges/{item_id}/split")
async def split_charge(
    booking_id: int,
    folio_id: int,
    item_id: int,
    payload: SplitChargeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Split a charge into multiple parts across folios"""
    original = await session.get(FolioLineItem, item_id)
    if not original or original.folio_id != folio_id:
        raise HTTPException(404, "Line item not found")
    if original.is_voided:
        raise HTTPException(400, "Cannot split a voided item")

    folio = await session.get(Folio, folio_id)
    if not folio or folio.booking_id != booking_id:
        raise HTTPException(404, "Folio not found")
    if folio.status == "closed":
        raise HTTPException(400, "Cannot split on a closed folio")

    total_splits = sum(s.get("amount", 0) for s in payload.splits)
    if abs(total_splits - original.amount) > 0.01:
        raise HTTPException(400, f"Split amounts ({total_splits:.2f}) must equal original ({original.amount:.2f})")

    # Void original
    original.is_voided = True
    original.voided_by = current_user.id
    original.voided_at = datetime.utcnow()
    original.notes = (original.notes or "") + f" [Split into {len(payload.splits)} parts]"

    affected_folios = set()
    for split in payload.splits:
        target_folio_id = split.get("folio_id", folio_id)
        split_amount = split["amount"]

        target_folio = await session.get(Folio, target_folio_id)
        if not target_folio or target_folio.booking_id != booking_id:
            raise HTTPException(400, f"Invalid target folio {target_folio_id}")

        new_item = FolioLineItem(
            folio_id=target_folio_id,
            item_type=original.item_type,
            description=f"{original.description} (split)",
            quantity=original.quantity * (split_amount / original.amount) if original.amount else 1,
            unit_price=original.unit_price,
            amount=split_amount,
            posted_by=current_user.id,
            original_line_item_id=original.id,
            source_folio_id=folio_id if target_folio_id != folio_id else None,
        )
        await apply_tax_to_line_item(session, new_item)
        session.add(new_item)
        affected_folios.add(target_folio_id)

    # Recalculate all affected folios
    affected_folios.add(folio_id)
    for fid in affected_folios:
        f = await session.get(Folio, fid)
        if f:
            await recalculate_folio(session, f)

    booking = await session.get(Booking, booking_id)
    if booking:
        await sync_booking_payment(session, booking)

    await session.commit()

    return {"success": True, "message": f"Charge split into {len(payload.splits)} parts"}


@router.post("/{booking_id}/folios/transfer")
async def transfer_charges(
    booking_id: int,
    payload: TransferChargeRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Transfer charges from one folio to another"""
    # Check if this is a child booking - transfers must go through parent
    booking = await session.get(Booking, booking_id)
    if booking and booking.parent_booking_id:
        parent = await session.get(Booking, booking.parent_booking_id)
        raise HTTPException(
            400,
            f"This is a child booking. Folio transfers must be made on the parent booking "
            f"({parent.booking_number if parent else booking.parent_booking_id})"
        )

    target_folio = await session.get(Folio, payload.target_folio_id)
    if not target_folio or target_folio.booking_id != booking_id:
        raise HTTPException(404, "Target folio not found")
    if target_folio.status == "closed":
        raise HTTPException(400, "Cannot transfer to a closed folio")

    affected_folios = {payload.target_folio_id}

    for item_id in payload.line_item_ids:
        item = await session.get(FolioLineItem, item_id)
        if not item or item.is_voided:
            continue

        source_folio = await session.get(Folio, item.folio_id)
        if not source_folio or source_folio.booking_id != booking_id:
            continue
        if source_folio.status == "closed":
            continue

        # Void on source
        item.is_voided = True
        item.voided_by = current_user.id
        item.voided_at = datetime.utcnow()
        item.notes = (item.notes or "") + f" [Transferred to {target_folio.window_label}]"

        # Create copy on target (preserving tax breakdown)
        transferred = FolioLineItem(
            folio_id=payload.target_folio_id,
            item_type=item.item_type,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
            amount=item.amount,
            posted_by=current_user.id,
            original_line_item_id=item.id,
            source_folio_id=item.folio_id,
            notes=payload.notes or f"Transferred from Window {source_folio.window_label}",
        )
        copy_tax_fields(item, transferred)
        session.add(transferred)
        affected_folios.add(item.folio_id)

    for fid in affected_folios:
        f = await session.get(Folio, fid)
        if f:
            await recalculate_folio(session, f)

    booking = await session.get(Booking, booking_id)
    if booking:
        await sync_booking_payment(session, booking)

    await session.commit()

    return {"success": True, "message": f"Transferred {len(payload.line_item_ids)} item(s)"}


@router.post("/{booking_id}/folios/transfer-to-booking")
async def cross_booking_transfer(
    booking_id: int,
    payload: CrossBookingTransferRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Transfer charges from this booking's folio to another booking's folio (cross-booking)."""
    source_booking = await session.get(Booking, booking_id)
    if not source_booking:
        raise HTTPException(404, "Source booking not found")

    # Check if source is a child booking - transfers must go through parent
    if source_booking.parent_booking_id:
        parent = await session.get(Booking, source_booking.parent_booking_id)
        raise HTTPException(
            400,
            f"Source is a child booking. Cross-booking transfers must be made from the parent booking "
            f"({parent.booking_number if parent else source_booking.parent_booking_id})"
        )

    target_booking = await session.get(Booking, payload.target_booking_id)
    if not target_booking:
        raise HTTPException(404, "Target booking not found")

    # Check if target is a child booking - transfers must go to parent
    if target_booking.parent_booking_id:
        parent = await session.get(Booking, target_booking.parent_booking_id)
        raise HTTPException(
            400,
            f"Target is a child booking. Cross-booking transfers must be made to the parent booking "
            f"({parent.booking_number if parent else target_booking.parent_booking_id})"
        )

    if target_booking.status in ("checked_out", "cancelled", "no_show"):
        raise HTTPException(400, f"Target booking is {target_booking.status}")

    # Resolve target folio
    if payload.target_folio_id:
        target_folio = await session.get(Folio, payload.target_folio_id)
        if not target_folio or target_folio.booking_id != payload.target_booking_id:
            raise HTTPException(404, "Target folio not found on target booking")
    else:
        # Find first open guest folio on target booking
        result = await session.exec(
            select(Folio).where(
                Folio.booking_id == payload.target_booking_id,
                Folio.status != "closed",
                Folio.folio_type == "guest",
            ).limit(1)
        )
        target_folio = result.first()
        if not target_folio:
            raise HTTPException(400, "No open folio found on target booking")

    if target_folio.status == "closed":
        raise HTTPException(400, "Target folio is closed")

    transferred_count = 0
    affected_folios = {target_folio.id}

    for item_id in payload.line_item_ids:
        item = await session.get(FolioLineItem, item_id)
        if not item or item.is_voided:
            continue

        source_folio = await session.get(Folio, item.folio_id)
        if not source_folio or source_folio.booking_id != booking_id:
            continue
        if source_folio.status == "closed":
            continue

        # Void on source
        item.is_voided = True
        item.voided_by = current_user.id
        item.voided_at = datetime.utcnow()
        item.notes = (item.notes or "") + f" [Cross-transferred to Booking #{payload.target_booking_id}]"

        # Create copy on target
        transferred = FolioLineItem(
            folio_id=target_folio.id,
            item_type=item.item_type,
            description=item.description,
            quantity=item.quantity,
            unit_price=item.unit_price,
            amount=item.amount,
            posted_by=current_user.id,
            original_line_item_id=item.id,
            source_folio_id=item.folio_id,
            source_booking_id=booking_id,
            notes=payload.notes or f"Transferred from Booking #{booking_id}",
        )
        copy_tax_fields(item, transferred)
        session.add(transferred)
        affected_folios.add(item.folio_id)
        transferred_count += 1

    # Recalculate all affected folios
    for fid in affected_folios:
        f = await session.get(Folio, fid)
        if f:
            await recalculate_folio(session, f)

    # Sync both bookings
    for bk in (source_booking, target_booking):
        await sync_booking_payment(session, bk)

    # Audit log
    session.add(AuditLog(
        user_id=current_user.id,
        action="cross_booking_transfer",
        entity_type="folio",
        entity_id=target_folio.id,
        description=f"Transferred {transferred_count} charge(s) from Booking #{booking_id} to Booking #{payload.target_booking_id}",
        old_value={"source_booking_id": booking_id, "item_ids": payload.line_item_ids},
        new_value={"target_booking_id": payload.target_booking_id, "target_folio_id": target_folio.id},
    ))

    await session.commit()
    return {
        "success": True,
        "message": f"Transferred {transferred_count} charge(s) to Booking #{payload.target_booking_id}",
        "target_folio_id": target_folio.id,
    }


@router.post("/{booking_id}/folios/move-to-paymaster")
async def move_to_paymaster(
    booking_id: int,
    payload: MoveToPaymasterRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Move charges from a booking's folio to a paymaster holding account."""
    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    pm = await session.get(PaymasterAccount, payload.paymaster_account_id)
    if not pm:
        raise HTTPException(404, "Paymaster account not found")
    if pm.status != "active":
        raise HTTPException(400, "Paymaster account is not active")

    moved_count = 0
    total_amount = 0.0
    affected_folios = set()

    for item_id in payload.line_item_ids:
        item = await session.get(FolioLineItem, item_id)
        if not item or item.is_voided:
            continue

        source_folio = await session.get(Folio, item.folio_id)
        if not source_folio or source_folio.booking_id != booking_id:
            continue
        if source_folio.status == "closed":
            continue

        charge_amount = item.amount + (item.tax_amount or 0)

        # Void on source
        item.is_voided = True
        item.voided_by = current_user.id
        item.voided_at = datetime.utcnow()
        item.notes = (item.notes or "") + f" [Moved to Paymaster: {pm.account_name}]"

        # Create paymaster posting
        pm.total_charges = round(pm.total_charges + charge_amount, 2)
        pm.current_balance = round(pm.total_charges - pm.total_transferred, 2)

        session.add(PaymasterPosting(
            paymaster_account_id=pm.id,
            posting_type="charge_in",
            amount=charge_amount,
            balance_after=pm.current_balance,
            description=f"{item.item_type}: {item.description}",
            source_booking_id=booking_id,
            source_folio_id=item.folio_id,
            source_line_item_id=item.id,
            posted_by=current_user.id,
            notes=payload.notes,
        ))

        affected_folios.add(item.folio_id)
        moved_count += 1
        total_amount += charge_amount

    # Recalculate affected folios
    for fid in affected_folios:
        f = await session.get(Folio, fid)
        if f:
            await recalculate_folio(session, f)

    await sync_booking_payment(session, booking)

    # Audit
    session.add(AuditLog(
        user_id=current_user.id,
        action="move_to_paymaster",
        entity_type="paymaster",
        entity_id=pm.id,
        description=f"Moved {moved_count} charge(s) totaling {total_amount:.2f} from Booking #{booking_id} to Paymaster '{pm.account_name}'",
        old_value={"booking_id": booking_id, "item_ids": payload.line_item_ids},
        new_value={"paymaster_id": pm.id, "amount": total_amount},
    ))

    await session.commit()
    return {
        "success": True,
        "message": f"Moved {moved_count} charge(s) ({total_amount:.2f}) to Paymaster",
        "paymaster_balance": pm.current_balance,
    }


# ─── SETTLEMENT ──────────────────────────────────────────────────────────────────

@router.post("/{booking_id}/folios/{folio_id}/settle")
async def settle_folio(
    booking_id: int,
    folio_id: int,
    payload: SettleFolioRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Settle/close a folio. If balance remains and payment_method is given, record final payment."""
    folio = await session.get(Folio, folio_id)
    if not folio or folio.booking_id != booking_id:
        raise HTTPException(404, "Folio not found")
    if folio.status == "closed":
        raise HTTPException(400, "Folio is already closed")

    # If there's a balance and a payment method, record the final payment
    if folio.balance > 0 and payload.payment_method:
        settle_amount = folio.balance

        # ── BTC (Bill to Company) ─────────────────────────────────────
        if payload.payment_method == "btc":
            if not payload.corporate_account_id:
                raise HTTPException(400, "corporate_account_id is required for BTC settlement")

            # Look up the corporate account's AR account
            ar_result = await session.exec(
                select(ARAccount).where(
                    ARAccount.corporate_account_id == payload.corporate_account_id,
                    ARAccount.status == "active",
                )
            )
            ar = ar_result.first()
            if not ar:
                raise HTTPException(404, "No active AR account found for this corporate account")

            # Check credit limit
            if ar.current_balance + settle_amount > ar.credit_limit > 0:
                raise HTTPException(
                    400,
                    f"Exceeds AR credit limit. Balance: {ar.current_balance:.2f}, "
                    f"Settle: {settle_amount:.2f}, Limit: {ar.credit_limit:.2f}"
                )

            # Create AR posting
            new_balance = round(ar.current_balance + settle_amount, 2)
            ar_posting = ARPosting(
                ar_account_id=ar.id,
                booking_id=booking_id,
                folio_id=folio.id,
                posting_type="charge",
                amount=settle_amount,
                balance_after=new_balance,
                description=f"BTC settlement – Folio {folio.folio_number}",
                posted_by=current_user.id,
                due_date=(datetime.utcnow() + timedelta(days=ar.payment_terms_days)).date(),
                status="pending",
            )
            session.add(ar_posting)
            ar.current_balance = new_balance
            ar.updated_at = datetime.utcnow()

        # Record folio payment as normal
        payment = Payment(
            folio_id=folio.id,
            amount=settle_amount,
            method=payload.payment_method,
            payment_type="full_payment",
            status="captured",
            processed_by=current_user.id,
            notes=payload.notes or f"Settlement payment via {payload.payment_method}",
        )
        session.add(payment)
        await session.flush()

        session.add(FolioLineItem(
            folio_id=folio.id,
            item_type="payment",
            description=f"Settlement payment via {payload.payment_method}",
            quantity=1,
            unit_price=-settle_amount,
            amount=-settle_amount,
            posted_by=current_user.id,
            reference_id=payment.id,
        ))
        await recalculate_folio(session, folio)

    if folio.balance > 0.01:
        raise HTTPException(400, f"Outstanding balance of {folio.balance:.2f}. Provide payment_method to settle.")

    folio.status = "closed"
    folio.closed_at = datetime.utcnow()
    folio.closed_by = current_user.id

    # D-22: Invoice immutability — auto-generate GST invoice number on settle
    if not folio.invoice_number:
        folio.invoice_number = f"INV-{folio.folio_number}-{datetime.utcnow().strftime('%Y%m%d')}"
    folio.is_settled = True

    booking = await session.get(Booking, booking_id)
    if booking:
        await sync_booking_payment(session, booking)

    # G-01: Audit log for folio settlement
    session.add(AuditLog(
        user_id=current_user.id,
        action="settle_folio",
        entity_type="folio",
        entity_id=folio.id,
        description=f"Settled folio {folio.folio_number} (booking #{booking_id}) via {payload.payment_method or 'zero-balance'}",
        new_value={"invoice_number": folio.invoice_number, "balance": folio.balance, "method": payload.payment_method},
    ))

    await session.commit()

    return {"success": True, "message": "Folio settled", "folio": serialize_folio(folio)}


@router.post("/{booking_id}/folios/settle-all")
async def settle_all_folios(
    booking_id: int,
    payload: SettleFolioRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Settle all open folios for a booking"""
    folios = (await session.exec(
        select(Folio).where(Folio.booking_id == booking_id, Folio.status == "open")
    )).all()

    if not folios:
        return {"success": True, "message": "No open folios to settle"}

    total_outstanding = sum(f.balance for f in folios if f.balance > 0)

    for folio in folios:
        if folio.balance > 0 and payload.payment_method:
            payment = Payment(
                folio_id=folio.id,
                amount=folio.balance,
                method=payload.payment_method,
                payment_type="full_payment",
                status="captured",
                processed_by=current_user.id,
                notes=payload.notes or "Checkout settlement",
            )
            session.add(payment)
            await session.flush()

            session.add(FolioLineItem(
                folio_id=folio.id,
                item_type="payment",
                description=f"Settlement via {payload.payment_method}",
                quantity=1,
                unit_price=-folio.balance,
                amount=-folio.balance,
                posted_by=current_user.id,
                reference_id=payment.id,
            ))
            await recalculate_folio(session, folio)

        if folio.balance <= 0.01:
            folio.status = "closed"
            folio.closed_at = datetime.utcnow()
            folio.closed_by = current_user.id

    booking = await session.get(Booking, booking_id)
    if booking:
        await sync_booking_payment(session, booking)

    await session.commit()

    settled = sum(1 for f in folios if f.status == "closed")
    return {"success": True, "message": f"Settled {settled}/{len(folios)} folios", "total_settled": settled}


@router.get("/{booking_id}/folios/{folio_id}/statement")
async def get_statement(
    booking_id: int,
    folio_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get printable folio statement data"""
    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    folio = await session.get(Folio, folio_id)
    if not folio or folio.booking_id != booking_id:
        raise HTTPException(404, "Folio not found")

    from app.models.reservations import Guest
    from app.models.inventory import Room, RoomType

    guest = await session.get(Guest, booking.guest_id) if booking.guest_id else None
    room = await session.get(Room, booking.room_id) if booking.room_id else None
    room_type = await session.get(RoomType, booking.room_type_id) if booking.room_type_id else None

    line_items = (await session.exec(
        select(FolioLineItem).where(FolioLineItem.folio_id == folio_id)
        .order_by(FolioLineItem.posted_at.asc())
    )).all()

    payments = (await session.exec(
        select(Payment).where(Payment.folio_id == folio_id)
        .order_by(Payment.processed_at.asc())
    )).all()

    # Build running balance
    running_items = []
    balance = 0.0
    for li in line_items:
        if not li.is_voided:
            balance += li.amount
        running_items.append({
            **serialize_line_item(li),
            "running_balance": round(balance, 2),
        })

    return {
        "success": True,
        "statement": {
            "folio": serialize_folio(folio),
            "booking": {
                "booking_number": booking.booking_number,
                "confirmation_code": booking.confirmation_code,
                "arrival_date": booking.arrival_date.isoformat() if booking.arrival_date else None,
                "departure_date": booking.departure_date.isoformat() if booking.departure_date else None,
                "nights": booking.nights,
            },
            "guest": {
                "name": f"{guest.first_name} {guest.last_name}" if guest else "Guest",
                "email": guest.email if guest else None,
                "phone": guest.phone if guest else None,
            } if guest else None,
            "room": {
                "number": room.number if room else None,
                "type": room_type.name if room_type else None,
            },
            "line_items": running_items,
            "payments": [serialize_payment(p) for p in payments],
        }
    }


# ─── PRINT / REPRINT ─────────────────────────────────────────────────────────────

@router.post("/{booking_id}/folios/{folio_id}/print")
async def print_folio(
    booking_id: int,
    folio_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Print a folio statement. Increments print_count.
    Returns 'Original' on first print, 'Copy of Folio' on reprints (D-10).
    """
    folio = await session.get(Folio, folio_id)
    if not folio or folio.booking_id != booking_id:
        raise HTTPException(404, "Folio not found")

    folio.print_count = (folio.print_count or 0) + 1
    is_copy = folio.print_count > 1
    label = "Copy of Folio" if is_copy else "Original"

    await session.commit()

    return {
        "success": True,
        "print_label": label,
        "print_count": folio.print_count,
        "is_copy": is_copy,
        "invoice_number": folio.invoice_number,
        "folio": serialize_folio(folio),
    }


# ─── ROUTING RULES ───────────────────────────────────────────────────────────────

@router.get("/{booking_id}/routing-rules")
async def list_routing_rules(
    booking_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List charge routing rules for a booking"""
    rules = (await session.exec(
        select(ChargeRoutingRule).where(ChargeRoutingRule.booking_id == booking_id)
    )).all()

    return {
        "success": True,
        "rules": [{
            "id": r.id,
            "booking_id": r.booking_id,
            "charge_category": r.charge_category,
            "target_folio_id": r.target_folio_id,
            "payment_method": r.payment_method,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        } for r in rules]
    }


@router.post("/{booking_id}/routing-rules", status_code=status.HTTP_201_CREATED)
async def create_routing_rule(
    booking_id: int,
    payload: RoutingRuleRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a charge routing rule"""
    target_folio = await session.get(Folio, payload.target_folio_id)
    if not target_folio or target_folio.booking_id != booking_id:
        raise HTTPException(400, "Target folio not found for this booking")

    # Remove existing rule for same category
    existing = (await session.exec(
        select(ChargeRoutingRule).where(
            ChargeRoutingRule.booking_id == booking_id,
            ChargeRoutingRule.charge_category == payload.charge_category,
        )
    )).first()
    if existing:
        await session.delete(existing)

    rule = ChargeRoutingRule(
        booking_id=booking_id,
        charge_category=payload.charge_category,
        target_folio_id=payload.target_folio_id,
        payment_method=payload.payment_method,
        created_by=current_user.id,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)

    return {"success": True, "rule_id": rule.id}


@router.delete("/{booking_id}/routing-rules/{rule_id}")
async def delete_routing_rule(
    booking_id: int,
    rule_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete a charge routing rule"""
    rule = await session.get(ChargeRoutingRule, rule_id)
    if not rule or rule.booking_id != booking_id:
        raise HTTPException(404, "Routing rule not found")

    await session.delete(rule)
    await session.commit()

    return {"success": True, "message": "Routing rule deleted"}


# ─── GROUP BOOKING FOLIOS ─────────────────────────────────────────────────────────

@router.get("/{booking_id}/group-folios")
async def get_group_folios(
    booking_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Get all folios for a group booking (parent + all child bookings).

    Returns:
    - Consolidated total for the entire group
    - Individual folio details with parent/child markers
    - Child bookings show display_balance=0 (routed to parent)
    """
    import logging
    logger = logging.getLogger(__name__)

    from app.services.billing_service import (
        is_child_booking, is_parent_booking, get_parent_booking,
        get_group_bookings, get_group_total_charges
    )

    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    # Get all bookings in the group
    group_bookings = await get_group_bookings(session, booking)

    if len(group_bookings) <= 1:
        # Not a group booking - return regular folio list
        return await list_folios(booking_id, session, current_user)

    # Get consolidated totals
    group_totals = await get_group_total_charges(session, booking)

    # Find the parent booking
    parent_booking = None
    child_bookings = []

    for grp_booking in group_bookings:
        if is_parent_booking(grp_booking):
            parent_booking = grp_booking
        elif is_child_booking(grp_booking):
            child_bookings.append(grp_booking)

    # Build response with all folios
    all_folios = []

    # Process parent booking folios first
    if parent_booking:
        parent_folios = (await session.exec(
            select(Folio).where(Folio.booking_id == parent_booking.id).order_by(Folio.window_label)
        )).all()

        for folio in parent_folios:
            data = serialize_folio(folio)
            data["booking_id"] = parent_booking.id
            data["booking_number"] = parent_booking.booking_number
            data["is_parent_booking"] = True
            data["is_child_booking"] = False
            data["display_balance"] = folio.balance  # Parent shows actual balance

            # Include room info
            if parent_booking.room_id:
                from app.models.inventory import Room
                room = await session.get(Room, parent_booking.room_id)
                data["room_number"] = room.number if room else None

            all_folios.append(data)

    # Process child booking folios
    for child_booking in child_bookings:
        child_folios = (await session.exec(
            select(Folio).where(Folio.booking_id == child_booking.id).order_by(Folio.window_label)
        )).all()

        for folio in child_folios:
            data = serialize_folio(folio)
            data["booking_id"] = child_booking.id
            data["booking_number"] = child_booking.booking_number
            data["is_parent_booking"] = False
            data["is_child_booking"] = True
            data["actual_balance"] = folio.balance  # Keep actual for tracking
            data["balance"] = 0  # Override display balance
            data["display_balance"] = 0  # Child shows 0 payable
            data["parent_booking_id"] = child_booking.parent_booking_id
            data["balance_note"] = "Charges consolidated to main booking"

            # Include room info
            if child_booking.room_id:
                from app.models.inventory import Room
                room = await session.get(Room, child_booking.room_id)
                data["room_number"] = room.number if room else None

            all_folios.append(data)

    return {
        "success": True,
        "is_group_booking": True,
        "group_booking_id": booking.group_booking_id,
        "booking_count": len(group_bookings),
        "parent_booking": {
            "id": parent_booking.id,
            "booking_number": parent_booking.booking_number,
        } if parent_booking else None,
        "group_totals": group_totals,
        "folios": all_folios,
        "message": f"Group has {len(group_bookings)} bookings. Total balance payable on parent booking only."
    }


# ─── CHECKOUT PREVIEW ──────────────────────────────────────────────────────────

@router.get("/{booking_id}/checkout-preview")
async def get_checkout_preview(
    booking_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Get checkout preview with correct balance calculation.

    For early checkout (checkout before departure date):
    - Calculates actual nights stayed
    - Shows credit amount for unused nights
    - Returns adjusted balance (actual amount due)

    This ensures the checkout dialog shows the correct payment amount.
    """
    import logging
    from datetime import date
    from app.services.billing_service import (
        calculate_early_checkout_adjustment,
        get_effective_nightly_rate,
        is_child_booking, is_parent_booking, get_parent_booking,
        get_group_bookings, get_group_total_charges,
    )

    logger = logging.getLogger(__name__)

    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    if booking.status != "checked_in":
        raise HTTPException(400, "Booking is not checked in")

    # Get all folios
    folios = (await session.exec(
        select(Folio).where(
            Folio.booking_id == booking_id,
            Folio.status == "open"
        ).order_by(Folio.window_label)
    )).all()

    # Calculate current folio balance
    current_balance = sum(f.balance or 0 for f in folios)

    # Determine if this is an early checkout
    today = date.today()
    original_nights = booking.nights or max(1, (booking.departure_date - booking.arrival_date).days)
    check_in_date = booking.check_in_date.date() if booking.check_in_date else booking.arrival_date
    actual_nights = max(1, (today - check_in_date).days)
    is_early = actual_nights < original_nights

    # Build folio windows for display
    folio_windows = []
    for f in folios:
        folio_windows.append({
            "folio_id": f.id,
            "window_label": f.window_label,
            "folio_type": f.folio_type,
            "total_charges": f.total_charges or 0,
            "total_payments": f.total_payments or 0,
            "balance": f.balance or 0,
        })

    response = {
        "success": True,
        "booking_id": booking_id,
        "booking_number": booking.booking_number,
        "is_early_checkout": is_early,
        "original_nights": original_nights,
        "actual_nights": actual_nights,
        "original_departure": booking.departure_date.isoformat() if booking.departure_date else None,
        "checkout_date": today.isoformat(),
        "folio_windows": folio_windows,
        "current_folio_balance": round(current_balance, 2),
    }

    if is_early:
        try:
            adjustment = await calculate_early_checkout_adjustment(
                session, booking, today
            )

            credit_amount = adjustment.get("refund_amount", 0)
            adjusted_balance = max(0, round(current_balance - credit_amount, 2))

            response["early_checkout"] = {
                "unused_nights": original_nights - actual_nights,
                "nightly_rate": adjustment.get("nightly_rate", 0),
                "original_total": adjustment.get("original_total", current_balance),
                "actual_total": adjustment.get("new_total", adjusted_balance),
                "credit_base": adjustment.get("new_base", 0),
                "credit_tax": adjustment.get("new_tax", 0),
                "credit_amount": credit_amount,
            }
            response["adjusted_balance"] = adjusted_balance
            response["amount_due"] = adjusted_balance
            response["message"] = (
                f"Early checkout: {actual_nights} of {original_nights} nights. "
                f"Credit of ₹{credit_amount:.2f} will be applied for {original_nights - actual_nights} unused night(s)."
            )

            # Update individual folio window balances for display
            if folio_windows and credit_amount > 0:
                # Apply credit to first folio window
                folio_windows[0]["adjusted_balance"] = adjusted_balance
                folio_windows[0]["credit_applied"] = credit_amount

            logger.info(
                f"Checkout preview for booking {booking_id}: "
                f"{actual_nights}/{original_nights} nights, credit: ₹{credit_amount}, "
                f"balance: ₹{current_balance} → ₹{adjusted_balance}"
            )

        except Exception as e:
            logger.error(f"Failed to calculate early checkout adjustment: {e}")
            response["adjusted_balance"] = current_balance
            response["amount_due"] = current_balance
            response["error"] = str(e)
    else:
        # Not early checkout - full balance due
        response["adjusted_balance"] = current_balance
        response["amount_due"] = current_balance
        response["message"] = "Full stay completed. Total balance due."

    return response
