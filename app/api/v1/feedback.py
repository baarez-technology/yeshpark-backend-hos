"""
Checkout Feedback API
Handles post-stay guest feedback submissions
"""
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlmodel import select

from app.db.session import get_tenant_session
from app.models.checkout_feedback import CheckoutFeedback
from app.models.reservations import Reservation, Guest

router = APIRouter()


class FeedbackSubmission(BaseModel):
    """Feedback submission from the frontend"""
    reservation_id: int
    overall_rating: int  # 1-5
    cleanliness_rating: Optional[int] = None
    comfort_rating: Optional[int] = None
    staff_rating: Optional[int] = None
    location_rating: Optional[int] = None
    amenities_rating: Optional[int] = None
    value_rating: Optional[int] = None
    dining_rating: Optional[int] = None
    checkin_rating: Optional[int] = None
    quick_tags: Optional[List[str]] = None
    would_recommend: Optional[bool] = None
    comments: Optional[str] = None


class FeedbackResponse(BaseModel):
    """Response after submitting feedback"""
    success: bool
    message: str
    feedback_id: Optional[int] = None


class BookingDetailsResponse(BaseModel):
    """Booking details for the feedback page"""
    reservation_id: int
    guest_name: str
    room_type: str
    room_number: Optional[str] = None
    check_in: str
    check_out: str
    nights: int
    already_submitted: bool = False


@router.post("/submit", response_model=FeedbackResponse)
async def submit_feedback(
    submission: FeedbackSubmission,
    request: Request
):
    """
    Submit post-checkout feedback
    """
    async with get_tenant_session() as session:
        # Verify the reservation exists
        result = await session.execute(
            select(Reservation).where(Reservation.id == submission.reservation_id)
        )
        reservation = result.scalar_one_or_none()

        if not reservation:
            raise HTTPException(status_code=404, detail="Reservation not found")

        # Check if feedback already exists for this reservation
        existing = await session.execute(
            select(CheckoutFeedback).where(
                CheckoutFeedback.reservation_id == submission.reservation_id
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail="Feedback has already been submitted for this reservation"
            )

        # Get client info
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")

        # Create feedback record
        feedback = CheckoutFeedback(
            reservation_id=submission.reservation_id,
            guest_id=reservation.guest_id,
            overall_rating=submission.overall_rating,
            cleanliness_rating=submission.cleanliness_rating,
            comfort_rating=submission.comfort_rating,
            staff_rating=submission.staff_rating,
            location_rating=submission.location_rating,
            amenities_rating=submission.amenities_rating,
            value_rating=submission.value_rating,
            dining_rating=submission.dining_rating,
            checkin_rating=submission.checkin_rating,
            quick_tags=submission.quick_tags,
            would_recommend=submission.would_recommend,
            comments=submission.comments,
            submitted_via="email_link",
            ip_address=client_ip,
            user_agent=user_agent[:500] if user_agent else None,  # Limit length
        )

        session.add(feedback)
        await session.commit()
        await session.refresh(feedback)

        return FeedbackResponse(
            success=True,
            message="Thank you for your feedback!",
            feedback_id=feedback.id
        )


@router.get("/booking/{reservation_id}", response_model=BookingDetailsResponse)
async def get_booking_for_feedback(reservation_id: int):
    """
    Get booking details for the feedback form
    """
    async with get_tenant_session() as session:
        # Get reservation with guest info
        result = await session.execute(
            select(Reservation).where(Reservation.id == reservation_id)
        )
        reservation = result.scalar_one_or_none()

        if not reservation:
            raise HTTPException(status_code=404, detail="Reservation not found")

        # Get guest info
        guest_result = await session.execute(
            select(Guest).where(Guest.id == reservation.guest_id)
        )
        guest = guest_result.scalar_one_or_none()

        # Check if feedback already submitted
        existing = await session.execute(
            select(CheckoutFeedback).where(
                CheckoutFeedback.reservation_id == reservation_id
            )
        )
        already_submitted = existing.scalar_one_or_none() is not None

        # Calculate nights
        nights = 1
        if reservation.check_in_date and reservation.check_out_date:
            nights = (reservation.check_out_date - reservation.check_in_date).days

        return BookingDetailsResponse(
            reservation_id=reservation.id,
            guest_name=f"{guest.first_name} {guest.last_name}" if guest else "Guest",
            room_type=reservation.room_type or "Standard Room",
            room_number=reservation.room_number,
            check_in=reservation.check_in_date.isoformat() if reservation.check_in_date else "",
            check_out=reservation.check_out_date.isoformat() if reservation.check_out_date else "",
            nights=nights,
            already_submitted=already_submitted
        )


@router.get("/check/{reservation_id}")
async def check_feedback_status(reservation_id: int):
    """
    Check if feedback has already been submitted for a reservation
    """
    async with get_tenant_session() as session:
        result = await session.execute(
            select(CheckoutFeedback).where(
                CheckoutFeedback.reservation_id == reservation_id
            )
        )
        feedback = result.scalar_one_or_none()

        return {
            "reservation_id": reservation_id,
            "submitted": feedback is not None,
            "submitted_at": feedback.created_at.isoformat() if feedback else None
        }
