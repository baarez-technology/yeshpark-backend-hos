"""
Corporate Account Management API.
CRUD for corporate accounts + booking linkage.
"""

import secrets
from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.v1.auth import get_current_user
from app.models.bookings import CorporateAccounts
from app.models.reservations import Booking
from app.models.ar import ARAccount
from app.models.user import User

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class CorporateAccountCreate(BaseModel):
    company_name: str
    account_code: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    billing_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    zip_code: Optional[str] = None
    tax_id: Optional[str] = None
    discount_percentage: Optional[float] = None
    credit_limit: Optional[float] = None
    payment_terms: Optional[str] = None
    contract_start_date: Optional[str] = None
    contract_end_date: Optional[str] = None
    rate_plan_id: Optional[int] = None
    notes: Optional[str] = None


class CorporateAccountUpdate(BaseModel):
    company_name: Optional[str] = None
    account_code: Optional[str] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    billing_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    zip_code: Optional[str] = None
    tax_id: Optional[str] = None
    discount_percentage: Optional[float] = None
    credit_limit: Optional[float] = None
    payment_terms: Optional[str] = None
    contract_start_date: Optional[str] = None
    contract_end_date: Optional[str] = None
    rate_plan_id: Optional[int] = None
    status: Optional[str] = None
    notes: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def generate_account_code() -> str:
    return f"CORP-{secrets.token_urlsafe(4).upper().replace('_', '').replace('-', '')[:6]}"


def serialize_account(acct: CorporateAccounts, ar_balance: float = 0.0) -> dict:
    return {
        "id": acct.id,
        "account_code": acct.account_code,
        "company_name": acct.company_name,
        "contact_name": acct.contact_name,
        "contact_email": acct.contact_email,
        "contact_phone": acct.contact_phone,
        "billing_address": acct.billing_address,
        "city": acct.city,
        "state": acct.state,
        "country": acct.country,
        "zip_code": acct.zip_code,
        "tax_id": acct.tax_id,
        "discount_percentage": acct.discount_percentage,
        "credit_limit": acct.credit_limit,
        "payment_terms": acct.payment_terms,
        "contract_start_date": str(acct.contract_start_date) if acct.contract_start_date else None,
        "contract_end_date": str(acct.contract_end_date) if acct.contract_end_date else None,
        "rate_plan_id": acct.rate_plan_id,
        "total_bookings": acct.total_bookings,
        "total_revenue": acct.total_revenue,
        "ar_balance": ar_balance,
        "status": acct.status,
        "notes": acct.notes,
        "created_at": acct.created_at.isoformat() if acct.created_at else None,
        "updated_at": acct.updated_at.isoformat() if acct.updated_at else None,
    }


async def get_ar_balance(session: AsyncSession, corporate_id: int) -> float:
    """Get total AR balance for a corporate account."""
    result = await session.exec(
        select(ARAccount).where(
            ARAccount.corporate_account_id == corporate_id,
            ARAccount.status == "active"
        )
    )
    ar = result.first()
    return ar.current_balance if ar else 0.0


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/accounts")
async def list_corporate_accounts(
    status: Optional[str] = None,
    search: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List all corporate accounts with optional filtering."""
    query = select(CorporateAccounts)
    if status:
        query = query.where(CorporateAccounts.status == status)
    if search:
        query = query.where(
            col(CorporateAccounts.company_name).contains(search)
            | col(CorporateAccounts.account_code).contains(search)
        )
    query = query.order_by(CorporateAccounts.company_name)
    accounts = (await session.exec(query)).all()

    items = []
    for acct in accounts:
        ar_bal = await get_ar_balance(session, acct.id)
        items.append(serialize_account(acct, ar_bal))

    return {"success": True, "accounts": items, "total": len(items)}


@router.post("/accounts")
async def create_corporate_account(
    payload: CorporateAccountCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new corporate account and auto-create its AR account."""
    code = payload.account_code or generate_account_code()

    # Check for duplicate account_code
    existing = (await session.exec(
        select(CorporateAccounts).where(CorporateAccounts.account_code == code)
    )).first()
    if existing:
        raise HTTPException(400, f"Account code '{code}' already exists")

    acct = CorporateAccounts(
        account_code=code,
        company_name=payload.company_name,
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
        billing_address=payload.billing_address,
        city=payload.city,
        state=payload.state,
        country=payload.country,
        zip_code=payload.zip_code,
        tax_id=payload.tax_id,
        discount_percentage=payload.discount_percentage,
        credit_limit=payload.credit_limit,
        payment_terms=payload.payment_terms,
        rate_plan_id=payload.rate_plan_id,
        notes=payload.notes,
    )
    # Parse dates if provided
    from datetime import date as date_type
    if payload.contract_start_date:
        try:
            acct.contract_start_date = date_type.fromisoformat(payload.contract_start_date)
        except ValueError:
            pass
    if payload.contract_end_date:
        try:
            acct.contract_end_date = date_type.fromisoformat(payload.contract_end_date)
        except ValueError:
            pass

    session.add(acct)
    await session.flush()

    # Auto-create AR account
    ar_number = f"AR-{code}"
    ar = ARAccount(
        corporate_account_id=acct.id,
        account_name=acct.company_name,
        account_number=ar_number,
        credit_limit=acct.credit_limit or 0.0,
        payment_terms_days=int(acct.payment_terms) if acct.payment_terms and acct.payment_terms.isdigit() else 30,
        contact_name=acct.contact_name,
        contact_email=acct.contact_email,
    )
    session.add(ar)
    await session.commit()
    await session.refresh(acct)

    return {"success": True, "account": serialize_account(acct)}


@router.get("/accounts/{account_id}")
async def get_corporate_account(
    account_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get a single corporate account with summary stats."""
    acct = await session.get(CorporateAccounts, account_id)
    if not acct:
        raise HTTPException(404, "Corporate account not found")
    ar_bal = await get_ar_balance(session, acct.id)
    return {"success": True, "account": serialize_account(acct, ar_bal)}


@router.put("/accounts/{account_id}")
async def update_corporate_account(
    account_id: int,
    payload: CorporateAccountUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update a corporate account."""
    acct = await session.get(CorporateAccounts, account_id)
    if not acct:
        raise HTTPException(404, "Corporate account not found")

    data = payload.model_dump(exclude_unset=True)

    # Parse dates if provided
    from datetime import date as date_type
    for date_field in ("contract_start_date", "contract_end_date"):
        if date_field in data and data[date_field]:
            try:
                data[date_field] = date_type.fromisoformat(data[date_field])
            except ValueError:
                del data[date_field]

    for key, value in data.items():
        if hasattr(acct, key):
            setattr(acct, key, value)
    acct.updated_at = datetime.utcnow()

    # Sync credit_limit to AR account if changed
    if "credit_limit" in data:
        ar_result = await session.exec(
            select(ARAccount).where(ARAccount.corporate_account_id == acct.id)
        )
        ar = ar_result.first()
        if ar:
            ar.credit_limit = acct.credit_limit or 0.0

    await session.commit()
    await session.refresh(acct)
    ar_bal = await get_ar_balance(session, acct.id)
    return {"success": True, "account": serialize_account(acct, ar_bal)}


@router.delete("/accounts/{account_id}")
async def delete_corporate_account(
    account_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Soft-delete a corporate account (set status=inactive)."""
    acct = await session.get(CorporateAccounts, account_id)
    if not acct:
        raise HTTPException(404, "Corporate account not found")
    acct.status = "inactive"
    acct.updated_at = datetime.utcnow()

    # Also suspend the AR account
    ar_result = await session.exec(
        select(ARAccount).where(ARAccount.corporate_account_id == acct.id)
    )
    ar = ar_result.first()
    if ar:
        ar.status = "suspended"
        ar.updated_at = datetime.utcnow()

    await session.commit()
    return {"success": True, "message": f"Corporate account '{acct.company_name}' deactivated"}


@router.get("/accounts/{account_id}/bookings")
async def list_corporate_bookings(
    account_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List bookings linked to a corporate account."""
    acct = await session.get(CorporateAccounts, account_id)
    if not acct:
        raise HTTPException(404, "Corporate account not found")

    bookings = (await session.exec(
        select(Booking).where(Booking.corporate_account_id == account_id)
            .order_by(Booking.created_at.desc())
    )).all()

    items = []
    for b in bookings:
        items.append({
            "id": b.id,
            "booking_number": b.booking_number,
            "guest_id": b.guest_id,
            "status": b.status,
            "arrival_date": str(b.arrival_date) if b.arrival_date else None,
            "departure_date": str(b.departure_date) if b.departure_date else None,
            "total_price": b.total_price,
            "payment_status": b.payment_status,
        })

    return {"success": True, "bookings": items, "total": len(items)}


@router.post("/accounts/{account_id}/link-booking/{booking_id}")
async def link_booking_to_corporate(
    account_id: int,
    booking_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Link an existing booking to a corporate account."""
    acct = await session.get(CorporateAccounts, account_id)
    if not acct:
        raise HTTPException(404, "Corporate account not found")

    booking = await session.get(Booking, booking_id)
    if not booking:
        raise HTTPException(404, "Booking not found")

    if booking.corporate_account_id == account_id:
        return {"success": True, "message": "Booking already linked to this account"}

    booking.corporate_account_id = account_id
    acct.total_bookings = (acct.total_bookings or 0) + 1
    acct.total_revenue = round((acct.total_revenue or 0) + (booking.total_price or 0), 2)
    acct.updated_at = datetime.utcnow()

    await session.commit()
    return {"success": True, "message": f"Booking #{booking.booking_number} linked to {acct.company_name}"}
