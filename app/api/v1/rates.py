from datetime import date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.inventory import RatePlan, RateRestriction, SeasonalRate, LengthOfStayRate, DayOfWeekRate, PromoCode
from app.models.user import User
from app.services.reservation_service import compute_total

router = APIRouter()


class RatePlanCreate(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    plan_type: str = "BAR"
    currency: str = "INR"
    base_price: float
    is_active: bool = True
    parent_rate_plan_id: Optional[int] = None


class SeasonalRateCreate(BaseModel):
    rate_plan_id: int
    room_type: Optional[str] = None
    start_date: date
    end_date: date
    price_adjustment: float
    adjustment_type: str = "absolute"


class PromoCodeCreate(BaseModel):
    code: str
    name: str
    description: Optional[str] = None
    discount_type: str = "percentage"
    discount_value: float
    min_stay: Optional[int] = None
    max_stay: Optional[int] = None
    valid_from: date
    valid_until: date
    usage_limit: Optional[int] = None
    applicable_rate_plans: Optional[List[int]] = None


@router.get("/plans")
async def list_rate_plans(
    is_active: Optional[bool] = Query(None),
    plan_type: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    query = select(RatePlan)
    if is_active is not None:
        query = query.where(RatePlan.is_active == is_active)
    if plan_type:
        query = query.where(RatePlan.plan_type == plan_type)
    
    plans = (await session.exec(query.order_by(RatePlan.code))).all()
    return [{"id": p.id, "code": p.code, "name": p.name, "description": p.description,
             "plan_type": p.plan_type, "base_price": p.base_price, "currency": p.currency,
             "is_active": p.is_active} for p in plans]


@router.post("/plans", status_code=status.HTTP_201_CREATED)
async def create_rate_plan(
    payload: RatePlanCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    # Check if code already exists
    existing = (await session.exec(
        select(RatePlan).where(RatePlan.code == payload.code)
    )).first()
    if existing:
        raise HTTPException(status_code=400, detail="Rate plan code already exists")
    
    plan = RatePlan(**payload.model_dump())
    session.add(plan)
    await session.commit()
    await session.refresh(plan)
    return {"id": plan.id, "code": plan.code, "status": "created"}


@router.get("/calculate")
async def calculate_rate(
    rate_plan_id: int,
    arrival_date: date,
    departure_date: date,
    room_type: Optional[str] = None,
    promo_code: Optional[str] = None,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user)
):
    total, currency = await compute_total(session, rate_plan_id, arrival_date, departure_date, room_type, promo_code)
    nights = (departure_date - arrival_date).days
    return {"total": total, "currency": currency, "nights": nights, "rate_per_night": total / nights if nights > 0 else 0}


@router.get("/promo-codes")
async def list_promo_codes(
    is_active: Optional[bool] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    query = select(PromoCode)
    if is_active is not None:
        query = query.where(PromoCode.is_active == is_active)
    
    codes = (await session.exec(query.order_by(PromoCode.valid_from.desc()))).all()
    return [{"id": c.id, "code": c.code, "name": c.name, "discount_type": c.discount_type,
             "discount_value": c.discount_value, "valid_from": c.valid_from, "valid_until": c.valid_until,
             "usage_count": c.usage_count, "usage_limit": c.usage_limit, "is_active": c.is_active} for c in codes]


@router.post("/promo-codes", status_code=status.HTTP_201_CREATED)
async def create_promo_code(
    payload: PromoCodeCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    # Check if code already exists
    existing = (await session.exec(
        select(PromoCode).where(PromoCode.code == payload.code.upper())
    )).first()
    if existing:
        raise HTTPException(status_code=400, detail="Promo code already exists")
    
    import json
    promo = PromoCode(
        code=payload.code.upper(),
        name=payload.name,
        description=payload.description,
        discount_type=payload.discount_type,
        discount_value=payload.discount_value,
        min_stay=payload.min_stay,
        max_stay=payload.max_stay,
        valid_from=payload.valid_from,
        valid_until=payload.valid_until,
        usage_limit=payload.usage_limit,
        applicable_rate_plans=json.dumps(payload.applicable_rate_plans) if payload.applicable_rate_plans else None
    )
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    return {"id": promo.id, "code": promo.code, "status": "created"}


@router.get("/promo-codes/{code}/validate")
async def validate_promo_code(
    code: str,
    arrival_date: date,
    departure_date: date,
    rate_plan_id: Optional[int] = None,
    session: AsyncSession = Depends(get_tenant_session)
):
    promo = (await session.exec(
        select(PromoCode).where(
            and_(
                PromoCode.code == code.upper(),
                PromoCode.is_active == True,
                PromoCode.valid_from <= arrival_date,
                PromoCode.valid_until >= departure_date
            )
        )
    )).first()
    
    if not promo:
        return {"valid": False, "message": "Promo code not found or expired"}
    
    nights = (departure_date - arrival_date).days
    if promo.min_stay and nights < promo.min_stay:
        return {"valid": False, "message": f"Minimum stay of {promo.min_stay} nights required"}
    if promo.max_stay and nights > promo.max_stay:
        return {"valid": False, "message": f"Maximum stay of {promo.max_stay} nights allowed"}
    if promo.usage_limit and promo.usage_count >= promo.usage_limit:
        return {"valid": False, "message": "Promo code usage limit reached"}
    
    return {"valid": True, "discount_type": promo.discount_type, "discount_value": promo.discount_value}


class PromoCodeUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None
    min_stay: Optional[int] = None
    max_stay: Optional[int] = None
    valid_from: Optional[date] = None
    valid_until: Optional[date] = None
    usage_limit: Optional[int] = None
    is_active: Optional[bool] = None
    applicable_rate_plans: Optional[List[int]] = None


@router.get("/promo-codes/{promo_id}")
async def get_promo_code(
    promo_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Get a single promo code by ID"""
    promo = await session.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")

    import json
    return {
        "id": promo.id,
        "code": promo.code,
        "name": promo.name,
        "description": promo.description,
        "discount_type": promo.discount_type,
        "discount_value": promo.discount_value,
        "min_stay": promo.min_stay,
        "max_stay": promo.max_stay,
        "valid_from": promo.valid_from,
        "valid_until": promo.valid_until,
        "usage_count": promo.usage_count,
        "usage_limit": promo.usage_limit,
        "is_active": promo.is_active,
        "applicable_rate_plans": json.loads(promo.applicable_rate_plans) if promo.applicable_rate_plans else []
    }


@router.put("/promo-codes/{promo_id}")
async def update_promo_code(
    promo_id: int,
    payload: PromoCodeUpdate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Update an existing promo code"""
    promo = await session.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")

    import json
    update_data = payload.model_dump(exclude_unset=True)

    # Handle applicable_rate_plans JSON conversion
    if 'applicable_rate_plans' in update_data and update_data['applicable_rate_plans'] is not None:
        update_data['applicable_rate_plans'] = json.dumps(update_data['applicable_rate_plans'])

    # Validate discount_value if discount_type is percentage
    if 'discount_type' in update_data and update_data['discount_type'] == 'percentage':
        discount_val = update_data.get('discount_value', promo.discount_value)
        if discount_val is not None and (discount_val < 0 or discount_val > 100):
            raise HTTPException(status_code=400, detail="Percentage discount must be between 0 and 100")

    for field, value in update_data.items():
        setattr(promo, field, value)

    await session.commit()
    await session.refresh(promo)

    return {
        "id": promo.id,
        "code": promo.code,
        "name": promo.name,
        "is_active": promo.is_active,
        "status": "updated"
    }


@router.patch("/promo-codes/{promo_id}/toggle")
async def toggle_promo_code_status(
    promo_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Toggle the active status of a promo code"""
    promo = await session.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")

    promo.is_active = not promo.is_active
    await session.commit()
    await session.refresh(promo)

    return {
        "id": promo.id,
        "code": promo.code,
        "is_active": promo.is_active,
        "status": "toggled"
    }


@router.delete("/promo-codes/{promo_id}")
async def delete_promo_code(
    promo_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Delete a promo code (soft delete by deactivating, or hard delete if usage_count is 0)"""
    promo = await session.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")

    # If promo has been used, soft delete (deactivate)
    if promo.usage_count and promo.usage_count > 0:
        promo.is_active = False
        await session.commit()
        return {"id": promo_id, "status": "deactivated", "message": "Promo code deactivated (has usage history)"}

    # Otherwise, hard delete
    await session.delete(promo)
    await session.commit()
    return {"id": promo_id, "status": "deleted"}


@router.patch("/promo-codes/{promo_id}/increment-usage")
async def increment_promo_usage(
    promo_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Increment the usage count of a promo code (called when promo is applied to a booking)"""
    promo = await session.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(status_code=404, detail="Promo code not found")

    if promo.usage_limit and promo.usage_count >= promo.usage_limit:
        raise HTTPException(status_code=400, detail="Promo code usage limit reached")

    promo.usage_count = (promo.usage_count or 0) + 1
    await session.commit()
    await session.refresh(promo)

    return {
        "id": promo.id,
        "code": promo.code,
        "usage_count": promo.usage_count,
        "usage_limit": promo.usage_limit,
        "status": "incremented"
    }


