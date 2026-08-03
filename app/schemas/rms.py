"""
Revenue Management System (RMS) Schemas
Pydantic schemas for PricingRule, Competitor, CompetitorRate, DemandForecast, MarketEvent, PickupPace, SegmentPerformance
"""
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============== PRICING RULE SCHEMAS ==============

class PricingRuleBase(BaseModel):
    """Base schema for pricing rules"""
    rule_name: str
    description: Optional[str] = None
    priority: int = Field(default=3, ge=1, le=5)
    is_active: bool = True
    room_types: Optional[List[Any]] = None  # Array of room type IDs/codes
    conditions: Optional[List[Dict[str, Any]]] = None  # Array of {type, operator, value}
    actions: Optional[List[Dict[str, Any]]] = None  # Array of {type, value}


class PricingRuleCreate(PricingRuleBase):
    """Schema for creating a pricing rule"""
    property_id: int


class PricingRuleUpdate(BaseModel):
    """Schema for updating a pricing rule - all fields optional"""
    rule_name: Optional[str] = None
    description: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=1, le=5)
    is_active: Optional[bool] = None
    room_types: Optional[List[Any]] = None
    conditions: Optional[List[Dict[str, Any]]] = None
    actions: Optional[List[Dict[str, Any]]] = None


class PricingRuleResponse(PricingRuleBase):
    """Schema for pricing rule API responses"""
    id: int
    property_id: int
    created_at: datetime
    last_triggered_at: Optional[datetime] = None
    times_triggered: int = 0

    class Config:
        from_attributes = True


# ============== COMPETITOR SCHEMAS ==============

class CompetitorBase(BaseModel):
    """Base schema for competitors"""
    name: str
    address: Optional[str] = None
    star_rating: Optional[float] = Field(default=None, ge=1, le=5)
    room_count: Optional[int] = None
    distance_km: Optional[float] = None
    google_place_id: Optional[str] = None
    booking_com_id: Optional[str] = None
    tripadvisor_id: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None


class CompetitorCreate(CompetitorBase):
    """Schema for creating a competitor"""
    property_id: int


class CompetitorUpdate(BaseModel):
    """Schema for updating a competitor - all fields optional"""
    name: Optional[str] = None
    address: Optional[str] = None
    star_rating: Optional[float] = Field(default=None, ge=1, le=5)
    room_count: Optional[int] = None
    distance_km: Optional[float] = None
    google_place_id: Optional[str] = None
    booking_com_id: Optional[str] = None
    tripadvisor_id: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class CompetitorResponse(CompetitorBase):
    """Schema for competitor API responses"""
    id: int
    property_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============== COMPETITOR RATE SCHEMAS ==============

class CompetitorRateBase(BaseModel):
    """Base schema for competitor rates"""
    competitor_id: int
    rate_date: date
    room_type: Optional[str] = None
    rate_amount: float
    rate_source: Optional[str] = None  # booking_com, expedia, tripadvisor, direct
    currency: str = "INR"


class CompetitorRateCreate(CompetitorRateBase):
    """Schema for creating a competitor rate"""
    property_id: int


class CompetitorRateUpdate(BaseModel):
    """Schema for updating a competitor rate - all fields optional"""
    rate_amount: Optional[float] = None
    room_type: Optional[str] = None
    rate_source: Optional[str] = None
    currency: Optional[str] = None


class CompetitorRateResponse(CompetitorRateBase):
    """Schema for competitor rate API responses"""
    id: int
    property_id: int
    captured_at: datetime

    class Config:
        from_attributes = True


# ============== DEMAND FORECAST SCHEMAS ==============

class DemandForecastBase(BaseModel):
    """Base schema for demand forecasts"""
    forecast_date: date
    days_out: int
    day_of_week: int  # 0=Monday, 6=Sunday
    demand_index: float
    demand_level: str  # compression, high, normal, low, very_low
    forecasted_occupancy: Optional[float] = None
    forecasted_adr: Optional[float] = None
    forecasted_revpar: Optional[float] = None
    forecasted_revenue: Optional[float] = None
    event_id: Optional[int] = None
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    price_recommendation: Optional[Dict[str, Any]] = None
    yoy_comparison: Optional[Dict[str, Any]] = None


class DemandForecastCreate(DemandForecastBase):
    """Schema for creating a demand forecast"""
    property_id: int


class DemandForecastUpdate(BaseModel):
    """Schema for updating a demand forecast - all fields optional"""
    demand_index: Optional[float] = None
    demand_level: Optional[str] = None
    forecasted_occupancy: Optional[float] = None
    forecasted_adr: Optional[float] = None
    forecasted_revpar: Optional[float] = None
    forecasted_revenue: Optional[float] = None
    event_id: Optional[int] = None
    confidence_score: Optional[float] = Field(default=None, ge=0, le=1)
    price_recommendation: Optional[Dict[str, Any]] = None
    yoy_comparison: Optional[Dict[str, Any]] = None


class DemandForecastResponse(DemandForecastBase):
    """Schema for demand forecast API responses"""
    id: int
    property_id: int
    generated_at: datetime

    class Config:
        from_attributes = True


# ============== MARKET EVENT SCHEMAS ==============

class MarketEventBase(BaseModel):
    """Base schema for market events"""
    event_name: str
    event_type: str  # holiday, conference, sports, concert, local
    start_date: date
    end_date: date
    impact_multiplier: float = 1.0
    is_recurring: bool = False
    recurrence_rule: Optional[str] = None
    notes: Optional[str] = None


class MarketEventCreate(MarketEventBase):
    """Schema for creating a market event"""
    property_id: int


class MarketEventUpdate(BaseModel):
    """Schema for updating a market event - all fields optional"""
    event_name: Optional[str] = None
    event_type: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    impact_multiplier: Optional[float] = None
    is_recurring: Optional[bool] = None
    recurrence_rule: Optional[str] = None
    notes: Optional[str] = None


class MarketEventResponse(MarketEventBase):
    """Schema for market event API responses"""
    id: int
    property_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============== PICKUP PACE SCHEMAS ==============

class PickupPaceBase(BaseModel):
    """Base schema for pickup pace tracking"""
    arrival_date: date
    snapshot_date: date
    days_out: int
    current_bookings: int = 0
    expected_total: Optional[int] = None
    predicted_final: Optional[int] = None
    booking_progress_pct: Optional[float] = None
    pace_status: str = "on-pace"  # strong, on-pace, slow, critical
    ly_bookings: Optional[int] = None
    ly_variance_pct: Optional[float] = None
    lw_bookings: Optional[int] = None
    lw_variance_pct: Optional[float] = None
    alerts: Optional[List[str]] = None


class PickupPaceCreate(PickupPaceBase):
    """Schema for creating a pickup pace record"""
    property_id: int


class PickupPaceUpdate(BaseModel):
    """Schema for updating a pickup pace record - all fields optional"""
    current_bookings: Optional[int] = None
    expected_total: Optional[int] = None
    predicted_final: Optional[int] = None
    booking_progress_pct: Optional[float] = None
    pace_status: Optional[str] = None
    ly_bookings: Optional[int] = None
    ly_variance_pct: Optional[float] = None
    lw_bookings: Optional[int] = None
    lw_variance_pct: Optional[float] = None
    alerts: Optional[List[str]] = None


class PickupPaceResponse(PickupPaceBase):
    """Schema for pickup pace API responses"""
    id: int
    property_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============== SEGMENT PERFORMANCE SCHEMAS ==============

class SegmentPerformanceBase(BaseModel):
    """Base schema for segment performance"""
    segment_id: Optional[int] = None
    segment_name: str
    period_month: date
    revenue: float = 0.0
    room_nights: int = 0
    bookings: int = 0
    adr: Optional[float] = None
    revpar: Optional[float] = None
    cancellations: int = 0
    cancel_rate_pct: Optional[float] = None
    revenue_contribution_pct: Optional[float] = None
    avg_lead_time_days: Optional[float] = None
    avg_los: Optional[float] = None
    yoy_variance_pct: Optional[float] = None
    optimizations: Optional[List[Dict[str, Any]]] = None


class SegmentPerformanceCreate(SegmentPerformanceBase):
    """Schema for creating a segment performance record"""
    property_id: int


class SegmentPerformanceUpdate(BaseModel):
    """Schema for updating a segment performance record - all fields optional"""
    revenue: Optional[float] = None
    room_nights: Optional[int] = None
    bookings: Optional[int] = None
    adr: Optional[float] = None
    revpar: Optional[float] = None
    cancellations: Optional[int] = None
    cancel_rate_pct: Optional[float] = None
    revenue_contribution_pct: Optional[float] = None
    avg_lead_time_days: Optional[float] = None
    avg_los: Optional[float] = None
    yoy_variance_pct: Optional[float] = None
    optimizations: Optional[List[Dict[str, Any]]] = None


class SegmentPerformanceResponse(SegmentPerformanceBase):
    """Schema for segment performance API responses"""
    id: int
    property_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============== LIST RESPONSE SCHEMAS ==============

class PricingRuleListResponse(BaseModel):
    """Paginated pricing rule list response"""
    items: List[PricingRuleResponse]
    total: int
    page: int
    page_size: int


class CompetitorListResponse(BaseModel):
    """Paginated competitor list response"""
    items: List[CompetitorResponse]
    total: int
    page: int
    page_size: int


class DemandForecastListResponse(BaseModel):
    """Paginated demand forecast list response"""
    items: List[DemandForecastResponse]
    total: int
    page: int
    page_size: int
