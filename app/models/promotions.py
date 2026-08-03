"""
Promotions & Discount Management Models
Includes: Promotion, PromotionApplicability, PromotionUsage, PromotionBlackoutDate, PromotionAnalytics
"""
from datetime import datetime
from datetime import date as date_type
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, Text


class Promotion(SQLModel, table=True):
    """
    Promotional campaigns and discount offers.
    Supports percentage, fixed amount, free night, upgrade, and add-on discount types.
    """
    __tablename__ = "promotions"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)

    # Identification
    promotion_code: Optional[str] = Field(default=None, index=True)  # Unique per property, nullable for code-less promos
    title: str = Field(nullable=False)
    description: Optional[str] = None

    # Discount configuration
    discount_type: str = Field(nullable=False, index=True)  # percentage, fixed, free_night, upgrade, addon
    discount_value: float = Field(nullable=False)  # Percentage (0-100) or fixed amount

    # Status
    is_active: bool = Field(default=True, index=True)

    # Validity period
    valid_from: date_type = Field(nullable=False, index=True)
    valid_to: date_type = Field(nullable=False, index=True)

    # Stay requirements
    min_nights: Optional[int] = Field(default=None)  # Minimum nights required
    max_nights: Optional[int] = Field(default=None)  # Maximum nights allowed

    # Booking amount constraints
    min_booking_amount: Optional[float] = Field(default=None)  # Minimum booking value to qualify
    max_discount_amount: Optional[float] = Field(default=None)  # Cap on discount amount

    # Usage limits
    usage_limit: Optional[int] = Field(default=None)  # Total redemptions allowed (null = unlimited)
    usage_count: int = Field(default=0)  # Current redemption count

    # Stacking and priority
    is_stackable: bool = Field(default=False)  # Can be combined with other promos
    priority: int = Field(default=0, index=True)  # Higher priority applied first

    # Terms and conditions
    terms_and_conditions: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Audit fields
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PromotionApplicability(SQLModel, table=True):
    """
    Defines what entities a promotion applies to.
    Supports whitelist (is_included=True) and blacklist (is_included=False) patterns.
    """
    __tablename__ = "promotion_applicability"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)
    promotion_id: int = Field(foreign_key="promotions.id", index=True, nullable=False)

    # Entity definition
    entity_type: str = Field(nullable=False, index=True)  # room_type, rate_plan, channel, segment
    entity_id: int = Field(nullable=False)  # ID of the entity (room_type_id, rate_plan_id, etc.)
    entity_name: Optional[str] = Field(default=None)  # Denormalized name for convenience

    # Inclusion type
    is_included: bool = Field(default=True)  # True = whitelist (applies to), False = blacklist (excludes from)

    # Audit
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PromotionUsage(SQLModel, table=True):
    """
    Tracks individual promotion redemptions.
    Records discount amounts and booking details for each usage.
    """
    __tablename__ = "promotion_usage"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)
    promotion_id: int = Field(foreign_key="promotions.id", index=True, nullable=False)
    booking_id: int = Field(foreign_key="bookings.id", index=True, nullable=False)

    # Guest tracking (optional - for guest-specific analysis)
    guest_id: Optional[int] = Field(default=None, foreign_key="guests.id", index=True)

    # Financial details
    discount_amount: float = Field(nullable=False)  # Actual discount applied
    original_amount: float = Field(nullable=False)  # Booking total before discount
    final_amount: float = Field(nullable=False)  # Booking total after discount

    # Timestamp
    applied_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class PromotionBlackoutDate(SQLModel, table=True):
    """
    Defines date ranges when a promotion is not applicable.
    Used for holidays, peak seasons, or special events.
    """
    __tablename__ = "promotion_blackout_dates"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)
    promotion_id: int = Field(foreign_key="promotions.id", index=True, nullable=False)

    # Blackout period
    blackout_start: date_type = Field(nullable=False, index=True)
    blackout_end: date_type = Field(nullable=False, index=True)

    # Documentation
    reason: Optional[str] = Field(default=None)  # e.g., "Holiday Season", "Special Event"

    # Audit
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PromotionAnalytics(SQLModel, table=True):
    """
    Daily aggregated analytics for promotion performance.
    Tracks redemptions, revenue impact, and channel/room type breakdowns.
    """
    __tablename__ = "promotion_analytics"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)
    promotion_id: int = Field(foreign_key="promotions.id", index=True, nullable=False)

    # Date of analytics
    analytics_date: date_type = Field(nullable=False, index=True)

    # Core metrics
    redemptions: int = Field(default=0)  # Number of times redeemed on this date
    revenue_generated: float = Field(default=0.0)  # Total revenue from bookings using this promo

    # Performance indicators
    incremental_revenue: Optional[float] = Field(default=None)  # Estimated additional revenue due to promo
    adr_uplift_pct: Optional[float] = Field(default=None)  # ADR impact percentage
    occupancy_impact_pct: Optional[float] = Field(default=None)  # Occupancy impact percentage

    # Breakdowns (JSONB)
    # Format: {"direct": {"redemptions": 10, "revenue": 5000}, "ota": {"redemptions": 5, "revenue": 2500}}
    channel_breakdown: Optional[str] = Field(default=None, sa_column=Column(JSON))

    # Format: {"deluxe": {"redemptions": 8, "revenue": 4000}, "suite": {"redemptions": 7, "revenue": 3500}}
    room_type_breakdown: Optional[str] = Field(default=None, sa_column=Column(JSON))

    # Audit
    created_at: datetime = Field(default_factory=datetime.utcnow)
