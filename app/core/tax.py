"""
Tax Calculation Engine — GST slab-based tax computation.

Supports India's dual-component GST (CGST + SGST) and configurable
tax slabs per category with amount thresholds.
"""
from datetime import date
from typing import Optional
from dataclasses import dataclass

from sqlmodel import select, and_
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.operations import TaxSlab, TaxCategory


@dataclass
class TaxBreakdown:
    """Result of a tax calculation."""
    tax_category_id: int
    rate_pct: float
    tax_amount: float
    component_1_name: str
    component_1_pct: float
    component_1_amount: float
    component_2_name: str
    component_2_pct: float
    component_2_amount: float


async def calculate_tax(
    session: AsyncSession,
    category_name: str,
    base_amount: float,
    country: str = "IN",
    as_of: Optional[date] = None,
) -> Optional[TaxBreakdown]:
    """Calculate tax for a charge based on its category and amount.

    Args:
        session: DB session
        category_name: Tax category name (e.g., "room_charge", "food_beverage")
        base_amount: The pre-tax charge amount
        country: ISO country code (default "IN" for India)
        as_of: Date to check slab validity (defaults to today)

    Returns:
        TaxBreakdown with amounts, or None if no matching slab, zero/negative amount, or no category.
    """
    # Skip tax for zero/negative amounts (refunds, adjustments, voids)
    if base_amount <= 0:
        return None

    if not as_of:
        from app.core.business_date import get_business_date
        as_of = await get_business_date(session)

    # Find the tax category
    category = (await session.exec(
        select(TaxCategory).where(
            and_(TaxCategory.name == category_name, TaxCategory.is_active == True)
        )
    )).first()
    if not category:
        return None

    # Find matching slab: correct country, amount in range, currently effective
    slabs = (await session.exec(
        select(TaxSlab).where(
            and_(
                TaxSlab.tax_category_id == category.id,
                TaxSlab.country == country,
                TaxSlab.is_active == True,
                TaxSlab.effective_from <= as_of,
            )
        ).order_by(TaxSlab.min_amount.desc())
    )).all()

    matching_slab = None
    for slab in slabs:
        # Check effective_to
        if slab.effective_to and slab.effective_to < as_of:
            continue
        # Check amount threshold
        if base_amount >= slab.min_amount:
            if slab.max_amount is None or base_amount <= slab.max_amount:
                matching_slab = slab
                break

    if not matching_slab:
        return None

    tax_amount = round(base_amount * matching_slab.rate_pct / 100, 2)
    comp1_amount = round(base_amount * matching_slab.component_1_pct / 100, 2)
    comp2_amount = round(tax_amount - comp1_amount, 2)  # avoid rounding drift

    return TaxBreakdown(
        tax_category_id=category.id,
        rate_pct=matching_slab.rate_pct,
        tax_amount=tax_amount,
        component_1_name=matching_slab.component_1_name,
        component_1_pct=matching_slab.component_1_pct,
        component_1_amount=comp1_amount,
        component_2_name=matching_slab.component_2_name,
        component_2_pct=matching_slab.component_2_pct,
        component_2_amount=comp2_amount,
    )


# Mapping of folio item_type → tax category name.
# Non-taxable types (payment, refund, discount, tax) are intentionally excluded.
ITEM_TYPE_TO_TAX_CATEGORY = {
    "room_charge": "room_charge",
    "restaurant": "food_beverage",
    "minibar": "food_beverage",
    "spa": "spa",
    "laundry": "service",
    "parking": "service",
    "phone": "service",
    "late_checkout": "service",
    "damage": "service",
    "misc": "service",
}


def get_tax_category_for_item(item_type: str) -> Optional[str]:
    """Return the tax category name for a given folio item_type."""
    return ITEM_TYPE_TO_TAX_CATEGORY.get(item_type)


async def apply_tax_to_line_item(session: AsyncSession, line_item) -> None:
    """Auto-calculate and populate tax fields on a FolioLineItem.
    Mutates line_item in-place. Safe to call on any item — skips
    non-taxable types and zero/negative amounts."""
    cat_name = get_tax_category_for_item(line_item.item_type)
    if not cat_name:
        return
    tax = await calculate_tax(session, cat_name, line_item.amount)
    if not tax:
        return
    line_item.tax_category_id = tax.tax_category_id
    line_item.tax_rate_pct = tax.rate_pct
    line_item.tax_amount = tax.tax_amount
    line_item.tax_component_1_name = tax.component_1_name
    line_item.tax_component_1_pct = tax.component_1_pct
    line_item.tax_component_1_amount = tax.component_1_amount
    line_item.tax_component_2_name = tax.component_2_name
    line_item.tax_component_2_pct = tax.component_2_pct
    line_item.tax_component_2_amount = tax.component_2_amount


def copy_tax_fields(source, target) -> None:
    """Copy tax breakdown fields from one line item to another (for transfers)."""
    for field in (
        "tax_category_id", "tax_rate_pct", "tax_amount",
        "tax_component_1_name", "tax_component_1_pct", "tax_component_1_amount",
        "tax_component_2_name", "tax_component_2_pct", "tax_component_2_amount",
    ):
        setattr(target, field, getattr(source, field, None))


# ============== Simple Tax Calculation Helpers ==============
# These delegate to billing_engine.py - the SINGLE SOURCE OF TRUTH for room tax calculations.
# Kept for backward compatibility with existing code.

# Import from billing_engine (single source of truth)
from app.services.billing_engine import (
    TAX_THRESHOLD,
    TAX_RATE_LOW,
    TAX_RATE_HIGH,
    get_tax_rate,
    calculate_stay_charges,
)
from decimal import Decimal

# Re-export constants for backward compatibility
ROOM_TAX_THRESHOLD = float(TAX_THRESHOLD)  # 7500.0 INR
ROOM_TAX_RATE_LOW = float(TAX_RATE_LOW)    # 0.12 (12%)
ROOM_TAX_RATE_HIGH = float(TAX_RATE_HIGH)  # 0.18 (18%)


def get_room_tax_rate(per_night_rate: float) -> float:
    """Get the GST rate based on per-night room rate.
    DELEGATES TO: billing_engine.get_tax_rate()

    Args:
        per_night_rate: The room rate per night (not total)

    Returns:
        Tax rate as decimal (0.12 or 0.18)
    """
    rate, _ = get_tax_rate(Decimal(str(per_night_rate)))
    return float(rate)


def calculate_booking_taxes(base_price_per_night: float, nights: int = 1) -> dict:
    """Calculate taxes for a booking.
    DELEGATES TO: billing_engine.calculate_stay_charges()

    Args:
        base_price_per_night: Room rate per night
        nights: Number of nights

    Returns:
        Dict with calculated_base, tax_rate, taxes, service_fee (always 0), total_price
    """
    charges = calculate_stay_charges(base_price_per_night, nights)

    return {
        "calculated_base": float(charges.base_amount),
        "tax_rate": float(charges.tax_rate),
        "tax_rate_pct": charges.tax.tax_rate_percent,  # As percentage (12 or 18)
        "taxes": float(charges.tax_amount),
        "service_fee": 0.0,  # Service fee removed
        "total_price": float(charges.total_amount),
    }
