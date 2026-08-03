"""
Revenue Management Models
Includes: PricingAdjustments, ChannelPerformance, DynamicPricingRules, CompetitorData, ForecastData,
          PricingRecommendationRecord, RateChangeAudit, AutoPricingConfig, AIInsightRecord,
          CompetitorScrapeLog, EventRecord
"""
from datetime import datetime
from datetime import date as date_type  # Alias to avoid field name conflicts
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class PricingAdjustments(SQLModel, table=True):
    """Dynamic pricing adjustments and rules"""
    __tablename__ = "pricing_adjustments"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    adjustment_type: Optional[str] = None  # percentage_increase, percentage_decrease, fixed_amount
    adjustment_value: float = Field(nullable=False)
    applies_to: Optional[str] = Field(default=None, index=True)  # room_type, booking_source, loyalty_tier, market_segment, date_range
    entity_id: Optional[str] = Field(default=None, index=True)
    condition_type: Optional[str] = None
    condition_value: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    priority: int = Field(default=0, index=True)
    valid_from: date_type = Field(nullable=False, index=True)
    valid_to: date_type = Field(nullable=False, index=True)
    days_of_week: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    min_nights: Optional[int] = None
    min_advance_booking: Optional[int] = None
    is_active: bool = Field(default=True, index=True)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ChannelPerformance(SQLModel, table=True):
    """Track performance by booking channel"""
    __tablename__ = "channel_performance"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    date: date_type = Field(nullable=False, index=True)
    channel: str = Field(nullable=False, index=True)
    bookings_count: int = Field(default=0)
    revenue: float = Field(default=0.0)
    commission_amount: float = Field(default=0.0)
    commission_rate: Optional[float] = None
    net_revenue: Optional[float] = None
    cancellations_count: int = Field(default=0)
    cancellation_rate: Optional[float] = None
    avg_booking_value: Optional[float] = None
    avg_lead_time: Optional[int] = None  # days
    conversion_rate: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class DynamicPricingRules(SQLModel, table=True):
    """Rules for dynamic pricing based on occupancy and demand"""
    __tablename__ = "dynamic_pricing_rules"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    rule_name: str = Field(nullable=False)
    room_type_id: Optional[int] = Field(default=None, foreign_key="room_types.id", index=True)
    occupancy_threshold_min: Optional[float] = None  # percentage
    occupancy_threshold_max: Optional[float] = None  # percentage
    days_before_arrival_min: Optional[int] = None
    days_before_arrival_max: Optional[int] = None
    price_adjustment_type: str = Field(default="percentage")  # percentage, fixed
    price_adjustment_value: float = Field(nullable=False)
    priority: int = Field(default=0)
    is_active: bool = Field(default=True, index=True)
    valid_from: Optional[date_type] = Field(default=None, index=True)
    valid_to: Optional[date_type] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CompetitorData(SQLModel, table=True):
    """Track competitor pricing and occupancy"""
    __tablename__ = "competitor_data"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    competitor_name: str = Field(nullable=False, index=True)
    date: date_type = Field(nullable=False, index=True)
    room_type: Optional[str] = Field(default=None, index=True)
    rate: Optional[float] = None
    availability: Optional[int] = None
    occupancy_estimate: Optional[float] = None
    source: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ForecastData(SQLModel, table=True):
    """Revenue and occupancy forecasts"""
    __tablename__ = "forecast_data"

    id: Optional[int] = Field(default=None, primary_key=True)
    forecast_date: date_type = Field(nullable=False, index=True)
    forecast_type: str = Field(index=True)  # occupancy, revenue, adr, revpar
    forecasted_value: float = Field(nullable=False)
    actual_value: Optional[float] = None
    variance: Optional[float] = None
    variance_percentage: Optional[float] = None
    confidence_level: Optional[float] = None
    model_used: Optional[str] = None
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PricingRecommendationRecord(SQLModel, table=True):
    """Store AI pricing recommendations with status tracking"""
    __tablename__ = "pricing_recommendation_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    date: date_type = Field(nullable=False, index=True)
    room_type_id: int = Field(foreign_key="room_types.id", nullable=False, index=True)
    current_rate: float = Field(nullable=False)
    recommended_rate: float = Field(nullable=False)
    change_percent: float = Field(nullable=False)
    demand_level: str = Field(nullable=False, index=True)  # compression, high, normal, low, very_low
    confidence: float = Field(nullable=False)  # 0-1 confidence score
    reasoning: str = Field(nullable=False)
    priority: str = Field(nullable=False, index=True)  # critical, high, medium, low
    status: str = Field(default="pending", nullable=False, index=True)  # pending, accepted, dismissed
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    actioned_at: Optional[datetime] = Field(default=None, index=True)
    actioned_by: Optional[str] = Field(default=None, index=True)


class RateChangeAudit(SQLModel, table=True):
    """Track all rate changes for audit and analysis"""
    __tablename__ = "rate_change_audit"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_type_id: int = Field(foreign_key="room_types.id", nullable=False, index=True)
    date: date_type = Field(nullable=False, index=True)
    old_rate: float = Field(nullable=False)
    new_rate: float = Field(nullable=False)
    change_reason: str = Field(nullable=False, index=True)  # manual, rule, recommendation, auto
    rule_id: Optional[int] = Field(default=None, foreign_key="rms_pricing_rules.id", index=True)
    recommendation_id: Optional[int] = Field(default=None, foreign_key="pricing_recommendation_records.id", index=True)
    changed_by: str = Field(nullable=False, index=True)
    changed_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)


class AutoPricingConfig(SQLModel, table=True):
    """Auto-pricing configuration settings per room type"""
    __tablename__ = "auto_pricing_config"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_type_id: Optional[int] = Field(default=None, foreign_key="room_types.id", index=True)  # null means all rooms
    is_enabled: bool = Field(default=True, nullable=False, index=True)
    min_rate: float = Field(nullable=False)
    max_rate: float = Field(nullable=False)
    max_daily_change_percent: float = Field(nullable=False)
    competitor_tracking_enabled: bool = Field(default=False, nullable=False)
    demand_pricing_enabled: bool = Field(default=True, nullable=False)
    last_auto_update: Optional[datetime] = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AIInsightRecord(SQLModel, table=True):
    """Store AI-generated insights for revenue optimization"""
    __tablename__ = "ai_insight_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    insight_type: str = Field(nullable=False, index=True)  # opportunity, warning, recommendation, analysis
    title: str = Field(nullable=False)
    description: str = Field(nullable=False)
    revenue_impact: Optional[float] = Field(default=None)  # Estimated revenue impact
    priority: str = Field(nullable=False, index=True)  # critical, high, medium, low
    action_url: Optional[str] = Field(default=None)
    is_read: bool = Field(default=False, nullable=False, index=True)
    is_dismissed: bool = Field(default=False, nullable=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    expires_at: Optional[datetime] = Field(default=None, index=True)


class CompetitorScrapeLog(SQLModel, table=True):
    """Track competitor rate scraping jobs and their status"""
    __tablename__ = "competitor_scrape_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    competitor_id: int = Field(foreign_key="rms_competitors.id", nullable=False, index=True)
    scrape_status: str = Field(nullable=False, index=True)  # pending, running, completed, failed
    rates_found: int = Field(default=0, nullable=False)
    error_message: Optional[str] = Field(default=None)
    started_at: datetime = Field(default_factory=datetime.utcnow, nullable=False, index=True)
    completed_at: Optional[datetime] = Field(default=None, index=True)


class EventRecord(SQLModel, table=True):
    """Local events affecting hotel demand"""
    __tablename__ = "event_records"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False, index=True)
    event_type: str = Field(nullable=False, index=True)  # concert, conference, sports, festival, holiday, other
    venue: Optional[str] = Field(default=None, index=True)
    start_date: date_type = Field(nullable=False, index=True)
    end_date: date_type = Field(nullable=False, index=True)
    expected_attendance: Optional[int] = Field(default=None)
    distance_km: Optional[float] = Field(default=None)
    impact_score: float = Field(nullable=False)  # 0-10 scale
    demand_lift_percent: float = Field(nullable=False)  # Expected % increase in demand
    source: str = Field(nullable=False, index=True)  # manual, ticketmaster, scraped
    external_id: Optional[str] = Field(default=None, index=True)  # External system ID
    created_at: datetime = Field(default_factory=datetime.utcnow)

