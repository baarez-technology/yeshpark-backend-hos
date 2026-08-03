"""
Hotel Configuration API — business date, timezone, currency, etc.
"""
from datetime import date, datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select, delete
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.operations import NightAudit
from app.core.business_date import get_hotel_config

router = APIRouter()


class HotelConfigResponse(BaseModel):
    id: int
    business_date: date
    night_audit_cutoff: str
    timezone: str
    currency: str
    incidental_hold_pct: float
    digital_key_activation_minutes: int = 60
    last_audit_completed_at: Optional[datetime] = None
    last_audit_by: Optional[int] = None


class HotelConfigUpdate(BaseModel):
    night_audit_cutoff: Optional[str] = None
    timezone: Optional[str] = None
    currency: Optional[str] = None
    incidental_hold_pct: Optional[float] = None
    digital_key_activation_minutes: Optional[int] = None


class BusinessDateOverride(BaseModel):
    business_date: date
    reason: str


@router.get("/business-date")
async def get_business_date(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Return the current hotel business date."""
    config = await get_hotel_config(session)
    return {"business_date": config.business_date}


@router.get("")
async def get_config(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Return full hotel configuration."""
    config = await get_hotel_config(session)
    return HotelConfigResponse(
        id=config.id,
        business_date=config.business_date,
        night_audit_cutoff=config.night_audit_cutoff,
        timezone=config.timezone,
        currency=config.currency,
        incidental_hold_pct=config.incidental_hold_pct,
        digital_key_activation_minutes=getattr(config, 'digital_key_activation_minutes', 60),
        last_audit_completed_at=config.last_audit_completed_at,
        last_audit_by=config.last_audit_by,
    )


@router.post("/override-business-date")
async def override_business_date(
    payload: BusinessDateOverride,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Admin-only: forcibly correct the business date.
    Use only when the audit date has drifted from the calendar date
    due to test runs, data issues, or deployment errors."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can override the business date")

    config = await get_hotel_config(session)
    old_date = config.business_date
    config.business_date = payload.business_date
    config.updated_at = datetime.utcnow()
    session.add(config)
    await session.commit()
    await session.refresh(config)

    return {
        "success": True,
        "old_business_date": old_date,
        "new_business_date": config.business_date,
        "reason": payload.reason,
        "overridden_by": current_user.email,
    }


@router.delete("/purge-future-audits")
async def purge_future_audits(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Admin-only: delete night audit records whose date is strictly after
    the current business date. Use after overriding business date to remove
    phantom records left by accidental test audit runs."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admin can purge future audit records")

    config = await get_hotel_config(session)
    business_date = config.business_date

    future_audits = (await session.exec(
        select(NightAudit).where(NightAudit.audit_date > business_date)
    )).all()

    deleted_dates = [str(a.audit_date) for a in future_audits]
    for audit in future_audits:
        await session.delete(audit)

    await session.commit()

    return {
        "success": True,
        "business_date": business_date,
        "deleted_count": len(deleted_dates),
        "deleted_dates": deleted_dates,
    }


@router.put("")
async def update_config(
    update: HotelConfigUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update hotel configuration (admin only). Business date cannot be
    set directly — it only advances via night audit."""
    if current_user.role not in ("admin", "general_manager", "finance_controller"):
        raise HTTPException(status_code=403, detail="Only admin/GM/finance can update hotel config")

    config = await get_hotel_config(session)
    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(config, field, value)
    config.updated_at = datetime.utcnow()
    session.add(config)
    await session.commit()
    await session.refresh(config)

    return HotelConfigResponse(
        id=config.id,
        business_date=config.business_date,
        night_audit_cutoff=config.night_audit_cutoff,
        timezone=config.timezone,
        currency=config.currency,
        incidental_hold_pct=config.incidental_hold_pct,
        digital_key_activation_minutes=getattr(config, 'digital_key_activation_minutes', 60),
        last_audit_completed_at=config.last_audit_completed_at,
        last_audit_by=config.last_audit_by,
    )
