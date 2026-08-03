"""
Enhanced Cancellation Service with Room Release and Waitlist Processing

Handles full cancellation flow:
1. Release Redis lock if held
2. Update room status to dirty or clear assignment
3. Mark booking as cancelled with history
4. Process refund if applicable
5. Auto-book first waitlist entry if available
6. Send notifications to guest and waitlist conversions
"""

import logging
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.reservations import Reservation, ReservationHistory, Guest, Waitlist
from app.models.inventory import Room, RoomType
from app.models.operations import Folio, Payment
from app.services.refund_service import process_partial_refund
from app.services.reservation_service import cancel_reservation
from app.services.email_service import get_email_service
from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_lock_manager():
    """Get lock manager with fallback for when Redis is unavailable."""
    try:
        from app.services.redis_lock_service import get_lock_manager
        return get_lock_manager()
    except (RuntimeError, ImportError) as e:
        logger.debug(f"Lock manager not available: {e}")
        return None


async def cancel_booking_with_release(
    session: AsyncSession,
    booking_id: int,
    cancellation_reason: str = "guest_cancelled",
    refund_percentage: Optional[float] = None,
    notify_guest: bool = True,
    process_waitlist: bool = True
) -> Dict[str, Any]:
    """
    Cancel booking with full cleanup including room release and waitlist processing.

    Args:
        session: Database session
        booking_id: ID of the booking to cancel
        cancellation_reason: Reason for cancellation
        refund_percentage: Percentage to refund (defaults to config setting)
        notify_guest: Whether to send cancellation email to guest
        process_waitlist: Whether to auto-book first waitlist entry

    Returns:
        Dict with cancellation result details:
        {
            "success": bool,
            "reservation": Reservation or None,
            "refund": Payment or None,
            "room_released": bool,
            "lock_released": bool,
            "waitlist_converted": int or None (reservation ID if converted)
        }
    """
    result = {
        "success": False,
        "reservation": None,
        "refund": None,
        "room_released": False,
        "lock_released": False,
        "waitlist_converted": None
    }

    try:
        # Get reservation
        reservation = await session.get(Reservation, booking_id)
        if not reservation:
            logger.warning(f"Reservation {booking_id} not found")
            return result

        if reservation.status in ["checked_out", "cancelled"]:
            logger.info(f"Reservation {booking_id} already {reservation.status}")
            return result

        # Store room info before cancellation
        room_id = reservation.room_id
        room_type_id = reservation.room_type_id
        arrival_date = reservation.arrival_date
        departure_date = reservation.departure_date

        # 1. Release Redis lock if held
        if room_id:
            lock_manager = _get_lock_manager()
            if lock_manager:
                try:
                    released = await lock_manager.release_room_lock(room_id, booking_id)
                    if released:
                        logger.info(f"Released Redis lock for room {room_id}, booking {booking_id}")
                        result["lock_released"] = True
                except Exception as e:
                    logger.warning(f"Error releasing lock for room {room_id}: {e}")

        # 2. Update room status if assigned
        if room_id:
            room = await session.get(Room, room_id)
            if room:
                # If guest was checked in, mark room as dirty
                if reservation.status == "checked_in":
                    room.status = "dirty"
                    room.occupancy_status = "vacant"
                    room.cleaning_status = "dirty"
                    logger.info(f"Room {room.number} marked dirty after cancellation of checked-in booking")
                else:
                    room.status = "available"
                    room.occupancy_status = "vacant"
                    logger.info(f"Room {room.number} released and made available")

                room.updated_at = datetime.utcnow()
                result["room_released"] = True

        # 3. Clear room assignment from reservation
        reservation.room_id = None

        # 4. Cancel the reservation with history
        cancelled = await cancel_reservation(
            session,
            booking_id,
            reason=cancellation_reason,
            user_id=None  # System cancellation
        )

        if not cancelled:
            logger.warning(f"Failed to cancel reservation {booking_id}")
            return result

        result["reservation"] = cancelled

        # 5. Process refund if applicable
        if refund_percentage is None:
            refund_percentage = settings.auto_cancel_refund_percentage

        refund = await process_partial_refund(
            session,
            booking_id,
            refund_percentage=refund_percentage,
            reason=cancellation_reason
        )

        if refund:
            cancelled.payment_status = "refunded"
            result["refund"] = refund

        await session.flush()

        # 6. Process waitlist if enabled
        if process_waitlist and room_type_id:
            waitlist_reservation_id = await process_waitlist_for_dates(
                session,
                room_type_id=room_type_id,
                arrival_date=arrival_date,
                departure_date=departure_date
            )
            if waitlist_reservation_id:
                result["waitlist_converted"] = waitlist_reservation_id
                logger.info(f"Waitlist converted to reservation {waitlist_reservation_id}")

        # 7. Send notification to guest
        if notify_guest:
            await send_cancellation_notification(
                session,
                reservation=cancelled,
                refund=refund,
                refund_percentage=refund_percentage,
                cancellation_reason=cancellation_reason
            )

        result["success"] = True
        logger.info(f"Successfully cancelled booking {booking_id} with full cleanup")

        return result

    except Exception as e:
        logger.error(f"Error in cancel_booking_with_release for {booking_id}: {str(e)}")
        return result


async def process_waitlist_for_dates(
    session: AsyncSession,
    room_type_id: int,
    arrival_date,
    departure_date
) -> Optional[int]:
    """
    Check waitlist and auto-book first matching entry.

    Args:
        session: Database session
        room_type_id: Room type that became available
        arrival_date: Start date of availability
        departure_date: End date of availability

    Returns:
        New reservation ID if waitlist was converted, None otherwise
    """
    try:
        # Get room type name for matching
        room_type = await session.get(RoomType, room_type_id)
        if not room_type:
            return None

        # Find matching waitlist entries (ordered by priority, then by created_at)
        waitlist_entries = (await session.execute(
            select(Waitlist).where(
                and_(
                    Waitlist.status == "active",
                    Waitlist.arrival_date <= arrival_date,
                    Waitlist.departure_date >= departure_date,
                    Waitlist.room_type_preference == room_type.name
                )
            ).order_by(
                Waitlist.priority.desc(),
                Waitlist.created_at.asc()
            )
        )).scalars().all()

        if not waitlist_entries:
            # Try without exact date match - overlapping dates
            waitlist_entries = (await session.execute(
                select(Waitlist).where(
                    and_(
                        Waitlist.status == "active",
                        Waitlist.room_type_preference == room_type.name,
                        # Overlapping dates
                        Waitlist.arrival_date < departure_date,
                        Waitlist.departure_date > arrival_date
                    )
                ).order_by(
                    Waitlist.priority.desc(),
                    Waitlist.created_at.asc()
                )
            )).scalars().all()

        if not waitlist_entries:
            logger.debug(f"No waitlist entries for {room_type.name} matching dates")
            return None

        # Try to convert first waitlist entry
        from app.services.reservation_service import create_reservation

        for entry in waitlist_entries:
            try:
                # Get guest
                guest = await session.get(Guest, entry.guest_id)
                if not guest:
                    continue

                # Create reservation from waitlist
                new_reservation = await create_reservation(
                    session,
                    guest_id=entry.guest_id,
                    room_type_id=room_type_id,
                    arrival_date=entry.arrival_date,
                    departure_date=entry.departure_date,
                    adults=entry.adults,
                    children=entry.children,
                    rate_plan_id=entry.rate_plan_id,
                    source="waitlist_conversion"
                )

                if new_reservation:
                    # Update waitlist entry
                    entry.status = "converted"
                    entry.converted_at = datetime.utcnow()
                    entry.converted_to_reservation_id = new_reservation.id

                    await session.flush()

                    # Send notification to waitlist guest
                    await send_waitlist_conversion_notification(
                        session,
                        guest=guest,
                        reservation=new_reservation,
                        room_type_name=room_type.name
                    )

                    logger.info(
                        f"Waitlist entry {entry.id} converted to reservation {new_reservation.id}"
                    )
                    return new_reservation.id

            except Exception as e:
                logger.warning(f"Failed to convert waitlist entry {entry.id}: {e}")
                continue

        return None

    except Exception as e:
        logger.error(f"Error processing waitlist: {e}")
        return None


async def send_cancellation_notification(
    session: AsyncSession,
    reservation: Reservation,
    refund: Optional[Payment],
    refund_percentage: float,
    cancellation_reason: str = "Guest requested cancellation"
):
    """Send cancellation confirmation email to guest."""
    try:
        guest = await session.get(Guest, reservation.guest_id)
        if not guest or not guest.email:
            return

        email_service = get_email_service()

        # Get room type name
        room_type_name = "Standard Room"
        if reservation.room_type_id:
            from app.models.inventory import RoomType
            room_type = await session.get(RoomType, reservation.room_type_id)
            if room_type:
                room_type_name = room_type.name

        # Send user-friendly cancellation email
        email_service.send_cancellation_email(
            to_email=guest.email,
            guest_name=f"{guest.first_name} {guest.last_name}",
            booking_number=reservation.confirmation_code,
            check_in_date=reservation.arrival_date.strftime("%B %d, %Y"),
            check_out_date=reservation.departure_date.strftime("%B %d, %Y"),
            room_type=room_type_name,
            cancellation_reason=cancellation_reason
        )

        logger.info(f"Sent cancellation email to {guest.email}")

    except Exception as e:
        logger.error(f"Failed to send cancellation email: {e}")


async def send_waitlist_conversion_notification(
    session: AsyncSession,
    guest: Guest,
    reservation: Reservation,
    room_type_name: str
):
    """Send notification to guest when their waitlist entry is converted."""
    try:
        if not guest.email:
            return

        email_service = get_email_service()

        # Use booking confirmation email (if available) or generic email
        try:
            email_service.send_booking_confirmation_email(
                to_email=guest.email,
                guest_name=f"{guest.first_name} {guest.last_name}",
                booking_number=reservation.confirmation_code,
                check_in_date=reservation.arrival_date.strftime("%B %d, %Y"),
                check_out_date=reservation.departure_date.strftime("%B %d, %Y"),
                room_type=room_type_name,
                total_amount=reservation.total_amount,
                currency=reservation.currency
            )
            logger.info(f"Sent waitlist conversion email to {guest.email}")
        except Exception:
            # Fallback to simple notification
            logger.info(f"Waitlist conversion notification for {guest.email} - booking {reservation.confirmation_code}")

    except Exception as e:
        logger.error(f"Failed to send waitlist conversion email: {e}")


async def release_room_on_checkout(
    session: AsyncSession,
    reservation_id: int
) -> bool:
    """
    Release room when guest checks out.
    Called by checkout process.
    """
    try:
        reservation = await session.get(Reservation, reservation_id)
        if not reservation:
            return False

        room_id = reservation.room_id

        if not room_id:
            return True  # No room to release

        # Release Redis lock
        lock_manager = _get_lock_manager()
        if lock_manager:
            try:
                await lock_manager.release_room_lock(room_id, reservation_id)
            except Exception as e:
                logger.warning(f"Error releasing lock on checkout: {e}")

        # Update room status to dirty
        room = await session.get(Room, room_id)
        if room:
            room.status = "dirty"
            room.occupancy_status = "vacant"
            room.cleaning_status = "dirty"
            room.updated_at = datetime.utcnow()

        await session.flush()

        logger.info(f"Room {room_id} released on checkout for reservation {reservation_id}")
        return True

    except Exception as e:
        logger.error(f"Error releasing room on checkout: {e}")
        return False


async def get_waitlist_entries_for_dates(
    session: AsyncSession,
    arrival_date,
    departure_date,
    room_type_name: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Get all active waitlist entries that overlap with given dates.
    Used for monitoring and manual processing.
    """
    query = select(Waitlist).where(
        and_(
            Waitlist.status == "active",
            Waitlist.arrival_date < departure_date,
            Waitlist.departure_date > arrival_date
        )
    )

    if room_type_name:
        query = query.where(Waitlist.room_type_preference == room_type_name)

    query = query.order_by(Waitlist.priority.desc(), Waitlist.created_at.asc())

    entries = (await session.execute(query)).scalars().all()

    result = []
    for entry in entries:
        guest = await session.get(Guest, entry.guest_id)
        result.append({
            "id": entry.id,
            "guest_id": entry.guest_id,
            "guest_name": f"{guest.first_name} {guest.last_name}" if guest else "Unknown",
            "arrival_date": entry.arrival_date.isoformat(),
            "departure_date": entry.departure_date.isoformat(),
            "room_type": entry.room_type_preference,
            "adults": entry.adults,
            "children": entry.children,
            "priority": entry.priority,
            "created_at": entry.created_at.isoformat()
        })

    return result
