"""
Dynamic Pricing Service
Calculates effective room prices using rate plans, seasonal rates,
day-of-week adjustments, length-of-stay discounts, and auto-apply promotions.
"""
from datetime import date
from typing import Optional, Tuple

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.inventory import (
    RatePlan,
    SeasonalRate,
    DayOfWeekRate,
    LengthOfStayRate,
    DailyRate,
)
from app.models.promotions import (
    Promotion,
    PromotionApplicability,
    PromotionBlackoutDate,
)


def _apply_adjustment(base: float, adjustment: float, adjustment_type: str) -> float:
    """Apply a price adjustment (absolute or percentage) to a base price."""
    if adjustment_type == "percentage":
        return base * (1 + adjustment / 100.0)
    # absolute
    return base + adjustment


async def calculate_effective_price(
    session: AsyncSession,
    room_type_name: str,
    room_type_id: int,
    base_price: float,
    check_in: Optional[date] = None,
    check_out: Optional[date] = None,
) -> Tuple[float, Optional[float]]:
    """
    Calculate the effective price for a room type considering all pricing rules.

    Returns (effective_price, original_price).
    original_price is non-None only when the price differs from base_price
    (i.e. a discount/adjustment was applied).
    """
    if not check_in or not check_out:
        return base_price, None

    nights = (check_out - check_in).days
    if nights <= 0:
        return base_price, None

    price = base_price

    # 1. Find active BAR rate plan
    bar_result = await session.exec(
        select(RatePlan).where(
            RatePlan.plan_type == "BAR",
            RatePlan.is_active == True,
        )
    )
    bar_plan = bar_result.first()

    if not bar_plan:
        return base_price, None

    # 1b. Check for DailyRate override (set by AI recommendation or manual rate update)
    daily_rate_result = await session.exec(
        select(DailyRate).where(
            DailyRate.room_type_id == room_type_id,
            DailyRate.rate_plan_id == bar_plan.id,
            DailyRate.date == check_in,
        ).limit(1)
    )
    daily_rate = daily_rate_result.first()
    if daily_rate and daily_rate.override_rate is not None:
        override = round(float(daily_rate.override_rate), 2)
        return override, base_price if override != base_price else None

    # 2. Apply SeasonalRate adjustment for check-in date
    seasonal_result = await session.exec(
        select(SeasonalRate).where(
            SeasonalRate.rate_plan_id == bar_plan.id,
            SeasonalRate.is_active == True,
            SeasonalRate.start_date <= check_in,
            SeasonalRate.end_date >= check_in,
        )
    )
    for sr in seasonal_result.all():
        # Apply if room_type matches or is None (applies to all)
        if sr.room_type is None or sr.room_type == room_type_name:
            price = _apply_adjustment(price, sr.price_adjustment, sr.adjustment_type)

    # 3. Apply DayOfWeekRate adjustment for check-in day
    check_in_dow = check_in.weekday()  # 0=Monday, 6=Sunday
    dow_result = await session.exec(
        select(DayOfWeekRate).where(
            DayOfWeekRate.rate_plan_id == bar_plan.id,
            DayOfWeekRate.is_active == True,
            DayOfWeekRate.day_of_week == check_in_dow,
        )
    )
    for dr in dow_result.all():
        if dr.room_type is None or dr.room_type == room_type_name:
            price = _apply_adjustment(price, dr.price_adjustment, dr.adjustment_type)

    # 4. Apply LengthOfStayRate discount based on number of nights
    los_result = await session.exec(
        select(LengthOfStayRate).where(
            LengthOfStayRate.rate_plan_id == bar_plan.id,
            LengthOfStayRate.is_active == True,
            LengthOfStayRate.min_nights <= nights,
        )
    )
    for lr in los_result.all():
        if lr.room_type is not None and lr.room_type != room_type_name:
            continue
        if lr.max_nights is not None and nights > lr.max_nights:
            continue
        price = _apply_adjustment(price, lr.price_adjustment, lr.adjustment_type)

    # 5. Apply best auto-apply Promotion (code-less, active, valid for dates)
    promo_result = await session.exec(
        select(Promotion).where(
            Promotion.is_active == True,
            Promotion.promotion_code == None,  # Auto-apply = no code required
            Promotion.valid_from <= check_in,
            Promotion.valid_to >= check_in,
        ).order_by(Promotion.priority.desc())
    )
    best_promo_discount = 0.0
    for promo in promo_result.all():
        # Check usage limit
        if promo.usage_limit is not None and promo.usage_count >= promo.usage_limit:
            continue

        # Check min/max nights
        if promo.min_nights is not None and nights < promo.min_nights:
            continue
        if promo.max_nights is not None and nights > promo.max_nights:
            continue

        # Check min booking amount
        if promo.min_booking_amount is not None and price < promo.min_booking_amount:
            continue

        # Check blackout dates
        blackout_result = await session.exec(
            select(PromotionBlackoutDate).where(
                PromotionBlackoutDate.promotion_id == promo.id,
                PromotionBlackoutDate.blackout_start <= check_in,
                PromotionBlackoutDate.blackout_end >= check_in,
            )
        )
        if blackout_result.first():
            continue

        # Check applicability (room_type whitelist/blacklist)
        app_result = await session.exec(
            select(PromotionApplicability).where(
                PromotionApplicability.promotion_id == promo.id,
                PromotionApplicability.entity_type == "room_type",
            )
        )
        applicabilities = app_result.all()
        if applicabilities:
            included_ids = {a.entity_id for a in applicabilities if a.is_included}
            excluded_ids = {a.entity_id for a in applicabilities if not a.is_included}
            if included_ids and room_type_id not in included_ids:
                continue
            if room_type_id in excluded_ids:
                continue

        # Calculate discount amount
        if promo.discount_type == "percentage":
            discount = price * (promo.discount_value / 100.0)
        elif promo.discount_type == "fixed":
            discount = promo.discount_value
        else:
            # free_night, upgrade, addon - not applicable to per-night price display
            continue

        # Apply max discount cap
        if promo.max_discount_amount is not None:
            discount = min(discount, promo.max_discount_amount)

        # Keep the best (highest) discount
        if discount > best_promo_discount:
            best_promo_discount = discount

    price -= best_promo_discount

    # Ensure price doesn't go below zero
    price = max(price, 0.0)

    # Round to 2 decimal places
    price = round(price, 2)

    # Return original_price only if price was actually changed
    if price != base_price:
        return price, base_price
    return base_price, None
