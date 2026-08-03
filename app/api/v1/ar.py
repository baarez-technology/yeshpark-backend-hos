"""
Accounts Receivable (AR) Ledger API.
AR account management, ledger postings, payments, credit notes, aging report.
"""

import secrets
from datetime import datetime, date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.v1.auth import get_current_user
from app.models.ar import ARAccount, ARPosting
from app.models.bookings import CorporateAccounts
from app.models.user import User

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class ARAccountCreate(BaseModel):
    corporate_account_id: int
    account_name: str
    credit_limit: float = 0.0
    payment_terms_days: int = 30
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None


class ARAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    credit_limit: Optional[float] = None
    payment_terms_days: Optional[int] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class PostPaymentRequest(BaseModel):
    amount: float
    payment_method: str = "bank_transfer"
    reference_number: Optional[str] = None
    notes: Optional[str] = None


class CreditNoteRequest(BaseModel):
    amount: float
    description: str
    reference_number: Optional[str] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def generate_ar_number(corporate_code: str) -> str:
    return f"AR-{corporate_code}"


def serialize_ar_account(ar: ARAccount) -> dict:
    return {
        "id": ar.id,
        "corporate_account_id": ar.corporate_account_id,
        "account_name": ar.account_name,
        "account_number": ar.account_number,
        "credit_limit": ar.credit_limit,
        "current_balance": ar.current_balance,
        "available_credit": max(0, ar.credit_limit - ar.current_balance),
        "payment_terms_days": ar.payment_terms_days,
        "status": ar.status,
        "contact_name": ar.contact_name,
        "contact_email": ar.contact_email,
        "notes": ar.notes,
        "created_at": ar.created_at.isoformat() if ar.created_at else None,
        "updated_at": ar.updated_at.isoformat() if ar.updated_at else None,
    }


def serialize_posting(p: ARPosting) -> dict:
    return {
        "id": p.id,
        "ar_account_id": p.ar_account_id,
        "booking_id": p.booking_id,
        "folio_id": p.folio_id,
        "posting_type": p.posting_type,
        "amount": p.amount,
        "balance_after": p.balance_after,
        "description": p.description,
        "reference_number": p.reference_number,
        "posted_by": p.posted_by,
        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
        "due_date": str(p.due_date) if p.due_date else None,
        "paid_at": p.paid_at.isoformat() if p.paid_at else None,
        "status": p.status,
    }


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/accounts")
async def list_ar_accounts(
    status: Optional[str] = None,
    corporate_account_id: Optional[int] = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List AR accounts with optional filtering."""
    query = select(ARAccount)
    if status:
        query = query.where(ARAccount.status == status)
    if corporate_account_id:
        query = query.where(ARAccount.corporate_account_id == corporate_account_id)
    query = query.order_by(ARAccount.account_name)
    accounts = (await session.exec(query)).all()
    return {
        "success": True,
        "accounts": [serialize_ar_account(a) for a in accounts],
        "total": len(accounts),
    }


@router.post("/accounts")
async def create_ar_account(
    payload: ARAccountCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create an AR account (usually auto-created when corporate account is created)."""
    corp = await session.get(CorporateAccounts, payload.corporate_account_id)
    if not corp:
        raise HTTPException(404, "Corporate account not found")

    # Check if AR account already exists
    existing = (await session.exec(
        select(ARAccount).where(ARAccount.corporate_account_id == corp.id)
    )).first()
    if existing:
        raise HTTPException(400, "AR account already exists for this corporate account")

    ar_number = generate_ar_number(corp.account_code)
    ar = ARAccount(
        corporate_account_id=corp.id,
        account_name=payload.account_name,
        account_number=ar_number,
        credit_limit=payload.credit_limit,
        payment_terms_days=payload.payment_terms_days,
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
        notes=payload.notes,
    )
    session.add(ar)
    await session.commit()
    await session.refresh(ar)
    return {"success": True, "account": serialize_ar_account(ar)}


@router.get("/accounts/{account_id}")
async def get_ar_account(
    account_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get AR account with balance summary."""
    ar = await session.get(ARAccount, account_id)
    if not ar:
        raise HTTPException(404, "AR account not found")

    # Count postings
    postings = (await session.exec(
        select(ARPosting).where(ARPosting.ar_account_id == ar.id)
    )).all()
    total_charges = sum(p.amount for p in postings if p.posting_type == "charge")
    total_payments = sum(abs(p.amount) for p in postings if p.posting_type == "payment")
    total_credits = sum(abs(p.amount) for p in postings if p.posting_type == "credit_note")
    pending_count = sum(1 for p in postings if p.status == "pending")

    data = serialize_ar_account(ar)
    data["summary"] = {
        "total_charges": round(total_charges, 2),
        "total_payments": round(total_payments, 2),
        "total_credits": round(total_credits, 2),
        "posting_count": len(postings),
        "pending_count": pending_count,
    }
    return {"success": True, "account": data}


@router.put("/accounts/{account_id}")
async def update_ar_account(
    account_id: int,
    payload: ARAccountUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Update AR account details."""
    ar = await session.get(ARAccount, account_id)
    if not ar:
        raise HTTPException(404, "AR account not found")

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        if hasattr(ar, key):
            setattr(ar, key, value)
    ar.updated_at = datetime.utcnow()
    await session.commit()
    await session.refresh(ar)
    return {"success": True, "account": serialize_ar_account(ar)}


@router.get("/accounts/{account_id}/ledger")
async def get_ar_ledger(
    account_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    posting_type: Optional[str] = None,
    limit: int = Query(default=100, le=500),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Get all postings for an AR account (ledger view)."""
    ar = await session.get(ARAccount, account_id)
    if not ar:
        raise HTTPException(404, "AR account not found")

    query = select(ARPosting).where(ARPosting.ar_account_id == account_id)

    if start_date:
        try:
            sd = datetime.fromisoformat(start_date)
            query = query.where(ARPosting.posted_at >= sd)
        except ValueError:
            pass
    if end_date:
        try:
            ed = datetime.fromisoformat(end_date)
            query = query.where(ARPosting.posted_at <= ed)
        except ValueError:
            pass
    if posting_type:
        query = query.where(ARPosting.posting_type == posting_type)

    query = query.order_by(ARPosting.posted_at.desc()).offset(offset).limit(limit)
    postings = (await session.exec(query)).all()

    return {
        "success": True,
        "postings": [serialize_posting(p) for p in postings],
        "total": len(postings),
        "account": serialize_ar_account(ar),
    }


@router.post("/accounts/{account_id}/post-payment")
async def post_ar_payment(
    account_id: int,
    payload: PostPaymentRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Record a payment against an AR account."""
    ar = await session.get(ARAccount, account_id)
    if not ar:
        raise HTTPException(404, "AR account not found")

    if payload.amount <= 0:
        raise HTTPException(400, "Payment amount must be positive")

    new_balance = round(ar.current_balance - payload.amount, 2)

    posting = ARPosting(
        ar_account_id=ar.id,
        posting_type="payment",
        amount=-payload.amount,  # Payments are negative
        balance_after=new_balance,
        description=f"Payment received via {payload.payment_method}",
        reference_number=payload.reference_number,
        posted_by=current_user.id,
        status="paid",
        paid_at=datetime.utcnow(),
    )
    session.add(posting)

    ar.current_balance = new_balance
    ar.updated_at = datetime.utcnow()

    # Mark oldest pending postings as paid (FIFO)
    remaining = payload.amount
    pending_postings = (await session.exec(
        select(ARPosting).where(
            ARPosting.ar_account_id == ar.id,
            ARPosting.posting_type == "charge",
            ARPosting.status == "pending",
        ).order_by(ARPosting.posted_at)
    )).all()

    for pp in pending_postings:
        if remaining <= 0:
            break
        if pp.amount <= remaining:
            pp.status = "paid"
            pp.paid_at = datetime.utcnow()
            remaining -= pp.amount
        else:
            # Partial payment — leave as pending
            remaining = 0

    await session.commit()
    await session.refresh(ar)

    return {
        "success": True,
        "message": f"Payment of {payload.amount:.2f} recorded",
        "account": serialize_ar_account(ar),
    }


@router.post("/accounts/{account_id}/credit-note")
async def post_credit_note(
    account_id: int,
    payload: CreditNoteRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Issue a credit note against an AR account."""
    ar = await session.get(ARAccount, account_id)
    if not ar:
        raise HTTPException(404, "AR account not found")

    if payload.amount <= 0:
        raise HTTPException(400, "Credit note amount must be positive")

    new_balance = round(ar.current_balance - payload.amount, 2)
    ref = payload.reference_number or f"CN-{secrets.token_urlsafe(4).upper()[:6]}"

    posting = ARPosting(
        ar_account_id=ar.id,
        posting_type="credit_note",
        amount=-payload.amount,
        balance_after=new_balance,
        description=payload.description,
        reference_number=ref,
        posted_by=current_user.id,
        status="paid",
    )
    session.add(posting)

    ar.current_balance = new_balance
    ar.updated_at = datetime.utcnow()

    await session.commit()
    await session.refresh(ar)

    return {
        "success": True,
        "message": f"Credit note of {payload.amount:.2f} issued",
        "account": serialize_ar_account(ar),
    }


@router.get("/accounts/{account_id}/statement")
async def get_ar_statement(
    account_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Generate an AR statement for a date range."""
    ar = await session.get(ARAccount, account_id)
    if not ar:
        raise HTTPException(404, "AR account not found")

    corp = await session.get(CorporateAccounts, ar.corporate_account_id)

    query = select(ARPosting).where(ARPosting.ar_account_id == account_id)
    if start_date:
        try:
            query = query.where(ARPosting.posted_at >= datetime.fromisoformat(start_date))
        except ValueError:
            pass
    if end_date:
        try:
            query = query.where(ARPosting.posted_at <= datetime.fromisoformat(end_date))
        except ValueError:
            pass
    query = query.order_by(ARPosting.posted_at)
    postings = (await session.exec(query)).all()

    timeline = []
    for p in postings:
        is_debit = p.amount > 0
        timeline.append({
            "date": p.posted_at.isoformat() if p.posted_at else None,
            "type": p.posting_type,
            "description": p.description,
            "reference": p.reference_number,
            "debit": p.amount if is_debit else 0,
            "credit": abs(p.amount) if not is_debit else 0,
            "balance": p.balance_after,
            "status": p.status,
        })

    return {
        "success": True,
        "statement": {
            "account": serialize_ar_account(ar),
            "company": {
                "name": corp.company_name if corp else ar.account_name,
                "address": corp.billing_address if corp else None,
                "tax_id": corp.tax_id if corp else None,
            },
            "period": {"start": start_date, "end": end_date},
            "opening_balance": timeline[0]["balance"] - timeline[0]["debit"] + timeline[0]["credit"] if timeline else 0,
            "closing_balance": ar.current_balance,
            "timeline": timeline,
        },
    }


@router.get("/aging-report")
async def get_aging_report(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Generate AR aging report across all active accounts."""
    accounts = (await session.exec(
        select(ARAccount).where(ARAccount.status == "active")
    )).all()

    today = date.today()
    report_items = []

    for ar in accounts:
        pending = (await session.exec(
            select(ARPosting).where(
                ARPosting.ar_account_id == ar.id,
                ARPosting.posting_type == "charge",
                ARPosting.status == "pending",
            )
        )).all()

        buckets = {"current": 0, "days_30": 0, "days_60": 0, "days_90": 0, "days_90_plus": 0}
        for p in pending:
            age = (today - p.posted_at.date()).days if p.posted_at else 0
            if age <= 30:
                buckets["current"] += p.amount
            elif age <= 60:
                buckets["days_30"] += p.amount
            elif age <= 90:
                buckets["days_60"] += p.amount
            else:
                buckets["days_90_plus"] += p.amount

        if ar.current_balance > 0 or any(v > 0 for v in buckets.values()):
            report_items.append({
                "account_id": ar.id,
                "account_name": ar.account_name,
                "account_number": ar.account_number,
                "total_outstanding": ar.current_balance,
                "credit_limit": ar.credit_limit,
                **{k: round(v, 2) for k, v in buckets.items()},
            })

    totals = {
        "current": round(sum(r["current"] for r in report_items), 2),
        "days_30": round(sum(r["days_30"] for r in report_items), 2),
        "days_60": round(sum(r["days_60"] for r in report_items), 2),
        "days_90": round(sum(r["days_90"] for r in report_items), 2),
        "days_90_plus": round(sum(r["days_90_plus"] for r in report_items), 2),
        "total": round(sum(r["total_outstanding"] for r in report_items), 2),
    }

    return {
        "success": True,
        "aging_report": {
            "items": report_items,
            "totals": totals,
            "generated_at": datetime.utcnow().isoformat(),
        },
    }
