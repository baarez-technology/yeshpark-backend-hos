"""
Transaction Codes API — Opera-style numeric codes for charge/payment categories.
Each code maps to a FolioLineItem.item_type and has a matching adjustment code.
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.operations import TransactionCode

router = APIRouter()


# --- Schemas ---

class TransactionCodeCreate(BaseModel):
    code: str
    name: str
    category: str  # Maps to FolioLineItem.item_type
    code_type: str = "charge"  # charge, payment, adjustment, tax
    adjustment_code: Optional[str] = None
    department: Optional[str] = None
    sort_order: int = 0


class TransactionCodeUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    code_type: Optional[str] = None
    adjustment_code: Optional[str] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


def serialize_tc(tc: TransactionCode) -> dict:
    return {
        "id": tc.id,
        "code": tc.code,
        "name": tc.name,
        "category": tc.category,
        "code_type": tc.code_type,
        "adjustment_code": tc.adjustment_code,
        "department": tc.department,
        "is_active": tc.is_active,
        "sort_order": tc.sort_order,
    }


# --- Endpoints ---

@router.get("")
async def list_transaction_codes(
    code_type: Optional[str] = None,
    category: Optional[str] = None,
    active_only: bool = True,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """List all transaction codes with optional filters."""
    query = select(TransactionCode)
    if code_type:
        query = query.where(TransactionCode.code_type == code_type)
    if category:
        query = query.where(TransactionCode.category == category)
    if active_only:
        query = query.where(TransactionCode.is_active == True)
    query = query.order_by(TransactionCode.sort_order, TransactionCode.code)

    results = (await session.exec(query)).all()
    return {"items": [serialize_tc(tc) for tc in results]}


@router.post("", status_code=201)
async def create_transaction_code(
    payload: TransactionCodeCreate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Create a new transaction code."""
    # Check duplicate code
    existing = (await session.exec(
        select(TransactionCode).where(TransactionCode.code == payload.code)
    )).first()
    if existing:
        raise HTTPException(400, f"Transaction code '{payload.code}' already exists")

    tc = TransactionCode(**payload.model_dump())
    session.add(tc)
    await session.commit()
    await session.refresh(tc)
    return serialize_tc(tc)


@router.get("/{code_id}")
async def get_transaction_code(
    code_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    tc = await session.get(TransactionCode, code_id)
    if not tc:
        raise HTTPException(404, "Transaction code not found")
    return serialize_tc(tc)


@router.put("/{code_id}")
async def update_transaction_code(
    code_id: int,
    payload: TransactionCodeUpdate,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    tc = await session.get(TransactionCode, code_id)
    if not tc:
        raise HTTPException(404, "Transaction code not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tc, field, value)
    session.add(tc)
    await session.commit()
    await session.refresh(tc)
    return serialize_tc(tc)


@router.delete("/{code_id}")
async def delete_transaction_code(
    code_id: int,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    tc = await session.get(TransactionCode, code_id)
    if not tc:
        raise HTTPException(404, "Transaction code not found")
    tc.is_active = False
    session.add(tc)
    await session.commit()
    return {"success": True, "message": f"Transaction code {tc.code} deactivated"}


@router.post("/seed")
async def seed_transaction_codes(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Seed default Opera-style transaction codes. Safe to re-run — skips existing codes."""
    defaults = [
        # Charge codes (1000-series = Room, 2000-series = F&B, 3000-series = Incidentals)
        ("1000", "Room Charge", "room_charge", "charge", "1001", "Rooms", 100),
        ("1001", "Room Charge Adjustment", "room_charge", "adjustment", None, "Rooms", 101),
        ("2000", "Minibar", "minibar", "charge", "2001", "F&B", 200),
        ("2001", "Minibar Adjustment", "minibar", "adjustment", None, "F&B", 201),
        ("2100", "Restaurant", "restaurant", "charge", "2101", "F&B", 210),
        ("2101", "Restaurant Adjustment", "restaurant", "adjustment", None, "F&B", 211),
        ("2200", "Room Service", "service", "charge", "2201", "F&B", 220),
        ("2201", "Room Service Adjustment", "service", "adjustment", None, "F&B", 221),
        ("3000", "Spa", "spa", "charge", "3001", "Spa", 300),
        ("3001", "Spa Adjustment", "spa", "adjustment", None, "Spa", 301),
        ("3100", "Laundry", "laundry", "charge", "3101", "Housekeeping", 310),
        ("3101", "Laundry Adjustment", "laundry", "adjustment", None, "Housekeeping", 311),
        ("3200", "Parking", "parking", "charge", "3201", "Front Office", 320),
        ("3201", "Parking Adjustment", "parking", "adjustment", None, "Front Office", 321),
        ("3300", "Phone", "phone", "charge", "3301", "Front Office", 330),
        ("3301", "Phone Adjustment", "phone", "adjustment", None, "Front Office", 331),
        ("3400", "Late Checkout", "late_checkout", "charge", "3401", "Front Office", 340),
        ("3401", "Late Checkout Adjustment", "late_checkout", "adjustment", None, "Front Office", 341),
        ("3500", "Damage", "damage", "charge", "3501", "Front Office", 350),
        ("3501", "Damage Adjustment", "damage", "adjustment", None, "Front Office", 351),
        ("3600", "Newspaper", "newspaper", "charge", "3601", "Front Office", 360),
        ("3601", "Newspaper Adjustment", "newspaper", "adjustment", None, "Front Office", 361),
        ("9000", "Miscellaneous", "misc", "charge", "9001", "General", 900),
        ("9001", "Miscellaneous Adjustment", "misc", "adjustment", None, "General", 901),
        # Payment codes (4000-series)
        ("4000", "Cash Payment", "cash", "payment", None, "Cashier", 400),
        ("4100", "Credit Card Payment", "card", "payment", None, "Cashier", 410),
        ("4200", "Bank Transfer", "bank_transfer", "payment", None, "Cashier", 420),
        ("4300", "UPI Payment", "upi", "payment", None, "Cashier", 430),
        ("4400", "NEFT Payment", "neft", "payment", None, "Cashier", 440),
        ("4500", "Net Banking Payment", "net_banking", "payment", None, "Cashier", 450),
        ("4600", "Voucher Payment", "voucher", "payment", None, "Cashier", 460),
        ("4700", "Complimentary", "comp", "payment", None, "Cashier", 470),
        ("4800", "Bill to Company", "btc", "payment", None, "Cashier", 480),
        # Tax codes (5000-series)
        ("5000", "GST", "tax", "tax", None, "Tax", 500),
        ("5100", "CGST", "tax", "tax", None, "Tax", 510),
        ("5200", "SGST", "tax", "tax", None, "Tax", 520),
    ]

    created = 0
    skipped = 0
    for code, name, category, code_type, adj_code, dept, order in defaults:
        existing = (await session.exec(
            select(TransactionCode).where(TransactionCode.code == code)
        )).first()
        if existing:
            skipped += 1
            continue
        session.add(TransactionCode(
            code=code, name=name, category=category, code_type=code_type,
            adjustment_code=adj_code, department=dept, sort_order=order,
        ))
        created += 1

    await session.commit()
    return {"success": True, "created": created, "skipped": skipped}


@router.get("/lookup/{category}")
async def lookup_by_category(
    category: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Look up transaction code by item_type category."""
    result = (await session.exec(
        select(TransactionCode).where(
            TransactionCode.category == category,
            TransactionCode.code_type == "charge",
            TransactionCode.is_active == True,
        )
    )).first()
    if not result:
        return {"code": None, "message": f"No transaction code found for category '{category}'"}
    return serialize_tc(result)
