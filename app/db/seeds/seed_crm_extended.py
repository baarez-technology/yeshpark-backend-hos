"""
CRM Extended Seed Data
Seeds data for: GuestActivityLog, GuestLTVSnapshot, SentimentTheme, SentimentByCategory
Based on mock data from Frontend/src/data/crm*.ts files
"""
from datetime import datetime, date, timedelta
from typing import Optional
import random

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.crm_extended import (
    GuestActivityLog,
    GuestLTVSnapshot,
    SentimentTheme,
    SentimentByCategory
)


# Activity types based on mock data
ACTIVITY_TYPES = [
    "booking", "checkin", "checkout", "review", "feedback",
    "complaint", "loyalty_redemption", "profile_update",
    "inquiry", "referral", "cancellation", "modification",
    "special_request", "tier_upgrade", "registration"
]

PLATFORMS = [
    "website", "mobile_app", "front_desk", "phone",
    "email", "ota", "kiosk", "admin_portal", "system"
]

# Sentiment themes based on mock data
POSITIVE_THEMES = [
    "friendly staff", "clean rooms", "great location", "excellent breakfast",
    "comfortable beds", "fast wifi", "beautiful view", "quiet atmosphere",
    "helpful concierge", "spacious rooms", "modern amenities", "good value"
]

NEGATIVE_THEMES = [
    "slow wifi", "noisy location", "outdated decor", "small rooms",
    "limited parking", "slow service", "expensive minibar", "poor lighting",
    "thin walls", "weak water pressure", "uncomfortable pillows"
]

# Sentiment categories
SENTIMENT_CATEGORIES = [
    "cleanliness", "staff", "location", "value",
    "amenities", "comfort", "food", "service"
]

# LTV segments
LTV_SEGMENTS = ["high", "medium", "low"]


async def seed_crm_extended_data(
    session: AsyncSession,
    property_id: int = 1,
    num_guests: int = 50
) -> dict:
    """
    Seed CRM Extended data including activity logs, LTV snapshots,
    sentiment themes, and sentiment by category.

    Args:
        session: Database session
        property_id: Property ID for multi-tenant support
        num_guests: Number of guests to create activity data for

    Returns:
        Dict with counts of created records
    """
    stats = {
        "activity_logs": 0,
        "ltv_snapshots": 0,
        "sentiment_themes": 0,
        "sentiment_categories": 0
    }

    # Check if data already exists
    existing = await session.execute(
        select(GuestActivityLog).where(
            GuestActivityLog.property_id == property_id
        ).limit(1)
    )
    if existing.scalar_one_or_none():
        print(f"CRM Extended data already exists for property {property_id}")
        return stats

    # 1. Create Guest Activity Logs
    activities = []
    for guest_id in range(1, num_guests + 1):
        # Each guest gets 3-15 activity records
        num_activities = random.randint(3, 15)

        for i in range(num_activities):
            days_ago = random.randint(0, 180)
            activity_time = datetime.utcnow() - timedelta(
                days=days_ago,
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59)
            )

            activity_type = random.choice(ACTIVITY_TYPES)
            platform = random.choice(PLATFORMS)

            # Create appropriate metadata based on activity type
            metadata = {}
            if activity_type == "booking":
                metadata = {
                    "room_type": random.choice(["Standard", "Deluxe", "Suite"]),
                    "nights": random.randint(1, 7),
                    "total_amount": random.randint(200, 2000)
                }
            elif activity_type == "loyalty_redemption":
                metadata = {
                    "points_redeemed": random.randint(1000, 10000),
                    "reward_type": random.choice(["room_upgrade", "spa_credit", "dining_credit", "free_night"])
                }
            elif activity_type == "review":
                metadata = {
                    "rating": random.randint(3, 5),
                    "source": random.choice(["google", "tripadvisor", "booking.com", "expedia"])
                }
            elif activity_type == "tier_upgrade":
                tiers = ["Bronze", "Silver", "Gold", "Platinum"]
                old_idx = random.randint(0, 2)
                metadata = {
                    "previous_tier": tiers[old_idx],
                    "new_tier": tiers[old_idx + 1]
                }

            description = _generate_activity_description(activity_type, metadata)

            activity = GuestActivityLog(
                property_id=property_id,
                guest_id=guest_id,
                activity_type=activity_type,
                description=description,
                related_entity_type=activity_type if activity_type in ["booking", "review", "feedback"] else None,
                related_entity_id=random.randint(1000, 9999) if activity_type in ["booking", "review", "feedback"] else None,
                activity_metadata=metadata if metadata else None,
                platform=platform,
                timestamp=activity_time,
                created_at=activity_time
            )
            activities.append(activity)

    session.add_all(activities)
    stats["activity_logs"] = len(activities)

    # 2. Create LTV Snapshots (monthly for last 12 months)
    ltv_snapshots = []
    for guest_id in range(1, num_guests + 1):
        # Generate guest-specific base values
        base_stays = random.randint(1, 20)
        base_revenue = random.uniform(500, 15000)
        ltv_segment = random.choices(
            LTV_SEGMENTS,
            weights=[0.2, 0.5, 0.3]
        )[0]

        first_stay_offset = random.randint(90, 730)
        first_stay = date.today() - timedelta(days=first_stay_offset)

        for month_offset in range(12):
            snapshot_date = date.today().replace(day=1) - timedelta(days=30 * month_offset)

            # Gradually increase metrics over time
            growth_factor = 1 + (0.02 * (12 - month_offset))

            total_stays = max(1, int(base_stays * growth_factor * random.uniform(0.8, 1.2)))
            total_nights = total_stays * random.randint(1, 4)
            total_revenue = base_revenue * growth_factor * random.uniform(0.9, 1.1)

            days_since_last = random.randint(0, 90) if month_offset == 0 else random.randint(30, 180)

            snapshot = GuestLTVSnapshot(
                property_id=property_id,
                guest_id=guest_id,
                snapshot_date=snapshot_date,
                total_stays=total_stays,
                total_nights=total_nights,
                total_revenue=round(total_revenue, 2),
                avg_spend_per_stay=round(total_revenue / total_stays, 2),
                avg_nights_per_stay=round(total_nights / total_stays, 2),
                first_stay_date=first_stay,
                last_stay_date=snapshot_date - timedelta(days=days_since_last),
                days_since_last_stay=days_since_last,
                predicted_ltv=round(total_revenue * random.uniform(1.5, 3.0), 2),
                ltv_segment=ltv_segment,
                created_at=datetime.combine(snapshot_date, datetime.min.time())
            )
            ltv_snapshots.append(snapshot)

    session.add_all(ltv_snapshots)
    stats["ltv_snapshots"] = len(ltv_snapshots)

    # 3. Create Sentiment Themes
    sentiment_themes = []

    # Positive themes
    for theme in POSITIVE_THEMES:
        mention_count = random.randint(50, 500)
        sentiment_theme = SentimentTheme(
            property_id=property_id,
            theme_name=theme,
            theme_type="positive",
            mention_count=mention_count,
            percentage=round(random.uniform(5, 35), 1),
            is_active=True,
            created_at=datetime.utcnow()
        )
        sentiment_themes.append(sentiment_theme)

    # Negative themes
    for theme in NEGATIVE_THEMES:
        mention_count = random.randint(10, 100)
        sentiment_theme = SentimentTheme(
            property_id=property_id,
            theme_name=theme,
            theme_type="negative",
            mention_count=mention_count,
            percentage=round(random.uniform(2, 15), 1),
            is_active=True,
            created_at=datetime.utcnow()
        )
        sentiment_themes.append(sentiment_theme)

    session.add_all(sentiment_themes)
    stats["sentiment_themes"] = len(sentiment_themes)

    # 4. Create Sentiment By Category (monthly for last 6 months)
    sentiment_categories = []

    for month_offset in range(6):
        period_start = (date.today().replace(day=1) - timedelta(days=30 * month_offset))
        period_end = (period_start + timedelta(days=29))

        for category in SENTIMENT_CATEGORIES:
            # Generate realistic sentiment distribution
            positive_pct = random.uniform(60, 90)
            negative_pct = random.uniform(5, 25)
            neutral_pct = 100 - positive_pct - negative_pct

            sentiment_cat = SentimentByCategory(
                property_id=property_id,
                category_name=category,
                positive_pct=round(positive_pct, 1),
                negative_pct=round(negative_pct, 1),
                neutral_pct=round(max(0, neutral_pct), 1),
                score=round(random.uniform(3.5, 4.8), 2),
                mention_count=random.randint(50, 300),
                period_start=period_start,
                period_end=period_end,
                created_at=datetime.combine(period_end, datetime.min.time())
            )
            sentiment_categories.append(sentiment_cat)

    session.add_all(sentiment_categories)
    stats["sentiment_categories"] = len(sentiment_categories)

    await session.commit()

    print(f"CRM Extended seed data created for property {property_id}:")
    print(f"  - Activity logs: {stats['activity_logs']}")
    print(f"  - LTV snapshots: {stats['ltv_snapshots']}")
    print(f"  - Sentiment themes: {stats['sentiment_themes']}")
    print(f"  - Sentiment categories: {stats['sentiment_categories']}")

    return stats


def _generate_activity_description(activity_type: str, metadata: dict) -> str:
    """Generate human-readable description for activity."""
    descriptions = {
        "booking": f"Booked {metadata.get('room_type', 'room')} for {metadata.get('nights', 1)} nights",
        "checkin": "Checked in to hotel",
        "checkout": "Checked out of hotel",
        "review": f"Left a {metadata.get('rating', 5)}-star review on {metadata.get('source', 'Google')}",
        "feedback": "Submitted feedback",
        "complaint": "Filed a complaint",
        "loyalty_redemption": f"Redeemed {metadata.get('points_redeemed', 0)} points for {metadata.get('reward_type', 'reward')}",
        "profile_update": "Updated profile information",
        "inquiry": "Made an inquiry",
        "referral": "Referred a new guest",
        "cancellation": "Cancelled reservation",
        "modification": "Modified booking details",
        "special_request": "Submitted special request",
        "tier_upgrade": f"Upgraded from {metadata.get('previous_tier', '')} to {metadata.get('new_tier', '')} tier",
        "registration": "Registered new account"
    }
    return descriptions.get(activity_type, f"Activity: {activity_type}")


async def clear_crm_extended_data(session: AsyncSession, property_id: int = 1):
    """Clear all CRM Extended data for a property (for testing)."""
    from sqlalchemy import delete

    await session.execute(
        delete(GuestActivityLog).where(GuestActivityLog.property_id == property_id)
    )
    await session.execute(
        delete(GuestLTVSnapshot).where(GuestLTVSnapshot.property_id == property_id)
    )
    await session.execute(
        delete(SentimentTheme).where(SentimentTheme.property_id == property_id)
    )
    await session.execute(
        delete(SentimentByCategory).where(SentimentByCategory.property_id == property_id)
    )
    await session.commit()
    print(f"Cleared CRM Extended data for property {property_id}")
