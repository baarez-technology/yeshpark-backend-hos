"""
POS Closure Confirmation Gate (B-19).
All outlets must confirm checks closed before night audit can run.
"""
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.operations import PosOutlet, PosClosure
from app.core.business_date import get_business_date

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class OutletCreate(BaseModel):
    outlet_code: str
    outlet_name: str
    location: Optional[str] = None
    responsible_staff_id: Optional[int] = None

class OutletUpdate(BaseModel):
    outlet_name: Optional[str] = None
    location: Optional[str] = None
    responsible_staff_id: Optional[int] = None
    status: Optional[str] = None

class ClosureConfirmRequest(BaseModel):
    closing_revenue: Optional[float] = None
    open_checks: int = 0
    discrepancy_notes: Optional[str] = None


# ── Outlet CRUD ──────────────────────────────────────────────────

@router.get("/outlets")
async def list_outlets(
    status_filter: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    q = select(PosOutlet)
    if status_filter:
        q = q.where(PosOutlet.status == status_filter)
    outlets = (await session.exec(q)).all()
    return outlets


@router.post("/outlets", status_code=status.HTTP_201_CREATED)
async def create_outlet(
    payload: OutletCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    if current_user.role not in ("admin", "general_manager", "finance_controller"):
        raise HTTPException(status_code=403, detail="Only admin/GM/finance can manage outlets")
    existing = (await session.exec(
        select(PosOutlet).where(PosOutlet.outlet_code == payload.outlet_code)
    )).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Outlet code '{payload.outlet_code}' already exists")
    outlet = PosOutlet(**payload.model_dump())
    session.add(outlet)
    await session.commit()
    await session.refresh(outlet)
    return outlet


@router.put("/outlets/{outlet_id}")
async def update_outlet(
    outlet_id: int,
    payload: OutletUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    outlet = await session.get(PosOutlet, outlet_id)
    if not outlet:
        raise HTTPException(status_code=404, detail="Outlet not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(outlet, field, value)
    session.add(outlet)
    await session.commit()
    await session.refresh(outlet)
    return outlet


@router.post("/seed-defaults", status_code=status.HTTP_201_CREATED)
async def seed_default_outlets(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Seed standard hotel POS outlets."""
    defaults = [
        ("restaurant", "Restaurant"),
        ("bar", "Bar & Lounge"),
        ("spa", "Spa & Wellness"),
        ("minibar", "Minibar"),
        ("laundry", "Laundry"),
        ("room_service", "Room Service"),
    ]
    created = 0
    for code, name in defaults:
        existing = (await session.exec(
            select(PosOutlet).where(PosOutlet.outlet_code == code)
        )).first()
        if not existing:
            session.add(PosOutlet(outlet_code=code, outlet_name=name))
            created += 1
    await session.commit()
    return {"message": f"Seeded {created} POS outlets", "total_outlets": len(defaults)}


# ── Closure Confirmation ─────────────────────────────────────────

@router.get("/status")
async def get_closure_status(
    audit_date: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Get POS closure status for a given audit date (defaults to business date)."""
    from datetime import date as date_type
    target = date_type.fromisoformat(audit_date) if audit_date else await get_business_date(session)

    active_outlets = (await session.exec(
        select(PosOutlet).where(PosOutlet.status == "active")
    )).all()

    result = []
    for outlet in active_outlets:
        closure = (await session.exec(
            select(PosClosure).where(
                PosClosure.pos_outlet_id == outlet.id,
                PosClosure.audit_date == target,
            )
        )).first()
        result.append({
            "outlet_id": outlet.id,
            "outlet_code": outlet.outlet_code,
            "outlet_name": outlet.outlet_name,
            "audit_date": str(target),
            "close_status": closure.close_status if closure else "pending",
            "closing_revenue": closure.closing_revenue if closure else None,
            "open_checks": closure.open_checks if closure else None,
            "confirmed_by": closure.confirmed_by if closure else None,
            "confirmed_at": str(closure.confirmed_at) if closure and closure.confirmed_at else None,
        })

    confirmed = sum(1 for r in result if r["close_status"] == "confirmed")
    return {
        "audit_date": str(target),
        "total_outlets": len(active_outlets),
        "confirmed": confirmed,
        "pending": len(active_outlets) - confirmed,
        "all_confirmed": confirmed == len(active_outlets),
        "outlets": result,
    }


@router.post("/outlets/{outlet_id}/confirm")
async def confirm_outlet_closure(
    outlet_id: int,
    payload: ClosureConfirmRequest,
    audit_date: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Confirm that a POS outlet has closed all checks for the business date."""
    from datetime import date as date_type
    target = date_type.fromisoformat(audit_date) if audit_date else await get_business_date(session)

    outlet = await session.get(PosOutlet, outlet_id)
    if not outlet:
        raise HTTPException(status_code=404, detail="Outlet not found")

    existing = (await session.exec(
        select(PosClosure).where(
            PosClosure.pos_outlet_id == outlet_id,
            PosClosure.audit_date == target,
        )
    )).first()

    if existing and existing.close_status == "confirmed":
        raise HTTPException(status_code=409, detail="Outlet already confirmed for this date")

    if existing:
        existing.close_status = "confirmed"
        existing.closing_revenue = payload.closing_revenue
        existing.open_checks = payload.open_checks
        existing.discrepancy_notes = payload.discrepancy_notes
        existing.confirmed_by = current_user.id
        existing.confirmed_at = datetime.utcnow()
        session.add(existing)
    else:
        closure = PosClosure(
            pos_outlet_id=outlet_id,
            audit_date=target,
            close_status="confirmed",
            closing_revenue=payload.closing_revenue,
            open_checks=payload.open_checks,
            discrepancy_notes=payload.discrepancy_notes,
            confirmed_by=current_user.id,
            confirmed_at=datetime.utcnow(),
        )
        session.add(closure)

    await session.commit()
    return {"message": f"Outlet '{outlet.outlet_name}' closure confirmed for {target}"}


@router.get("/pending-check")
async def check_pending_closures(
    audit_date: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user),
):
    """Used by night audit pre-flight: returns unconfirmed outlets (if any)."""
    from datetime import date as date_type
    target = date_type.fromisoformat(audit_date) if audit_date else await get_business_date(session)

    active_outlets = (await session.exec(
        select(PosOutlet).where(PosOutlet.status == "active")
    )).all()

    pending = []
    for outlet in active_outlets:
        closure = (await session.exec(
            select(PosClosure).where(
                PosClosure.pos_outlet_id == outlet.id,
                PosClosure.audit_date == target,
                PosClosure.close_status == "confirmed",
            )
        )).first()
        if not closure:
            pending.append({
                "outlet_id": outlet.id,
                "outlet_code": outlet.outlet_code,
                "outlet_name": outlet.outlet_name,
            })

    return {"audit_date": str(target), "pending_count": len(pending), "pending_outlets": pending}
