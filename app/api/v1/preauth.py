"""
Pre-authorization / card hold API endpoints.
Holds are created at check-in and released at checkout.
"""

import secrets
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.v1.auth import get_current_user
from app.models.reservations import Booking
from app.models.operations import AuthorizationHold, Folio, HotelConfig
from app.models.user import User

router = APIRouter()


# ─── Schemas ────────────────────────────────────────────────────────────────────

class CreateHoldRequest(BaseModel):
    booking_id: int
    hold_amount: Optional[float] = None  # If omitted, auto-calculates from hotel config
    card_last4: Optional[str] = None
    card_brand: Optional[str] = None
    notes: Optional[str] = None


class ReleaseHoldRequest(BaseModel):
    release_reason: str = "checkout"


class CaptureHoldRequest(BaseModel):
    capture_amount: Optional[float] = None  # If omitted, captures full hold amount
    notes: Optional[str] = None


# ─── Helper ─────────────────────────────────────────────────────────────────────

async def calculate_hold_amount(session: AsyncSession, booking: Booking) -> float:
    """Calculate hold amount: incidental_hold_pct × rate_per_night × nights"""
    config = (await session.exec(select(HotelConfig))).first()
    pct = config.incidental_hold_pct if config else 20.0

    nights = max(1, booking.nights or 1)
    nightly_rate = (booking.base_price or 0) / nights if nights > 0 else 0
    return round(nightly_rate * nights * pct / 100, 2)


def serialize_hold(h: AuthorizationHold) -> dict:
    return {
        "id": h.id,
        "booking_id": h.booking_id,
        "folio_id": h.folio_id,
        "hold_amount": h.hold_amount,
        "card_last4": h.card_last4,
        "card_brand": h.card_brand,
        "authorization_code": h.authorization_code,
        "status": h.status,
        "authorized_at": h.authorized_at.isoformat() if h.authorized_at else None,
        "authorized_by": h.authorized_by,
        "released_at": h.released_at.isoformat() if h.released_at else None,
        "released_by": h.released_by,
        "release_reason": h.release_reason,
        "expires_at": h.expires_at.isoformat() if h.expires_at else None,
        "notes": h.notes,
        "created_at": h.created_at.isoformat() if h.created_at else None,
    }


# ─── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/holds")
async def list_holds(
    booking_id: Optional[int] = None,
    hold_status: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List authorization holds, optionally filtered by booking or status."""
    query = select(AuthorizationHold)
    if booking_id:
        query = query.where(AuthorizationHold.booking_id == booking_id)
    if hold_status:
        query = query.where(AuthorizationHold.status == hold_status)
    query = query.order_by(AuthorizationHold.created_at.desc())

    holds = (await session.exec(query)).all()
    return {"success": True, "holds": [serialize_hold(h) for h in holds]}


@router.post("/holds", status_code=status.HTTP_201_CREATED)
async def create_hold(
    payload: CreateHoldRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a pre-authorization hold for a booking."""
    booking = await session.get(Booking, payload.booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    # Check for existing active hold
    existing = (await session.exec(
        select(AuthorizationHold).where(
            AuthorizationHold.booking_id == payload.booking_id,
            AuthorizationHold.status == "authorized",
        )
    )).first()
    if existing:
        raise HTTPException(400, f"Active hold already exists (ID: {existing.id}, amount: {existing.hold_amount})")

    # Calculate amount
    amount = payload.hold_amount
    if not amount or amount <= 0:
        amount = await calculate_hold_amount(session, booking)

    # Get primary folio
    folio = (await session.exec(
        select(Folio).where(Folio.booking_id == booking.id).order_by(Folio.window_label)
    )).first()

    hold = AuthorizationHold(
        booking_id=booking.id,
        folio_id=folio.id if folio else None,
        hold_amount=amount,
        card_last4=payload.card_last4,
        card_brand=payload.card_brand,
        authorization_code=f"AUTH-{secrets.token_hex(4).upper()}",
        status="authorized",
        authorized_by=current_user.id,
        expires_at=datetime.utcnow() + timedelta(days=7),
        notes=payload.notes,
    )
    session.add(hold)
    await session.commit()
    await session.refresh(hold)

    return {"success": True, "hold": serialize_hold(hold)}


@router.get("/holds/{hold_id}")
async def get_hold(
    hold_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get a specific authorization hold."""
    hold = await session.get(AuthorizationHold, hold_id)
    if not hold:
        raise HTTPException(404, "Hold not found")
    return {"success": True, "hold": serialize_hold(hold)}


@router.post("/holds/{hold_id}/release")
async def release_hold(
    hold_id: int,
    payload: ReleaseHoldRequest = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Release (void) an authorization hold."""
    hold = await session.get(AuthorizationHold, hold_id)
    if not hold:
        raise HTTPException(404, "Hold not found")
    if hold.status != "authorized":
        raise HTTPException(400, f"Hold cannot be released (status: {hold.status})")

    hold.status = "released"
    hold.released_at = datetime.utcnow()
    hold.released_by = current_user.id
    hold.release_reason = payload.release_reason if payload else "checkout"

    await session.commit()
    return {"success": True, "message": "Hold released", "hold": serialize_hold(hold)}


@router.post("/holds/{hold_id}/capture")
async def capture_hold(
    hold_id: int,
    payload: CaptureHoldRequest = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Capture (convert to payment) an authorization hold."""
    hold = await session.get(AuthorizationHold, hold_id)
    if not hold:
        raise HTTPException(404, "Hold not found")
    if hold.status != "authorized":
        raise HTTPException(400, f"Hold cannot be captured (status: {hold.status})")

    capture_amount = hold.hold_amount
    if payload and payload.capture_amount and payload.capture_amount > 0:
        if payload.capture_amount > hold.hold_amount:
            raise HTTPException(400, f"Capture amount ({payload.capture_amount}) exceeds hold ({hold.hold_amount})")
        capture_amount = payload.capture_amount

    hold.status = "captured"
    hold.released_at = datetime.utcnow()
    hold.released_by = current_user.id
    hold.release_reason = "captured"
    if payload and payload.notes:
        hold.notes = payload.notes

    await session.commit()
    return {
        "success": True,
        "message": f"Hold captured for {capture_amount:.2f}",
        "hold": serialize_hold(hold),
        "captured_amount": capture_amount,
    }
