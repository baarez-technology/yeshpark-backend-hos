"""
CRM Extended Models
Enhanced CRM capabilities for guest activity tracking, LTV analysis, and sentiment analytics.
Includes: GuestActivityLog, GuestLTVSnapshot, SentimentTheme, SentimentByCategory
"""
from datetime import datetime
from datetime import date as date_type
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class GuestActivityLog(SQLModel, table=True):
    """
    Comprehensive guest activity tracking.
    Records all guest interactions across all touchpoints.
    Multi-tenant: includes property_id for property-specific data.
    """
    __tablename__ = "crm_guest_activity_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(nullable=False, index=True)  # Multi-tenant: property/hotel ID
    guest_id: int = Field(foreign_key="guests.id", nullable=False, index=True)
    activity_type: str = Field(nullable=False, index=True)  # booking, checkin, checkout, review, loyalty_redemption, profile_update, inquiry, complaint, etc.
    description: Optional[str] = None  # Human-readable description of the activity
    related_entity_type: Optional[str] = Field(default=None, index=True)  # booking, review, feedback, loyalty_transaction, etc.
    related_entity_id: Optional[int] = Field(default=None, index=True)  # ID of the related entity
    activity_metadata: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB: Extra details (amount, points, room_number, etc.)
    platform: Optional[str] = Field(default=None, index=True)  # website, mobile, front_desk, phone, email, ota, kiosk
    timestamp: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class GuestLTVSnapshot(SQLModel, table=True):
    """
    Periodic Lifetime Value (LTV) snapshots for guests.
    Used for tracking guest value over time and segmentation.
    Multi-tenant: includes property_id for property-specific data.
    """
    __tablename__ = "crm_guest_ltv_snapshots"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(nullable=False, index=True)  # Multi-tenant: property/hotel ID
    guest_id: int = Field(foreign_key="guests.id", nullable=False, index=True)
    snapshot_date: date_type = Field(nullable=False, index=True)  # Date of this snapshot

    # Stay metrics
    total_stays: int = Field(default=0)  # Total number of stays
    total_nights: int = Field(default=0)  # Total nights stayed

    # Revenue metrics
    total_revenue: float = Field(default=0.0)  # Total lifetime revenue
    avg_spend_per_stay: float = Field(default=0.0)  # Average spend per stay
    avg_nights_per_stay: float = Field(default=0.0)  # Average nights per stay

    # Recency metrics
    first_stay_date: Optional[date_type] = None  # Date of first stay
    last_stay_date: Optional[date_type] = None  # Date of last stay
    days_since_last_stay: Optional[int] = None  # Days since last visit

    # Predictive metrics
    predicted_ltv: Optional[float] = None  # Predicted future lifetime value
    ltv_segment: Optional[str] = Field(default=None, index=True)  # high, medium, low

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class SentimentTheme(SQLModel, table=True):
    """
    Extracted themes from guest reviews.
    Tracks common positive and negative themes mentioned by guests.
    Multi-tenant: includes property_id for property-specific data.
    """
    __tablename__ = "crm_sentiment_themes"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(nullable=False, index=True)  # Multi-tenant: property/hotel ID
    theme_name: str = Field(nullable=False)  # e.g., "friendly staff", "clean rooms", "slow wifi", "noisy location"
    theme_type: str = Field(nullable=False, index=True)  # positive, negative
    mention_count: int = Field(default=0, index=True)  # Number of times this theme was mentioned
    percentage: Optional[float] = None  # Percentage of reviews mentioning this theme
    is_active: bool = Field(default=True, index=True)  # Whether to track this theme
    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class SentimentByCategory(SQLModel, table=True):
    """
    Sentiment scores aggregated by category.
    Provides detailed breakdown of guest sentiment for key service areas.
    Multi-tenant: includes property_id for property-specific data.
    """
    __tablename__ = "crm_sentiment_by_category"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(nullable=False, index=True)  # Multi-tenant: property/hotel ID
    category_name: str = Field(nullable=False, index=True)  # cleanliness, staff, location, value, amenities, comfort

    # Sentiment percentages
    positive_pct: float = Field(default=0.0)  # Percentage of positive mentions
    negative_pct: float = Field(default=0.0)  # Percentage of negative mentions
    neutral_pct: float = Field(default=0.0)  # Percentage of neutral mentions

    # Score and volume
    score: float = Field(default=0.0)  # Overall score (0-5 scale)
    mention_count: int = Field(default=0)  # Number of reviews mentioning this category

    # Time period
    period_start: date_type = Field(nullable=False, index=True)  # Start of analysis period
    period_end: date_type = Field(nullable=False, index=True)  # End of analysis period

    created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)
