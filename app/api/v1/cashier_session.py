"""
Cashier Session API — Open/close cash register sessions per staff member.
Tracks cash float, payments received, variance on close.
"""

from datetime import datetime, date
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.operations import CashierSession
from app.core.business_date import get_business_date

router = APIRouter()


# --- Schemas ---

class OpenSessionRequest(BaseModel):
    opening_balance: float = 0.0
    workstation_id: Optional[str] = None
    notes: Optional[str] = None


class CloseSessionRequest(BaseModel):
    closing_balance: float  # Actual cash counted
    notes: Optional[str] = None


def serialize_session(s: CashierSession) -> dict:
    return {
        "id": s.id,
        "staff_id": s.staff_id,
        "workstation_id": s.workstation_id,
        "session_date": str(s.session_date) if s.session_date else None,
        "status": s.status,
        "opening_balance": s.opening_balance,
        "closing_balance": s.closing_balance,
        "expected_balance": s.expected_balance,
        "cash_received": s.cash_received,
        "cash_paid_out": s.cash_paid_out,
        "variance": s.variance,
        "transaction_count": s.transaction_count,
        "opened_at": s.opened_at.isoformat() if s.opened_at else None,
        "closed_at": s.closed_at.isoformat() if s.closed_at else None,
        "notes": s.notes,
    }


# --- Endpoints ---

@router.get("")
async def list_sessions(
    status: Optional[str] = None,
    staff_id: Optional[int] = None,
    session_date: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List cashier sessions with optional filters."""
    query = select(CashierSession)
    if status:
        query = query.where(CashierSession.status == status)
    if staff_id:
        query = query.where(CashierSession.staff_id == staff_id)
    if session_date:
        query = query.where(CashierSession.session_date == session_date)
    query = query.order_by(CashierSession.opened_at.desc()).limit(limit)
    results = (await session.exec(query)).all()
    return {"items": [serialize_session(s) for s in results]}


@router.post("", status_code=201)
async def open_session(
    payload: OpenSessionRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Open a new cashier session. Only one open session per staff at a time."""
    # Check for existing open session
    existing = (await session.exec(
        select(CashierSession).where(
            CashierSession.staff_id == current_user.id,
            CashierSession.status == "open",
        )
    )).first()
    if existing:
        raise HTTPException(400, f"You already have an open cashier session (ID: {existing.id})")

    biz_date = await get_business_date(session)
    cs = CashierSession(
        staff_id=current_user.id,
        workstation_id=payload.workstation_id,
        session_date=biz_date,
        opening_balance=payload.opening_balance,
        expected_balance=payload.opening_balance,
        notes=payload.notes,
    )
    session.add(cs)
    await session.commit()
    await session.refresh(cs)
    return serialize_session(cs)


@router.get("/my-session")
async def get_my_session(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get the current user's open cashier session (if any)."""
    result = (await session.exec(
        select(CashierSession).where(
            CashierSession.staff_id == current_user.id,
            CashierSession.status == "open",
        )
    )).first()
    if not result:
        return {"session": None}
    return {"session": serialize_session(result)}


@router.get("/{session_id}")
async def get_session_detail(
    session_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    cs = await session.get(CashierSession, session_id)
    if not cs:
        raise HTTPException(404, "Cashier session not found")
    return serialize_session(cs)


@router.post("/{session_id}/close")
async def close_session(
    session_id: int,
    payload: CloseSessionRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Close a cashier session with cash count reconciliation."""
    cs = await session.get(CashierSession, session_id)
    if not cs:
        raise HTTPException(404, "Cashier session not found")
    if cs.status != "open":
        raise HTTPException(400, "Session is already closed")

    cs.closing_balance = payload.closing_balance
    cs.expected_balance = round(cs.opening_balance + cs.cash_received - cs.cash_paid_out, 2)
    cs.variance = round(payload.closing_balance - cs.expected_balance, 2)
    cs.status = "closed"
    cs.closed_at = datetime.utcnow()
    cs.closed_by = current_user.id
    if payload.notes:
        cs.notes = (cs.notes or "") + f"\nClose: {payload.notes}"

    session.add(cs)
    await session.commit()
    await session.refresh(cs)
    return serialize_session(cs)


@router.post("/{session_id}/record-cash")
async def record_cash_transaction(
    session_id: int,
    amount: float = Query(..., description="Positive=received, negative=paid out"),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Record a cash transaction against the session (called automatically on cash payments)."""
    cs = await session.get(CashierSession, session_id)
    if not cs:
        raise HTTPException(404, "Cashier session not found")
    if cs.status != "open":
        raise HTTPException(400, "Cannot record transactions on a closed session")

    if amount > 0:
        cs.cash_received = round(cs.cash_received + amount, 2)
    else:
        cs.cash_paid_out = round(cs.cash_paid_out + abs(amount), 2)
    cs.transaction_count += 1
    cs.expected_balance = round(cs.opening_balance + cs.cash_received - cs.cash_paid_out, 2)

    session.add(cs)
    await session.commit()
    return {"success": True, "expected_balance": cs.expected_balance, "transaction_count": cs.transaction_count}


@router.get("/open-sessions/check")
async def check_open_sessions(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Check if there are any open cashier sessions (used by night audit pre-flight)."""
    results = (await session.exec(
        select(CashierSession).where(CashierSession.status == "open")
    )).all()
    return {
        "open_count": len(results),
        "sessions": [{"id": s.id, "staff_id": s.staff_id, "workstation_id": s.workstation_id, "session_date": str(s.session_date)} for s in results],
    }
