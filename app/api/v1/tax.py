"""
Tax Configuration API — tax categories and slabs CRUD + calculation endpoint.
"""
from datetime import date, datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.user import User
from app.models.operations import TaxCategory, TaxSlab
from app.core.tax import calculate_tax

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────

class TaxCategoryCreate(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None

class TaxCategoryResponse(BaseModel):
    id: int
    name: str
    display_name: str
    description: Optional[str] = None
    is_active: bool

class TaxSlabCreate(BaseModel):
    tax_category_id: int
    country: str = "IN"
    min_amount: float = 0.0
    max_amount: Optional[float] = None
    rate_pct: float
    component_1_name: str = "CGST"
    component_1_pct: float = 0.0
    component_2_name: str = "SGST"
    component_2_pct: float = 0.0
    effective_from: Optional[date] = None

class TaxSlabResponse(BaseModel):
    id: int
    tax_category_id: int
    country: str
    min_amount: float
    max_amount: Optional[float]
    rate_pct: float
    component_1_name: str
    component_1_pct: float
    component_2_name: str
    component_2_pct: float
    effective_from: date
    effective_to: Optional[date]
    is_active: bool

class TaxCalculateRequest(BaseModel):
    category_name: str
    base_amount: float
    country: str = "IN"


# ── Tax Categories ───────────────────────────────────────────────────

@router.get("/categories", response_model=List[TaxCategoryResponse])
async def list_tax_categories(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    categories = (await session.exec(
        select(TaxCategory).where(TaxCategory.is_active == True)
    )).all()
    return categories


@router.post("/categories", response_model=TaxCategoryResponse)
async def create_tax_category(
    payload: TaxCategoryCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ("admin", "general_manager", "finance_controller"):
        raise HTTPException(status_code=403, detail="Only admin/GM/finance can manage tax categories")

    existing = (await session.exec(
        select(TaxCategory).where(TaxCategory.name == payload.name)
    )).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Tax category '{payload.name}' already exists")

    category = TaxCategory(**payload.model_dump())
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


@router.delete("/categories/{category_id}")
async def deactivate_tax_category(
    category_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ("admin", "general_manager", "finance_controller"):
        raise HTTPException(status_code=403, detail="Only admin/GM/finance can manage tax categories")

    category = await session.get(TaxCategory, category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Tax category not found")
    category.is_active = False
    session.add(category)
    await session.commit()
    return {"detail": "Tax category deactivated"}


# ── Tax Slabs ────────────────────────────────────────────────────────

@router.get("/slabs", response_model=List[TaxSlabResponse])
async def list_tax_slabs(
    country: Optional[str] = None,
    category_id: Optional[int] = None,
    session: AsyncSession = Depends(get_tenant_session),
):
    query = select(TaxSlab).where(TaxSlab.is_active == True)
    if country:
        query = query.where(TaxSlab.country == country)
    if category_id:
        query = query.where(TaxSlab.tax_category_id == category_id)
    slabs = (await session.exec(query.order_by(TaxSlab.tax_category_id, TaxSlab.min_amount))).all()
    return slabs


@router.post("/slabs", response_model=TaxSlabResponse)
async def create_tax_slab(
    payload: TaxSlabCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ("admin", "general_manager", "finance_controller"):
        raise HTTPException(status_code=403, detail="Only admin/GM/finance can manage tax slabs")

    # Validate category exists
    category = await session.get(TaxCategory, payload.tax_category_id)
    if not category:
        raise HTTPException(status_code=404, detail="Tax category not found")

    # Validate rate bounds
    if payload.rate_pct < 0 or payload.rate_pct > 100:
        raise HTTPException(status_code=400, detail="Tax rate must be between 0 and 100%")
    if payload.component_1_pct < 0 or payload.component_2_pct < 0:
        raise HTTPException(status_code=400, detail="Component rates cannot be negative")

    # Validate components sum to total
    if abs((payload.component_1_pct + payload.component_2_pct) - payload.rate_pct) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Component rates ({payload.component_1_pct} + {payload.component_2_pct}) must equal total rate ({payload.rate_pct})"
        )

    slab_data = payload.model_dump()
    if not slab_data.get("effective_from"):
        slab_data["effective_from"] = date.today()

    slab = TaxSlab(**slab_data)
    session.add(slab)
    await session.commit()
    await session.refresh(slab)
    return slab


@router.put("/slabs/{slab_id}", response_model=TaxSlabResponse)
async def update_tax_slab(
    slab_id: int,
    payload: TaxSlabCreate,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ("admin", "general_manager", "finance_controller"):
        raise HTTPException(status_code=403, detail="Only admin/GM/finance can manage tax slabs")

    slab = await session.get(TaxSlab, slab_id)
    if not slab:
        raise HTTPException(status_code=404, detail="Tax slab not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(slab, field, value)
    slab.updated_at = datetime.utcnow()
    session.add(slab)
    await session.commit()
    await session.refresh(slab)
    return slab


@router.delete("/slabs/{slab_id}")
async def deactivate_tax_slab(
    slab_id: int,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    if current_user.role not in ("admin", "general_manager", "finance_controller"):
        raise HTTPException(status_code=403, detail="Only admin/GM/finance can manage tax slabs")

    slab = await session.get(TaxSlab, slab_id)
    if not slab:
        raise HTTPException(status_code=404, detail="Tax slab not found")
    slab.is_active = False
    slab.updated_at = datetime.utcnow()
    session.add(slab)
    await session.commit()
    return {"detail": "Tax slab deactivated"}


# ── Tax Calculation ──────────────────────────────────────────────────

@router.post("/calculate")
async def calculate_tax_endpoint(
    payload: TaxCalculateRequest,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Calculate tax for a given category and amount. Useful for previews."""
    result = await calculate_tax(
        session=session,
        category_name=payload.category_name,
        base_amount=payload.base_amount,
        country=payload.country,
    )
    if not result:
        return {"tax_amount": 0, "rate_pct": 0, "detail": "No matching tax slab found"}

    return {
        "base_amount": payload.base_amount,
        "tax_rate_pct": result.rate_pct,
        "tax_amount": result.tax_amount,
        "total_with_tax": round(payload.base_amount + result.tax_amount, 2),
        "components": [
            {"name": result.component_1_name, "rate_pct": result.component_1_pct, "amount": result.component_1_amount},
            {"name": result.component_2_name, "rate_pct": result.component_2_pct, "amount": result.component_2_amount},
        ]
    }


# ── Seed India GST defaults ─────────────────────────────────────────

@router.post("/seed-india-gst")
async def seed_india_gst(
    session: AsyncSession = Depends(get_tenant_session),
    current_user: User = Depends(get_current_user)
):
    """Seed default India GST tax categories and slabs (idempotent)."""
    if current_user.role not in ("admin", "general_manager"):
        raise HTTPException(status_code=403, detail="Only admin/GM can seed tax data")

    created_categories = 0
    created_slabs = 0

    # Define default categories
    default_categories = [
        ("room_charge", "Room Charges"),
        ("food_beverage", "Food & Beverages"),
        ("spa", "Spa & Wellness"),
        ("service", "General Services"),
    ]

    category_ids = {}
    for name, display in default_categories:
        existing = (await session.exec(
            select(TaxCategory).where(TaxCategory.name == name)
        )).first()
        if existing:
            category_ids[name] = existing.id
        else:
            cat = TaxCategory(name=name, display_name=display)
            session.add(cat)
            await session.flush()
            category_ids[name] = cat.id
            created_categories += 1

    # Define India GST slabs
    default_slabs = [
        # Room charges: ≤7500 = 12% (6+6), >7500 = 18% (9+9)
        (category_ids["room_charge"], 0.0, 7500.0, 12.0, 6.0, 6.0),
        (category_ids["room_charge"], 7500.01, None, 18.0, 9.0, 9.0),
        # Food & beverages: flat 5% (2.5+2.5)
        (category_ids["food_beverage"], 0.0, None, 5.0, 2.5, 2.5),
        # Spa: flat 18% (9+9)
        (category_ids["spa"], 0.0, None, 18.0, 9.0, 9.0),
        # General services: flat 18% (9+9)
        (category_ids["service"], 0.0, None, 18.0, 9.0, 9.0),
    ]

    for cat_id, min_amt, max_amt, rate, c1, c2 in default_slabs:
        # Check if this slab already exists
        query = select(TaxSlab).where(
            and_(
                TaxSlab.tax_category_id == cat_id,
                TaxSlab.country == "IN",
                TaxSlab.min_amount == min_amt,
                TaxSlab.is_active == True,
            )
        )
        existing = (await session.exec(query)).first()
        if not existing:
            slab = TaxSlab(
                tax_category_id=cat_id,
                country="IN",
                min_amount=min_amt,
                max_amount=max_amt,
                rate_pct=rate,
                component_1_name="CGST",
                component_1_pct=c1,
                component_2_name="SGST",
                component_2_pct=c2,
            )
            session.add(slab)
            created_slabs += 1

    await session.commit()
    return {
        "detail": "India GST seeded",
        "categories_created": created_categories,
        "slabs_created": created_slabs,
    }
