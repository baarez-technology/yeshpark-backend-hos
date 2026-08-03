"""
Paymaster API — Manage holding accounts for disputed or unassigned charges.
Charges can be parked in a paymaster and later transferred to a specific booking.
"""

from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.reservations import Booking
from app.models.operations import (
    Folio, FolioLineItem, PaymasterAccount, PaymasterPosting, AuditLog,
)
from app.core.tax import copy_tax_fields

router = APIRouter()


# --- Schemas ---

class CreatePaymasterRequest(BaseModel):
    account_name: str = "Paymaster"
    account_code: Optional[str] = None
    notes: Optional[str] = None


class UpdatePaymasterRequest(BaseModel):
    account_name: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class TransferFromPaymasterRequest(BaseModel):
    posting_ids: List[int]
    target_booking_id: int
    target_folio_id: Optional[int] = None
    notes: Optional[str] = None


def serialize_account(pm: PaymasterAccount) -> dict:
    return {
        "id": pm.id,
        "account_name": pm.account_name,
        "account_code": pm.account_code,
        "status": pm.status,
        "total_charges": pm.total_charges,
        "total_transferred": pm.total_transferred,
        "current_balance": pm.current_balance,
        "notes": pm.notes,
        "created_at": pm.created_at.isoformat() if pm.created_at else None,
    }


def serialize_posting(p: PaymasterPosting) -> dict:
    return {
        "id": p.id,
        "paymaster_account_id": p.paymaster_account_id,
        "posting_type": p.posting_type,
        "amount": p.amount,
        "balance_after": p.balance_after,
        "description": p.description,
        "source_booking_id": p.source_booking_id,
        "source_folio_id": p.source_folio_id,
        "target_booking_id": p.target_booking_id,
        "target_folio_id": p.target_folio_id,
        "posted_by": p.posted_by,
        "posted_at": p.posted_at.isoformat() if p.posted_at else None,
        "notes": p.notes,
    }


# --- Endpoints ---

@router.get("/accounts")
async def list_paymaster_accounts(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List all paymaster accounts."""
    query = select(PaymasterAccount)
    if status:
        query = query.where(PaymasterAccount.status == status)
    query = query.order_by(PaymasterAccount.created_at.desc()).limit(limit)
    results = (await session.exec(query)).all()
    return {"items": [serialize_account(pm) for pm in results]}


@router.post("/accounts", status_code=201)
async def create_paymaster_account(
    payload: CreatePaymasterRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new paymaster holding account."""
    pm = PaymasterAccount(
        account_name=payload.account_name,
        account_code=payload.account_code,
        notes=payload.notes,
        created_by=current_user.id,
    )
    session.add(pm)
    await session.commit()
    await session.refresh(pm)
    return serialize_account(pm)


@router.get("/accounts/{account_id}")
async def get_paymaster_account(
    account_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    pm = await session.get(PaymasterAccount, account_id)
    if not pm:
        raise HTTPException(404, "Paymaster account not found")
    return serialize_account(pm)


@router.put("/accounts/{account_id}")
async def update_paymaster_account(
    account_id: int,
    payload: UpdatePaymasterRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    pm = await session.get(PaymasterAccount, account_id)
    if not pm:
        raise HTTPException(404, "Paymaster account not found")

    for field in ("account_name", "status", "notes"):
        val = getattr(payload, field, None)
        if val is not None:
            setattr(pm, field, val)
    pm.updated_at = datetime.utcnow()

    session.add(pm)
    await session.commit()
    await session.refresh(pm)
    return serialize_account(pm)


@router.get("/accounts/{account_id}/postings")
async def list_paymaster_postings(
    account_id: int,
    posting_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List all postings for a paymaster account."""
    pm = await session.get(PaymasterAccount, account_id)
    if not pm:
        raise HTTPException(404, "Paymaster account not found")

    query = select(PaymasterPosting).where(
        PaymasterPosting.paymaster_account_id == account_id
    )
    if posting_type:
        query = query.where(PaymasterPosting.posting_type == posting_type)
    query = query.order_by(PaymasterPosting.posted_at.desc()).offset(offset).limit(limit)

    results = (await session.exec(query)).all()
    return {
        "account": serialize_account(pm),
        "postings": [serialize_posting(p) for p in results],
    }


@router.post("/accounts/{account_id}/transfer-to-booking")
async def transfer_from_paymaster(
    account_id: int,
    payload: TransferFromPaymasterRequest,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Transfer charges from paymaster to a booking's folio."""
    pm = await session.get(PaymasterAccount, account_id)
    if not pm:
        raise HTTPException(404, "Paymaster account not found")

    target_booking = await session.get(Booking, payload.target_booking_id)
    if not target_booking:
        raise HTTPException(404, "Target booking not found")
    if target_booking.status in ("checked_out", "cancelled", "no_show"):
        raise HTTPException(400, f"Target booking is {target_booking.status}")

    # Resolve target folio
    if payload.target_folio_id:
        target_folio = await session.get(Folio, payload.target_folio_id)
        if not target_folio or target_folio.booking_id != payload.target_booking_id:
            raise HTTPException(404, "Target folio not found on target booking")
    else:
        result = await session.exec(
            select(Folio).where(
                Folio.booking_id == payload.target_booking_id,
                Folio.status != "closed",
                Folio.folio_type == "guest",
            ).limit(1)
        )
        target_folio = result.first()
        if not target_folio:
            raise HTTPException(400, "No open folio on target booking")

    if target_folio.status == "closed":
        raise HTTPException(400, "Target folio is closed")

    transferred_count = 0
    total_amount = 0.0

    for posting_id in payload.posting_ids:
        posting = await session.get(PaymasterPosting, posting_id)
        if not posting or posting.paymaster_account_id != account_id:
            continue
        if posting.posting_type != "charge_in":
            continue  # Only transfer original charges

        # Create line item on target folio
        line = FolioLineItem(
            folio_id=target_folio.id,
            item_type="misc",
            description=f"[From Paymaster] {posting.description}",
            quantity=1,
            unit_price=posting.amount,
            amount=posting.amount,
            posted_by=current_user.id,
            source_booking_id=posting.source_booking_id,
            source_folio_id=posting.source_folio_id,
            original_line_item_id=posting.source_line_item_id,
            notes=payload.notes or f"Transferred from Paymaster '{pm.account_name}'",
        )
        session.add(line)

        # Mark paymaster posting as transferred
        pm.total_transferred = round(pm.total_transferred + posting.amount, 2)
        pm.current_balance = round(pm.total_charges - pm.total_transferred, 2)

        session.add(PaymasterPosting(
            paymaster_account_id=pm.id,
            posting_type="transfer_out",
            amount=-posting.amount,
            balance_after=pm.current_balance,
            description=f"Transferred to Booking #{payload.target_booking_id}: {posting.description}",
            target_booking_id=payload.target_booking_id,
            target_folio_id=target_folio.id,
            posted_by=current_user.id,
            notes=payload.notes,
        ))

        transferred_count += 1
        total_amount += posting.amount

    # Recalculate target folio
    from app.api.v1.folio import recalculate_folio, sync_booking_payment
    await recalculate_folio(session, target_folio)
    await sync_booking_payment(session, target_booking)

    # Audit
    session.add(AuditLog(
        user_id=current_user.id,
        action="transfer_from_paymaster",
        entity_type="paymaster",
        entity_id=pm.id,
        description=f"Transferred {transferred_count} charge(s) ({total_amount:.2f}) from Paymaster to Booking #{payload.target_booking_id}",
        old_value={"paymaster_id": pm.id, "posting_ids": payload.posting_ids},
        new_value={"target_booking_id": payload.target_booking_id, "amount": total_amount},
    ))

    await session.commit()
    return {
        "success": True,
        "message": f"Transferred {transferred_count} charge(s) ({total_amount:.2f}) to Booking #{payload.target_booking_id}",
        "paymaster_balance": pm.current_balance,
    }


@router.post("/accounts/{account_id}/write-off")
async def write_off_paymaster(
    account_id: int,
    amount: float = Query(..., description="Amount to write off"),
    reason: str = Query(...),
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Write off an amount from paymaster (lost/irrecoverable charges)."""
    pm = await session.get(PaymasterAccount, account_id)
    if not pm:
        raise HTTPException(404, "Paymaster account not found")
    if amount > pm.current_balance:
        raise HTTPException(400, f"Write-off amount exceeds balance ({pm.current_balance})")

    pm.total_transferred = round(pm.total_transferred + amount, 2)
    pm.current_balance = round(pm.total_charges - pm.total_transferred, 2)

    session.add(PaymasterPosting(
        paymaster_account_id=pm.id,
        posting_type="write_off",
        amount=-amount,
        balance_after=pm.current_balance,
        description=f"Write-off: {reason}",
        posted_by=current_user.id,
        notes=reason,
    ))

    await session.commit()
    return {
        "success": True,
        "message": f"Written off {amount:.2f}",
        "paymaster_balance": pm.current_balance,
    }
