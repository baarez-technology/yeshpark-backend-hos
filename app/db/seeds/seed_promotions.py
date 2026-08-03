"""
Seed script for Promotions & Discount Management data.
Creates sample promotions, applicability rules, usage records, blackout dates, and analytics.
"""
import json
import random
from datetime import date, datetime, timedelta
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.promotions import (
    Promotion,
    PromotionApplicability,
    PromotionUsage,
    PromotionBlackoutDate,
    PromotionAnalytics,
)


async def seed_promotions_data(session: AsyncSession, property_id: int = 1) -> dict:
    """
    Seed promotions data for a property.

    Creates:
    - 10+ Promotions (percentage, fixed, free_night, upgrade, addon)
    - PromotionApplicability records (room types, rate plans, channels)
    - Sample PromotionUsage records (redemption tracking)
    - PromotionBlackoutDates (holidays, peak periods)
    - PromotionAnalytics (daily performance metrics)

    This function is idempotent - it checks for existing records before creating.

    Args:
        session: AsyncSession for database operations
        property_id: The hotel property ID (defaults to 1)

    Returns:
        dict with counts of created records
    """
    print("=" * 60)
    print("Starting promotions data seeding...")
    print("=" * 60)

    today = date.today()
    counts = {
        "promotions": 0,
        "applicability": 0,
        "usage": 0,
        "blackout_dates": 0,
        "analytics": 0,
    }

    # ========== PROMOTIONS ==========
    print("\n[1/5] Creating promotions...")

    promotions_data = [
        # Percentage Discounts
        {
            "promotion_code": "SUMMER25",
            "title": "Early Bird Summer",
            "description": "Book early for summer and save 25% on all room types. Perfect for planning your summer getaway.",
            "discount_type": "percentage",
            "discount_value": 25.0,
            "is_active": True,
            "valid_from": date(2025, 6, 1),
            "valid_to": date(2025, 8, 31),
            "min_nights": 3,
            "max_nights": None,
            "min_booking_amount": None,
            "max_discount_amount": 41500.0,
            "usage_limit": 500,
            "usage_count": 133,
            "is_stackable": False,
            "priority": 10,
            "terms_and_conditions": "Valid for stays between June 1 - August 31, 2025. Minimum 3-night stay required. Cannot be combined with other offers. Subject to availability.",
        },
        {
            "promotion_code": "WEEKEND15",
            "title": "Weekend Escape",
            "description": "Enjoy 15% off on Friday and Saturday night stays. The perfect weekend retreat awaits.",
            "discount_type": "percentage",
            "discount_value": 15.0,
            "is_active": True,
            "valid_from": date(2025, 1, 1),
            "valid_to": date(2025, 12, 31),
            "min_nights": 2,
            "max_nights": 3,
            "min_booking_amount": None,
            "max_discount_amount": 16500.0,
            "usage_limit": 1000,
            "usage_count": 287,
            "is_stackable": True,
            "priority": 5,
            "terms_and_conditions": "Valid for Friday and Saturday night stays only. Minimum 2-night stay. Can be combined with loyalty rewards. Subject to availability.",
        },
        {
            "promotion_code": "HOLIDAY20",
            "title": "Holiday Special",
            "description": "Celebrate the holiday season with 20% off on all suites. Complimentary champagne included.",
            "discount_type": "percentage",
            "discount_value": 20.0,
            "is_active": True,
            "valid_from": date(2025, 12, 1),
            "valid_to": date(2026, 1, 5),
            "min_nights": 2,
            "max_nights": None,
            "min_booking_amount": 33000.0,
            "max_discount_amount": 33000.0,
            "usage_limit": 200,
            "usage_count": 45,
            "is_stackable": False,
            "priority": 15,
            "terms_and_conditions": "Valid for Executive and Presidential Suites only. Minimum 2-night stay. Includes complimentary bottle of champagne. Cannot be combined with other promotions.",
        },
        {
            "promotion_code": "WINTER2024",
            "title": "Winter Wonderland Special",
            "description": "Enjoy 20% off on all room types during the winter season.",
            "discount_type": "percentage",
            "discount_value": 20.0,
            "is_active": True,
            "valid_from": today - timedelta(days=10),
            "valid_to": today + timedelta(days=60),
            "min_nights": 2,
            "max_nights": None,
            "min_booking_amount": 16500.0,
            "max_discount_amount": 25000.0,
            "usage_limit": 100,
            "usage_count": 34,
            "is_stackable": False,
            "priority": 8,
            "terms_and_conditions": "Valid for direct bookings only. Cannot be combined with other offers. Blackout dates may apply.",
        },
        {
            "promotion_code": "LOYAL10",
            "title": "Loyalty Reward",
            "description": "Exclusive 10% discount for returning guests. Our way of saying thank you.",
            "discount_type": "percentage",
            "discount_value": 10.0,
            "is_active": True,
            "valid_from": date(2025, 1, 1),
            "valid_to": date(2025, 12, 31),
            "min_nights": 1,
            "max_nights": None,
            "min_booking_amount": None,
            "max_discount_amount": None,
            "usage_limit": None,
            "usage_count": 412,
            "is_stackable": True,
            "priority": 3,
            "terms_and_conditions": "Available to guests who have stayed with us before. Valid ID required. Can be stacked with Weekend Escape offer.",
        },
        # Fixed Amount Discounts
        {
            "promotion_code": "CORP50",
            "title": "Corporate Perk",
            "description": "₹4,000 off per night for corporate account holders on extended stays.",
            "discount_type": "fixed",
            "discount_value": 4000.0,
            "is_active": True,
            "valid_from": date(2025, 1, 1),
            "valid_to": date(2025, 12, 31),
            "min_nights": 5,
            "max_nights": None,
            "min_booking_amount": 41500.0,
            "max_discount_amount": 20000.0,
            "usage_limit": None,
            "usage_count": 89,
            "is_stackable": False,
            "priority": 7,
            "terms_and_conditions": "Valid for corporate account holders only. Minimum 5-night stay required. ₹4,000 discount applied per night.",
        },
        {
            "promotion_code": "SAVE100",
            "title": "Instant Savings",
            "description": "Save ₹8,000 instantly on bookings of ₹41,500 or more.",
            "discount_type": "fixed",
            "discount_value": 8000.0,
            "is_active": True,
            "valid_from": today - timedelta(days=5),
            "valid_to": today + timedelta(days=45),
            "min_nights": 2,
            "max_nights": None,
            "min_booking_amount": 41500.0,
            "max_discount_amount": 8000.0,
            "usage_limit": 300,
            "usage_count": 56,
            "is_stackable": False,
            "priority": 6,
            "terms_and_conditions": "Valid for bookings of ₹41,500 or more. One-time discount per stay.",
        },
        # Free Night Offers
        {
            "promotion_code": "FREENIGHT",
            "title": "Stay 4, Pay 3 - Free Night Offer",
            "description": "Book 4 nights and get the 4th night absolutely free.",
            "discount_type": "free_night",
            "discount_value": 1.0,
            "is_active": True,
            "valid_from": today - timedelta(days=20),
            "valid_to": today + timedelta(days=90),
            "min_nights": 4,
            "max_nights": None,
            "min_booking_amount": None,
            "max_discount_amount": None,
            "usage_limit": 50,
            "usage_count": 12,
            "is_stackable": False,
            "priority": 12,
            "terms_and_conditions": "Valid for Deluxe and Suite rooms only. Direct booking required. Subject to availability.",
        },
        {
            "promotion_code": "STAY7FREE",
            "title": "Weekly Stay Bonus",
            "description": "Book 7 nights and get 2 nights free - perfect for extended stays.",
            "discount_type": "free_night",
            "discount_value": 2.0,
            "is_active": True,
            "valid_from": date(2025, 1, 1),
            "valid_to": date(2025, 12, 31),
            "min_nights": 7,
            "max_nights": None,
            "min_booking_amount": None,
            "max_discount_amount": None,
            "usage_limit": 100,
            "usage_count": 23,
            "is_stackable": False,
            "priority": 14,
            "terms_and_conditions": "Minimum 7-night stay required. 2 free nights applied at end of stay. All room types eligible.",
        },
        # Upgrade Offers
        {
            "promotion_code": "UPGRADE",
            "title": "Complimentary Room Upgrade",
            "description": "Book a Standard room and receive a complimentary upgrade to Deluxe (subject to availability).",
            "discount_type": "upgrade",
            "discount_value": 1.0,
            "is_active": True,
            "valid_from": today - timedelta(days=15),
            "valid_to": today + timedelta(days=75),
            "min_nights": 2,
            "max_nights": None,
            "min_booking_amount": 16500.0,
            "max_discount_amount": None,
            "usage_limit": 75,
            "usage_count": 28,
            "is_stackable": False,
            "priority": 9,
            "terms_and_conditions": "Upgrade subject to availability at check-in. Standard to Deluxe only. Direct bookings only.",
        },
        {
            "promotion_code": "VIPUPGRADE",
            "title": "VIP Suite Upgrade",
            "description": "For our premium guests - upgrade from Executive to Presidential Suite.",
            "discount_type": "upgrade",
            "discount_value": 1.0,
            "is_active": True,
            "valid_from": date(2025, 1, 1),
            "valid_to": date(2025, 12, 31),
            "min_nights": 3,
            "max_nights": None,
            "min_booking_amount": 66500.0,
            "max_discount_amount": None,
            "usage_limit": 25,
            "usage_count": 8,
            "is_stackable": False,
            "priority": 20,
            "terms_and_conditions": "VIP members only. Subject to availability. Minimum 3-night stay.",
        },
        # Add-on Offers
        {
            "promotion_code": "BREAKFAST",
            "title": "Complimentary Breakfast",
            "description": "Enjoy complimentary breakfast for two when you book direct.",
            "discount_type": "addon",
            "discount_value": 1.0,
            "is_active": True,
            "valid_from": today - timedelta(days=30),
            "valid_to": today + timedelta(days=120),
            "min_nights": 1,
            "max_nights": None,
            "min_booking_amount": 12500.0,
            "max_discount_amount": None,
            "usage_limit": 500,
            "usage_count": 187,
            "is_stackable": True,
            "priority": 4,
            "terms_and_conditions": "Breakfast for 2 adults included daily. Direct bookings only. Children under 12 eat free.",
        },
        {
            "promotion_code": "SPAPKG",
            "title": "Spa Package",
            "description": "Book any suite and receive a complimentary 60-minute spa treatment for two.",
            "discount_type": "addon",
            "discount_value": 1.0,
            "is_active": True,
            "valid_from": date(2025, 3, 1),
            "valid_to": date(2025, 11, 30),
            "min_nights": 2,
            "max_nights": None,
            "min_booking_amount": 41500.0,
            "max_discount_amount": None,
            "usage_limit": 100,
            "usage_count": 34,
            "is_stackable": False,
            "priority": 11,
            "terms_and_conditions": "Suite bookings only. Spa appointments subject to availability. Advance booking recommended.",
        },
        # Expired/Flash Sale (for history)
        {
            "promotion_code": "FLASH30",
            "title": "Flash Sale",
            "description": "Limited time offer! 30% off for bookings made this week only.",
            "discount_type": "percentage",
            "discount_value": 30.0,
            "is_active": False,
            "valid_from": date(2025, 11, 20),
            "valid_to": date(2025, 11, 27),
            "min_nights": 1,
            "max_nights": None,
            "min_booking_amount": None,
            "max_discount_amount": 33000.0,
            "usage_limit": 100,
            "usage_count": 100,
            "is_stackable": False,
            "priority": 25,
            "terms_and_conditions": "Valid for one week only. First come, first served. Limited to 100 redemptions.",
        },
        # OTA-specific promotion
        {
            "promotion_code": None,
            "title": "OTA Flash Sale",
            "description": "Limited time 15% discount for OTA bookings during low season.",
            "discount_type": "percentage",
            "discount_value": 15.0,
            "is_active": True,
            "valid_from": today,
            "valid_to": today + timedelta(days=30),
            "min_nights": 1,
            "max_nights": 7,
            "min_booking_amount": None,
            "max_discount_amount": 12500.0,
            "usage_limit": None,
            "usage_count": 87,
            "is_stackable": False,
            "priority": 6,
            "terms_and_conditions": "OTA channels only. Subject to availability. Rate visible on partner sites.",
        },
    ]

    promotion_objects = []
    for promo_data in promotions_data:
        # Check for existing promotion by code (or title for code-less promos)
        if promo_data["promotion_code"]:
            existing = (await session.exec(
                select(Promotion).where(
                    Promotion.property_id == property_id,
                    Promotion.promotion_code == promo_data["promotion_code"]
                )
            )).first()
        else:
            existing = (await session.exec(
                select(Promotion).where(
                    Promotion.property_id == property_id,
                    Promotion.title == promo_data["title"]
                )
            )).first()

        if existing:
            promotion_objects.append(existing)
            print(f"  -> Promotion already exists: {promo_data['title']}")
            continue

        promotion = Promotion(
            property_id=property_id,
            **promo_data
        )
        session.add(promotion)
        await session.flush()
        promotion_objects.append(promotion)
        counts["promotions"] += 1
        print(f"  + Created promotion: {promo_data['title']} ({promo_data['discount_type']})")

    await session.commit()
    print(f"  Total promotions created: {counts['promotions']}")

    # ========== PROMOTION APPLICABILITY ==========
    print("\n[2/5] Creating promotion applicability rules...")

    # Define room types, rate plans, and channels
    room_types = [
        (1, "Standard Double"),
        (2, "Deluxe King"),
        (3, "Deluxe Twin"),
        (4, "Executive Suite"),
        (5, "Presidential Suite"),
    ]

    rate_plans = [
        (1, "BAR"),
        (2, "Advance Purchase"),
        (3, "Corporate"),
        (4, "Mobile Rate"),
        (5, "Long Stay"),
    ]

    channels = [
        (1, "Direct"),
        (2, "Booking.com"),
        (3, "Expedia"),
        (4, "Hotels.com"),
        (5, "Agoda"),
    ]

    # Define applicability rules for each promotion
    applicability_rules = {
        "SUMMER25": {
            "room_type": [1, 2, 3, 4, 5],  # All room types
            "rate_plan": [1, 2],  # BAR, Advance Purchase
            "channel": [1],  # Direct only
        },
        "WEEKEND15": {
            "room_type": [1, 2, 3],  # Standard, Deluxe
            "rate_plan": [1],  # BAR only
            "channel": [1, 2, 3],  # Direct, Booking.com, Expedia
        },
        "HOLIDAY20": {
            "room_type": [4, 5],  # Suites only
            "rate_plan": [1, 3],  # BAR, Corporate
            "channel": [1],  # Direct only
        },
        "WINTER2024": {
            "room_type": [1, 2, 3, 4],  # All except Presidential
            "rate_plan": [1, 5],  # BAR, Long Stay
            "channel": [1],  # Direct only
        },
        "LOYAL10": {
            "room_type": [1, 2, 3, 4, 5],  # All
            "rate_plan": [1, 3, 4],  # BAR, Corporate, Mobile Rate
            "channel": [1, 2, 3, 4, 5],  # All channels
        },
        "CORP50": {
            "room_type": [4, 5],  # Suites
            "rate_plan": [3],  # Corporate only
            "channel": [1],  # Direct only
        },
        "FREENIGHT": {
            "room_type": [2, 3, 4, 5],  # Deluxe and Suites
            "rate_plan": [1],  # BAR only
            "channel": [1],  # Direct only
        },
        "UPGRADE": {
            "room_type": [1],  # Standard only (for upgrade to Deluxe)
            "rate_plan": [1, 2],  # BAR, Advance Purchase
            "channel": [1],  # Direct only
        },
        "BREAKFAST": {
            "room_type": [1, 2, 3, 4, 5],  # All
            "rate_plan": [1, 2],  # BAR, Advance Purchase
            "channel": [1],  # Direct only
        },
    }

    for promo in promotion_objects:
        promo_code = promo.promotion_code
        if promo_code not in applicability_rules:
            continue

        rules = applicability_rules[promo_code]

        # Room type applicability
        for rt_id, rt_name in room_types:
            if rt_id in rules.get("room_type", []):
                existing = (await session.exec(
                    select(PromotionApplicability).where(
                        PromotionApplicability.promotion_id == promo.id,
                        PromotionApplicability.entity_type == "room_type",
                        PromotionApplicability.entity_id == rt_id
                    )
                )).first()

                if not existing:
                    applicability = PromotionApplicability(
                        property_id=property_id,
                        promotion_id=promo.id,
                        entity_type="room_type",
                        entity_id=rt_id,
                        entity_name=rt_name,
                        is_included=True,
                    )
                    session.add(applicability)
                    counts["applicability"] += 1

        # Rate plan applicability
        for rp_id, rp_name in rate_plans:
            if rp_id in rules.get("rate_plan", []):
                existing = (await session.exec(
                    select(PromotionApplicability).where(
                        PromotionApplicability.promotion_id == promo.id,
                        PromotionApplicability.entity_type == "rate_plan",
                        PromotionApplicability.entity_id == rp_id
                    )
                )).first()

                if not existing:
                    applicability = PromotionApplicability(
                        property_id=property_id,
                        promotion_id=promo.id,
                        entity_type="rate_plan",
                        entity_id=rp_id,
                        entity_name=rp_name,
                        is_included=True,
                    )
                    session.add(applicability)
                    counts["applicability"] += 1

        # Channel applicability
        for ch_id, ch_name in channels:
            if ch_id in rules.get("channel", []):
                existing = (await session.exec(
                    select(PromotionApplicability).where(
                        PromotionApplicability.promotion_id == promo.id,
                        PromotionApplicability.entity_type == "channel",
                        PromotionApplicability.entity_id == ch_id
                    )
                )).first()

                if not existing:
                    applicability = PromotionApplicability(
                        property_id=property_id,
                        promotion_id=promo.id,
                        entity_type="channel",
                        entity_id=ch_id,
                        entity_name=ch_name,
                        is_included=True,
                    )
                    session.add(applicability)
                    counts["applicability"] += 1

    await session.commit()
    print(f"  Total applicability rules created: {counts['applicability']}")

    # ========== PROMOTION USAGE ==========
    print("\n[3/5] Creating sample promotion usage records...")

    # Create sample usage records for active promotions
    for promo in promotion_objects:
        if not promo.is_active:
            continue

        # Create 5-15 usage records per active promotion
        num_usages = random.randint(5, 15)

        for i in range(num_usages):
            # Generate mock booking and guest IDs
            mock_booking_id = 1000 + (promo.id * 100) + i
            mock_guest_id = random.randint(1, 50)

            # Check if usage record already exists
            existing = (await session.exec(
                select(PromotionUsage).where(
                    PromotionUsage.promotion_id == promo.id,
                    PromotionUsage.booking_id == mock_booking_id
                )
            )).first()

            if existing:
                continue

            # Calculate random amounts
            original_amount = random.uniform(200, 1500)
            if promo.discount_type == "percentage":
                discount = original_amount * (promo.discount_value / 100)
                if promo.max_discount_amount:
                    discount = min(discount, promo.max_discount_amount)
            elif promo.discount_type == "fixed":
                discount = promo.discount_value
            else:
                discount = random.uniform(50, 200)  # For other types

            final_amount = original_amount - discount

            # Random date in the past 30 days
            days_ago = random.randint(1, 30)
            applied_at = datetime.utcnow() - timedelta(days=days_ago, hours=random.randint(0, 23))

            usage = PromotionUsage(
                property_id=property_id,
                promotion_id=promo.id,
                booking_id=mock_booking_id,
                guest_id=mock_guest_id,
                discount_amount=round(discount, 2),
                original_amount=round(original_amount, 2),
                final_amount=round(final_amount, 2),
                applied_at=applied_at,
            )
            session.add(usage)
            counts["usage"] += 1

    await session.commit()
    print(f"  Total usage records created: {counts['usage']}")

    # ========== PROMOTION BLACKOUT DATES ==========
    print("\n[4/5] Creating promotion blackout dates...")

    # Define blackout periods for holidays and peak periods
    blackout_periods = [
        # Holiday periods
        (date(2025, 7, 4), date(2025, 7, 5), "Independence Day"),
        (date(2025, 8, 15), date(2025, 8, 16), "Summer Peak"),
        (date(2025, 12, 24), date(2025, 12, 26), "Christmas Holiday"),
        (date(2025, 12, 31), date(2026, 1, 1), "New Year's Eve"),
        (date(2025, 11, 27), date(2025, 11, 30), "Thanksgiving Weekend"),
        (date(2025, 2, 14), date(2025, 2, 15), "Valentine's Day"),
        (date(2025, 5, 23), date(2025, 5, 26), "Memorial Day Weekend"),
        (date(2025, 9, 1), date(2025, 9, 2), "Labor Day"),
        # Special events
        (date(2025, 10, 31), date(2025, 11, 1), "Halloween"),
        (date(2025, 3, 17), date(2025, 3, 17), "St. Patrick's Day"),
    ]

    # Assign blackout dates to promotions that should have them
    blackout_eligible_codes = ["SUMMER25", "WEEKEND15", "WINTER2024", "LOYAL10", "FREENIGHT"]

    for promo in promotion_objects:
        if promo.promotion_code not in blackout_eligible_codes:
            continue

        # Assign 2-4 random blackout periods to each eligible promotion
        selected_periods = random.sample(blackout_periods, min(random.randint(2, 4), len(blackout_periods)))

        for start_date, end_date, reason in selected_periods:
            # Check if within promotion validity period
            if start_date < promo.valid_from or end_date > promo.valid_to:
                continue

            existing = (await session.exec(
                select(PromotionBlackoutDate).where(
                    PromotionBlackoutDate.promotion_id == promo.id,
                    PromotionBlackoutDate.blackout_start == start_date,
                    PromotionBlackoutDate.blackout_end == end_date
                )
            )).first()

            if existing:
                continue

            blackout = PromotionBlackoutDate(
                property_id=property_id,
                promotion_id=promo.id,
                blackout_start=start_date,
                blackout_end=end_date,
                reason=reason,
            )
            session.add(blackout)
            counts["blackout_dates"] += 1

    await session.commit()
    print(f"  Total blackout dates created: {counts['blackout_dates']}")

    # ========== PROMOTION ANALYTICS ==========
    print("\n[5/5] Creating promotion analytics records...")

    # Create daily analytics for the past 30 days for active promotions
    for promo in promotion_objects:
        if not promo.is_active:
            continue

        for days_ago in range(30):
            analytics_date = today - timedelta(days=days_ago)

            # Skip if outside promotion validity
            if analytics_date < promo.valid_from or analytics_date > promo.valid_to:
                continue

            existing = (await session.exec(
                select(PromotionAnalytics).where(
                    PromotionAnalytics.promotion_id == promo.id,
                    PromotionAnalytics.analytics_date == analytics_date
                )
            )).first()

            if existing:
                continue

            # Generate realistic metrics
            base_redemptions = random.randint(2, 15)
            # Weekend boost
            if analytics_date.weekday() >= 4:  # Fri-Sun
                base_redemptions = int(base_redemptions * 1.5)

            revenue = base_redemptions * random.uniform(150, 400)
            incremental = revenue * random.uniform(0.15, 0.35)

            # Channel breakdown
            channel_breakdown = json.dumps({
                "direct": {
                    "redemptions": int(base_redemptions * 0.45),
                    "revenue": round(revenue * 0.45, 2),
                },
                "ota": {
                    "redemptions": int(base_redemptions * 0.35),
                    "revenue": round(revenue * 0.35, 2),
                },
                "corporate": {
                    "redemptions": int(base_redemptions * 0.20),
                    "revenue": round(revenue * 0.20, 2),
                },
            })

            # Room type breakdown
            room_type_breakdown = json.dumps({
                "deluxe": {
                    "redemptions": int(base_redemptions * 0.55),
                    "revenue": round(revenue * 0.55, 2),
                },
                "suite": {
                    "redemptions": int(base_redemptions * 0.30),
                    "revenue": round(revenue * 0.30, 2),
                },
                "standard": {
                    "redemptions": int(base_redemptions * 0.15),
                    "revenue": round(revenue * 0.15, 2),
                },
            })

            analytics = PromotionAnalytics(
                property_id=property_id,
                promotion_id=promo.id,
                analytics_date=analytics_date,
                redemptions=base_redemptions,
                revenue_generated=round(revenue, 2),
                incremental_revenue=round(incremental, 2),
                adr_uplift_pct=round(random.uniform(5, 18), 1),
                occupancy_impact_pct=round(random.uniform(2, 8), 1),
                channel_breakdown=channel_breakdown,
                room_type_breakdown=room_type_breakdown,
            )
            session.add(analytics)
            counts["analytics"] += 1

    await session.commit()
    print(f"  Total analytics records created: {counts['analytics']}")

    # ========== SUMMARY ==========
    print("\n" + "=" * 60)
    print("Promotions data seeding completed!")
    print("=" * 60)
    print(f"\nSummary:")
    print(f"  - Promotions: {counts['promotions']}")
    print(f"  - Applicability rules: {counts['applicability']}")
    print(f"  - Usage records: {counts['usage']}")
    print(f"  - Blackout dates: {counts['blackout_dates']}")
    print(f"  - Analytics records: {counts['analytics']}")
    print("=" * 60)

    return counts


# Standalone execution
if __name__ == "__main__":
    import asyncio
    from app.db.session import async_session_maker, init_db

    async def main():
        await init_db()
        async with async_session_maker() as session:
            await seed_promotions_data(session, property_id=1)

    asyncio.run(main())
