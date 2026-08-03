"""
Refund processing service for auto-cancellation and manual refunds
"""
from datetime import datetime
from typing import Optional, Tuple
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from app.models.operations import Folio, FolioLineItem, Payment
from app.models.reservations import Reservation, ReservationHistory, Guest
from app.services.reservation_service import cancel_reservation
from app.services.email_service import get_email_service
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


async def process_partial_refund(
    session: AsyncSession,
    reservation_id: int,
    refund_percentage: float = 0.5,
    reason: str = "auto_cancelled_no_precheckin"
) -> Optional[Payment]:
    """
    Process a partial refund for a booking.

    Args:
        session: Database session
        reservation_id: ID of the reservation to refund
        refund_percentage: Percentage of total payments to refund (default 50%)
        reason: Reason for the refund

    Returns:
        The created refund Payment record, or None if no payments exist
    """
    try:
        # Get the Folio for this reservation
        result = await session.exec(
            select(Folio).where(Folio.reservation_id == reservation_id)
        )
        folio = result.first()

        if not folio:
            logger.warning(f"No folio found for reservation {reservation_id}, skipping refund")
            return None

        # Check if there are any payments to refund
        if folio.total_payments <= 0:
            logger.info(f"No payments to refund for reservation {reservation_id}")
            return None

        # Calculate refund amount
        refund_amount = folio.total_payments * refund_percentage

        # Get the original payment to copy method/card details
        original_payment_result = await session.exec(
            select(Payment).where(
                Payment.folio_id == folio.id,
                Payment.status == "captured"
            ).order_by(Payment.processed_at.desc())
        )
        original_payment = original_payment_result.first()

        # Create refund Payment record
        refund_payment = Payment(
            folio_id=folio.id,
            amount=-refund_amount,  # Negative amount for refund
            currency=folio.currency,
            method=original_payment.method if original_payment else "refund",
            payment_type="refund",
            status="refunded",
            card_last4=original_payment.card_last4 if original_payment else None,
            card_brand=original_payment.card_brand if original_payment else None,
            processed_at=datetime.utcnow(),
            refunded_at=datetime.utcnow(),
            refund_reason=reason,
            notes=f"Automatic {int(refund_percentage * 100)}% refund - {reason}"
        )
        session.add(refund_payment)

        # Create FolioLineItem for the refund
        refund_line_item = FolioLineItem(
            folio_id=folio.id,
            item_type="refund",
            description=f"Refund - {reason}",
            quantity=1.0,
            unit_price=-refund_amount,
            amount=-refund_amount,
            posted_at=datetime.utcnow(),
            notes=f"{int(refund_percentage * 100)}% refund processed"
        )
        session.add(refund_line_item)

        # Update Folio totals
        folio.total_payments -= refund_amount
        folio.balance = folio.total_charges - folio.total_payments
        folio.updated_at = datetime.utcnow()

        await session.flush()

        logger.info(f"Processed ${refund_amount:.2f} refund for reservation {reservation_id}")
        return refund_payment

    except Exception as e:
        logger.error(f"Error processing refund for reservation {reservation_id}: {str(e)}")
        return None


async def cancel_and_refund_booking(
    session: AsyncSession,
    booking_id: int,
    cancellation_reason: str = "auto_cancelled_no_precheckin",
    refund_percentage: Optional[float] = None
) -> Tuple[Optional[Reservation], Optional[Payment]]:
    """
    Cancel booking and process partial refund.
    Combines cancel_reservation() with refund processing.

    Args:
        session: Database session
        booking_id: ID of the booking to cancel
        cancellation_reason: Reason for cancellation
        refund_percentage: Percentage to refund (defaults to config setting)

    Returns:
        Tuple of (cancelled Reservation, refund Payment) or (None, None) on failure
    """
    try:
        # Use config default if not specified
        if refund_percentage is None:
            refund_percentage = settings.auto_cancel_refund_percentage

        # Get reservation first to check status and get guest info
        reservation = await session.get(Reservation, booking_id)
        if not reservation:
            logger.warning(f"Reservation {booking_id} not found")
            return None, None

        if reservation.status in ["checked_out", "cancelled", "checked_in"]:
            logger.info(f"Reservation {booking_id} already {reservation.status}, skipping")
            return None, None

        # Cancel the reservation
        cancelled_reservation = await cancel_reservation(
            session,
            booking_id,
            reason=cancellation_reason,
            user_id=None  # System cancellation
        )

        if not cancelled_reservation:
            logger.warning(f"Failed to cancel reservation {booking_id}")
            return None, None

        # Update payment_status to refunded
        cancelled_reservation.payment_status = "refunded"

        # Process the refund
        refund_payment = await process_partial_refund(
            session,
            booking_id,
            refund_percentage=refund_percentage,
            reason=cancellation_reason
        )

        # Get guest for email notification
        guest = await session.get(Guest, reservation.guest_id)

        if guest and guest.email:
            try:
                email_service = get_email_service()

                # Calculate refund amount for email
                refund_amount = 0
                if refund_payment:
                    refund_amount = abs(refund_payment.amount)

                email_service.send_auto_cancellation_email(
                    to_email=guest.email,
                    guest_name=f"{guest.first_name} {guest.last_name}",
                    booking_number=reservation.confirmation_code,
                    arrival_date=reservation.arrival_date.strftime("%B %d, %Y"),
                    refund_amount=refund_amount,
                    refund_percentage=int(refund_percentage * 100),
                    currency=refund_payment.currency if refund_payment else "INR"
                )
                logger.info(f"Sent auto-cancellation email to {guest.email}")
            except Exception as e:
                logger.error(f"Failed to send cancellation email: {str(e)}")

        await session.flush()

        logger.info(f"Successfully cancelled and refunded reservation {booking_id}")
        return cancelled_reservation, refund_payment

    except Exception as e:
        logger.error(f"Error in cancel_and_refund_booking for {booking_id}: {str(e)}")
        return None, None
