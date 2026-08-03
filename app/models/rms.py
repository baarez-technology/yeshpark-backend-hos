"""
Revenue Management System (RMS) Models
Includes: PricingRule, Competitor, CompetitorRate, DemandForecast, MarketEvent, PickupPace, SegmentPerformance
"""
from datetime import datetime
from datetime import date as date_type
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, Index


class PricingRule(SQLModel, table=True):
    """Dynamic pricing rules engine for automated rate adjustments"""
    __tablename__ = "rms_pricing_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)
    rule_name: str = Field(nullable=False, index=True)
    description: Optional[str] = None
    priority: int = Field(default=3, ge=1, le=5, index=True)  # 1=highest, 5=lowest
    is_active: bool = Field(default=True, index=True)
    room_types: Optional[list] = Field(default=None, sa_column=Column(JSON))  # Array of room type IDs/codes
    conditions: Optional[list] = Field(default=None, sa_column=Column(JSON))  # Array of {type, operator, value}
    actions: Optional[list] = Field(default=None, sa_column=Column(JSON))  # Array of {type, value}
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_triggered_at: Optional[datetime] = Field(default=None, index=True)
    times_triggered: int = Field(default=0)


class Competitor(SQLModel, table=True):
    """Competitor hotel tracking for rate intelligence"""
    __tablename__ = "rms_competitors"

    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)
    name: str = Field(nullable=False, index=True)
    address: Optional[str] = None
    star_rating: Optional[float] = Field(default=None, ge=1, le=5)
    room_count: Optional[int] = None
    distance_km: Optional[float] = None
    google_place_id: Optional[str] = Field(default=None, index=True)
    booking_com_id: Optional[str] = Field(default=None, index=True)
    tripadvisor_id: Optional[str] = Field(default=None, index=True)
    is_active: bool = Field(default=True, index=True)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CompetitorRate(SQLModel, table=True):
    """Daily competitor rate tracking for competitive analysis"""
    __tablename__ = "rms_competitor_rates"

    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)
    competitor_id: int = Field(foreign_key="rms_competitors.id", index=True, nullable=False)
    rate_date: date_type = Field(nullable=False, index=True)
    room_type: Optional[str] = Field(default=None, index=True)
    rate_amount: float = Field(nullable=False)
    rate_source: Optional[str] = Field(default=None, index=True)  # booking_com, expedia, tripadvisor, direct
    currency: str = Field(default="INR")
    captured_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    __table_args__ = (
        Index('ix_competitor_rates_date_competitor', 'competitor_id', 'rate_date'),
    )


class DemandForecast(SQLModel, table=True):
    """AI-powered demand predictions for revenue optimization"""
    __tablename__ = "rms_demand_forecasts"

    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)
    forecast_date: date_type = Field(nullable=False, index=True)
    days_out: int = Field(nullable=False, index=True)  # Days from generation to forecast date
    day_of_week: int = Field(nullable=False)  # 0=Monday, 6=Sunday
    demand_index: float = Field(nullable=False)  # Normalized demand score (0-100)
    demand_level: str = Field(nullable=False, index=True)  # compression, high, normal, low, very_low
    forecasted_occupancy: Optional[float] = None  # Percentage (0-100)
    forecasted_adr: Optional[float] = None  # Average Daily Rate
    forecasted_revpar: Optional[float] = None  # Revenue per Available Room
    forecasted_revenue: Optional[float] = None  # Total forecasted revenue
    event_id: Optional[int] = Field(default=None, foreign_key="rms_market_events.id", index=True)
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)  # 0-1 confidence level
    price_recommendation: Optional[dict] = Field(default=None, sa_column=Column(JSON))  # {action, adjustment_pct, message}
    yoy_comparison: Optional[dict] = Field(default=None, sa_column=Column(JSON))  # Year-over-year metrics
    generated_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    __table_args__ = (
        Index('ix_demand_forecast_date_property', 'property_id', 'forecast_date'),
    )


class MarketEvent(SQLModel, table=True):
    """Market events affecting demand (holidays, conferences, concerts, etc.)"""
    __tablename__ = "rms_market_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)
    event_name: str = Field(nullable=False, index=True)
    event_type: str = Field(nullable=False, index=True)  # holiday, conference, sports, concert, local
    start_date: date_type = Field(nullable=False, index=True)
    end_date: date_type = Field(nullable=False, index=True)
    impact_multiplier: float = Field(default=1.0)  # Demand impact factor (e.g., 1.5 = 50% increase)
    is_recurring: bool = Field(default=False, index=True)
    recurrence_rule: Optional[str] = None  # RRULE format for recurring events
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index('ix_market_events_dates', 'property_id', 'start_date', 'end_date'),
    )


class PickupPace(SQLModel, table=True):
    """Booking pace tracking for demand monitoring"""
    __tablename__ = "rms_pickup_pace"

    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)
    arrival_date: date_type = Field(nullable=False, index=True)
    snapshot_date: date_type = Field(nullable=False, index=True)
    days_out: int = Field(nullable=False, index=True)  # Days until arrival
    current_bookings: int = Field(default=0)  # Current booking count
    expected_total: Optional[int] = None  # Expected total at this pace
    predicted_final: Optional[int] = None  # AI-predicted final bookings
    booking_progress_pct: Optional[float] = None  # Progress toward expected total
    pace_status: str = Field(default="on-pace", index=True)  # strong, on-pace, slow, critical
    ly_bookings: Optional[int] = None  # Last year bookings at same point
    ly_variance_pct: Optional[float] = None  # Variance vs last year
    lw_bookings: Optional[int] = None  # Last week bookings at same point
    lw_variance_pct: Optional[float] = None  # Variance vs last week
    alerts: Optional[list] = Field(default=None, sa_column=Column(JSON))  # Array of alert messages
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index('ix_pickup_pace_arrival_snapshot', 'property_id', 'arrival_date', 'snapshot_date'),
    )


class SegmentPerformance(SQLModel, table=True):
    """Revenue performance by market segment"""
    __tablename__ = "rms_segment_performance"

    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(foreign_key="hotel_settings.id", index=True, nullable=False)
    segment_id: Optional[int] = Field(default=None, foreign_key="market_segments.id", index=True)
    segment_name: str = Field(nullable=False, index=True)
    period_month: date_type = Field(nullable=False, index=True)  # First day of the month
    revenue: float = Field(default=0.0)
    room_nights: int = Field(default=0)
    bookings: int = Field(default=0)
    adr: Optional[float] = None  # Average Daily Rate
    revpar: Optional[float] = None  # Revenue per Available Room
    cancellations: int = Field(default=0)
    cancel_rate_pct: Optional[float] = None
    revenue_contribution_pct: Optional[float] = None  # Segment's share of total revenue
    avg_lead_time_days: Optional[float] = None  # Average booking lead time
    avg_los: Optional[float] = None  # Average length of stay
    yoy_variance_pct: Optional[float] = None  # Year-over-year variance
    optimizations: Optional[list] = Field(default=None, sa_column=Column(JSON))  # Array of optimization suggestions
    created_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index('ix_segment_perf_property_period', 'property_id', 'period_month'),
        Index('ix_segment_perf_segment_period', 'segment_id', 'period_month'),
    )
