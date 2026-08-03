"""
Revenue Intelligence API Endpoints
Provides AI-powered revenue management, forecasting, and pricing optimization
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Body, Request
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import Optional, List, Dict, Any, Union
import re
from datetime import date, datetime, timedelta
from pydantic import BaseModel, Field, ConfigDict, field_validator
from enum import Enum

from app.db.session import get_tenant_session
from app.services.revenue_intelligence_service import RevenueIntelligenceService


router = APIRouter()


def _normalize_forecast_confidence_for_display(forecasts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Normalize confidence_level to 0-1 scale for client display.
    Prevents '8876% accurate' when frontend does (confidence_level * 100) + '%'.
    Service returns 0-100; we convert to 0-1 so display shows e.g. 88%.
    """
    out = []
    for f in forecasts:
        c = f.get("confidence_level", 0.85)
        if c is None:
            c = 0.85
        elif c > 1.0:
            c = min(100.0, max(0.0, float(c))) / 100.0
        else:
            c = min(1.0, max(0.0, float(c)))
        out.append({**f, "confidence_level": round(c, 4)})
    return out


# ==================== ENUMS ====================

class DemandLevel(str, Enum):
    VERY_LOW = "very_low"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class PricingActionType(str, Enum):
    ADJUST_PERCENT = "adjust_percent"
    SET_RATE = "set_rate"
    MULTIPLY_BY = "multiply_by"


class ConditionType(str, Enum):
    DEMAND_LEVEL = "demand_level"
    OCCUPANCY = "occupancy"
    DAY_OF_WEEK = "day_of_week"
    LEAD_TIME = "lead_time"


class EventType(str, Enum):
    HOLIDAY = "holiday"
    CONFERENCE = "conference"
    SPORTS = "sports"
    CONCERT = "concert"
    LOCAL = "local"
    FESTIVAL = "festival"
    OTHER = "other"


class InsightSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


# ==================== SCHEMAS ====================

class KPIResponse(BaseModel):
    total_revenue: float
    revenue_trend: float
    occupancy: float
    occupancy_trend: float
    adr: float
    adr_trend: float
    revpar: float
    revpar_trend: float
    total_bookings: int
    available_room_nights: int
    occupied_room_nights: int
    period: Dict[str, Any]


class ForecastItem(BaseModel):
    date: str
    forecasted_demand: float
    forecasted_occupancy: float
    confidence_level: float
    day_of_week: str
    is_weekend: bool
    demand_level: str


class ForecastResponse(BaseModel):
    forecasts: List[ForecastItem]
    generated_at: datetime = Field(default_factory=datetime.now)


class PricingRecommendation(BaseModel):
    date: str
    room_type_id: int
    room_type_name: str
    current_rate: float
    recommended_rate: float
    change_percent: float
    demand_level: str
    forecasted_occupancy: float
    competitor_avg: float
    confidence: float
    reasoning: str
    priority: str


class PricingRecommendationsResponse(BaseModel):
    recommendations: List[PricingRecommendation]
    total_opportunity: float = 0
    generated_at: datetime = Field(default_factory=datetime.now)


class RevenueOpportunity(BaseModel):
    type: str
    title: str
    description: str
    revenue_impact: float
    priority: str
    action: str
    date: Optional[str] = None
    confidence: float


class OpportunitiesResponse(BaseModel):
    opportunities: List[RevenueOpportunity]
    total_opportunity: float
    generated_at: datetime = Field(default_factory=datetime.now)


class RevenueAlert(BaseModel):
    id: str
    type: str
    severity: str
    title: str
    message: str
    date: Optional[str] = None
    created_at: str


class AlertsResponse(BaseModel):
    alerts: List[RevenueAlert]
    critical_count: int = 0
    warning_count: int = 0


class ScenarioSimulateRequest(BaseModel):
    scenario_type: str  # rate_increase, rate_decrease, promotion
    parameters: Dict[str, Any]


class ScenarioResponse(BaseModel):
    scenario_type: str
    parameters: Dict[str, Any]
    baseline: Dict[str, Any]
    projected: Dict[str, Any]
    recommendation: str
    confidence: float
    simulated_at: str


class ChannelPerformance(BaseModel):
    channel: str
    total_bookings: int
    total_revenue: float
    total_commission: float
    net_revenue: float
    commission_rate: float
    cancellation_rate: float
    avg_booking_value: float
    revenue_share: float
    booking_share: float


class ChannelAnalysisResponse(BaseModel):
    period: Dict[str, str]
    channels: List[ChannelPerformance]
    totals: Dict[str, Any]
    recommendations: List[Dict[str, Any]]


# ==================== NEW SCHEMAS ====================

# --- Pricing Recommendation Actions ---

class RecommendationAcceptResponse(BaseModel):
    success: bool
    recommendation_id: int
    applied_rate: float
    room_type_id: int
    date: str
    audit_id: int
    message: str


class RecommendationDismissResponse(BaseModel):
    success: bool
    recommendation_id: int
    message: str


class BulkApplyResponse(BaseModel):
    success: bool
    applied_count: int
    failed_count: int
    total_revenue_impact: float
    results: List[Dict[str, Any]]


class BulkDismissResponse(BaseModel):
    success: bool
    dismissed_count: int
    message: str


# --- Rate Management ---

class RateUpdateRequest(BaseModel):
    rate: float = Field(..., gt=0, description="New rate to set")
    reason: Optional[str] = Field(None, description="Reason for rate change")


class RateUpdateResponse(BaseModel):
    success: bool
    room_type_id: int
    date: str
    previous_rate: float
    new_rate: float
    change_percent: float
    audit_id: int
    message: str


class BulkRateUpdateItem(BaseModel):
    room_type_id: int
    date: date
    rate: float = Field(..., gt=0)


class BulkRateUpdateRequest(BaseModel):
    updates: List[BulkRateUpdateItem]
    reason: Optional[str] = Field(None, description="Reason for bulk update")


class BulkRateUpdateResponse(BaseModel):
    success: bool
    updated_count: int
    failed_count: int
    audit_ids: List[int]
    results: List[Dict[str, Any]]


class RateCalendarItem(BaseModel):
    date: str
    room_type_id: int
    room_type_name: str
    base_rate: float
    effective_rate: float
    occupancy: float
    demand_level: str
    has_event: bool
    event_name: Optional[str] = None
    available: int = 0


class RateCalendarResponse(BaseModel):
    period: Dict[str, str]
    calendar: List[RateCalendarItem]
    summary: Dict[str, Any]


# --- Pricing Rules ---

class PricingRuleCondition(BaseModel):
    type: ConditionType
    operator: str = Field(..., description="Comparison operator: eq, ne, gt, lt, gte, lte, in")
    value: Any = Field(..., description="Value to compare against")


class PricingRuleAction(BaseModel):
    type: PricingActionType
    value: float = Field(..., description="Action value (percentage, rate, or multiplier)")


class PricingRuleCreate(BaseModel):
    rule_name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    room_type_id: Optional[int] = Field(None, description="Apply to specific room type, or all if None")
    priority: int = Field(3, ge=1, le=5, description="Priority 1-5, lower = higher priority")
    conditions: List[PricingRuleCondition]
    actions: List[PricingRuleAction]
    is_active: bool = True
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None


def _parse_pricing_rule_body(body: Dict[str, Any]) -> Dict[str, Any]:
    """Parse pricing rule body accepting camelCase or snake_case; coerce types to avoid 422.
    Supports flat body or nested body.data (frontend may send { data: { ruleName, ... } }).
    """
    # Flatten: if body has a "data" key that is a dict, merge it so we read from both levels
    flat: Dict[str, Any] = dict(body)
    if "data" in flat and isinstance(flat["data"], dict):
        for k, v in flat["data"].items():
            if k not in flat or flat[k] is None:
                flat[k] = v

    def get(key_snake: str, key_camel: str, default: Any = None, coerce_int: bool = False, coerce_str: bool = False, coerce_bool: bool = False) -> Any:
        v = flat.get(key_camel) if key_camel in flat else flat.get(key_snake, default)
        if v is None or v == "":
            return default
        if coerce_int:
            try:
                return int(v) if not isinstance(v, int) else v
            except (TypeError, ValueError):
                return default if default is not None else 0
        if coerce_str:
            return str(v).strip() if v is not None else (default or "")
        if coerce_bool:
            if isinstance(v, bool):
                return v
            if isinstance(v, str):
                return v.lower() in ("true", "1", "yes", "on")
            return bool(v)
        return v

    # Map frontend condition types to backend types
    CONDITION_TYPE_MAP = {
        "occupancy_above": ("occupancy", "gte"),
        "occupancy_below": ("occupancy", "lte"),
        "demand_high": ("demand_level", "eq"),
        "demand_low": ("demand_level", "eq"),
        "day_of_week": ("day_of_week", "eq"),
        "lead_time": ("lead_time", "gte"),
    }
    
    # Parse conditions
    conditions_raw = flat.get("conditions") or flat.get("Conditions") or []
    conditions = []
    if isinstance(conditions_raw, list):
        for cond in conditions_raw:
            if isinstance(cond, dict):
                cond_type = cond.get("type") or cond.get("Type") or ""
                cond_operator = cond.get("operator") or cond.get("Operator")
                cond_value = cond.get("value") or cond.get("Value")
                
                # Map frontend condition types to backend format
                if cond_type in CONDITION_TYPE_MAP:
                    mapped_type, default_op = CONDITION_TYPE_MAP[cond_type]
                    conditions.append({
                        "type": mapped_type,
                        "operator": cond_operator or default_op,
                        "value": cond_value
                    })
                else:
                    # Use as-is if already in backend format
                    conditions.append({
                        "type": cond_type,
                        "operator": cond_operator or "eq",
                        "value": cond_value
                    })

    # Map frontend action types to backend types
    ACTION_TYPE_MAP = {
        "increase_percent": "adjust_percent",
        "decrease_percent": "adjust_percent",
        "set_price": "set_rate",
        "set_rate": "set_rate",  # Also accept backend format
        "multiply": "multiply_by",
        "multiply_by": "multiply_by",  # Also accept backend format
        "adjust_percent": "adjust_percent",  # Also accept backend format
    }
    
    # Parse actions
    actions_raw = flat.get("actions") or flat.get("Actions") or []
    actions = []
    if isinstance(actions_raw, list):
        for act in actions_raw:
            if isinstance(act, dict):
                act_type = act.get("type") or act.get("Type") or ""
                act_value = act.get("value") or act.get("Value")
                
                # Map frontend action types to backend format
                if act_type in ACTION_TYPE_MAP:
                    mapped_type = ACTION_TYPE_MAP[act_type]
                    # For decrease_percent, make value negative (backend uses positive for increase, negative for decrease)
                    if act_type == "decrease_percent" and isinstance(act_value, (int, float)):
                        act_value = -abs(float(act_value))
                    # For increase_percent, ensure value is positive
                    elif act_type == "increase_percent" and isinstance(act_value, (int, float)):
                        act_value = abs(float(act_value))
                    actions.append({
                        "type": mapped_type,
                        "value": act_value
                    })
                else:
                    # Use as-is if already in backend format
                    actions.append({
                        "type": act_type,
                        "value": act_value
                    })

    # Parse dates
    valid_from_raw = flat.get("validFrom") or flat.get("valid_from")
    valid_to_raw = flat.get("validTo") or flat.get("valid_to")
    
    valid_from = None
    valid_to = None
    
    if valid_from_raw:
        try:
            if isinstance(valid_from_raw, str):
                valid_from = date.fromisoformat(valid_from_raw.split("T")[0])
            elif isinstance(valid_from_raw, date):
                valid_from = valid_from_raw
        except (ValueError, AttributeError):
            pass
    
    if valid_to_raw:
        try:
            if isinstance(valid_to_raw, str):
                valid_to = date.fromisoformat(valid_to_raw.split("T")[0])
            elif isinstance(valid_to_raw, date):
                valid_to = valid_to_raw
        except (ValueError, AttributeError):
            pass

    # Handle rule_name - frontend may send "name" instead
    rule_name = get("rule_name", "ruleName", coerce_str=True) or flat.get("name") or ""
    if isinstance(rule_name, str):
        rule_name = rule_name.strip()
    
    # Handle room_type_id - frontend may send "room_types" array with "ALL" or room type IDs
    room_type_id = get("room_type_id", "roomTypeId", coerce_int=True)
    if room_type_id is None:
        room_types = flat.get("room_types") or flat.get("roomTypes") or []
        if isinstance(room_types, list) and len(room_types) > 0:
            first_room_type = room_types[0]
            if first_room_type == "ALL" or first_room_type == "all":
                room_type_id = None  # None means apply to all room types
            else:
                try:
                    room_type_id = int(first_room_type) if not isinstance(first_room_type, int) else first_room_type
                except (TypeError, ValueError):
                    room_type_id = None
    
    return {
        "rule_name": rule_name,
        "description": get("description", "Description") or None,
        "room_type_id": room_type_id,
        "priority": get("priority", "Priority", default=3, coerce_int=True) or 3,
        "conditions": conditions,
        "actions": actions,
        "is_active": get("is_active", "isActive", default=True, coerce_bool=True),
        "valid_from": valid_from,
        "valid_to": valid_to,
    }


class PricingRuleUpdate(BaseModel):
    rule_name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    room_type_id: Optional[int] = None
    priority: Optional[int] = Field(None, ge=1, le=5)
    conditions: Optional[List[PricingRuleCondition]] = None
    actions: Optional[List[PricingRuleAction]] = None
    is_active: Optional[bool] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None


class PricingRuleResponse(BaseModel):
    id: int
    rule_name: str
    description: Optional[str]
    room_type_id: Optional[Union[int, str]] = None  # Can be int, 'ALL', or None
    room_type_name: Optional[str]
    priority: int
    conditions: List[Dict[str, Any]]
    actions: List[Dict[str, Any]]
    is_active: bool
    valid_from: Optional[str]
    valid_to: Optional[str]
    times_triggered: int
    last_triggered_at: Optional[str]
    created_at: str


class PricingRulesListResponse(BaseModel):
    rules: List[PricingRuleResponse]
    total: int
    active_count: int


class RuleToggleResponse(BaseModel):
    success: bool
    rule_id: int
    is_active: bool
    message: str


class RuleExecutionResult(BaseModel):
    rule_id: int
    rule_name: str
    rates_adjusted: int
    revenue_impact: float
    status: str
    message: str


class RuleExecutionResponse(BaseModel):
    success: bool
    executed_rules: int
    total_rates_adjusted: int
    total_revenue_impact: float
    results: List[RuleExecutionResult]


# --- Auto-Pricing Settings ---

class AutoPricingConfig(BaseModel):
    enabled: bool
    min_rate_adjustment: float = Field(-30, description="Minimum rate adjustment percent")
    max_rate_adjustment: float = Field(50, description="Maximum rate adjustment percent")
    auto_accept_threshold: float = Field(5, description="Auto-accept recommendations below this change percent")
    competitor_weight: float = Field(0.3, ge=0, le=1, description="Weight for competitor pricing")
    demand_weight: float = Field(0.5, ge=0, le=1, description="Weight for demand forecast")
    historical_weight: float = Field(0.2, ge=0, le=1, description="Weight for historical data")
    room_type_overrides: Optional[Dict[int, Dict[str, Any]]] = Field(None, description="Per-room-type config")
    update_frequency: str = Field("daily", description="How often to run auto-pricing: hourly, daily, weekly")
    last_run: Optional[str] = None


class AutoPricingUpdateRequest(BaseModel):
    enabled: Optional[bool] = None
    min_rate_adjustment: Optional[float] = Field(None, ge=-50, le=0)
    max_rate_adjustment: Optional[float] = Field(None, ge=0, le=100)
    auto_accept_threshold: Optional[float] = Field(None, ge=0, le=20)
    competitor_weight: Optional[float] = Field(None, ge=0, le=1)
    demand_weight: Optional[float] = Field(None, ge=0, le=1)
    historical_weight: Optional[float] = Field(None, ge=0, le=1)
    room_type_overrides: Optional[Dict[int, Dict[str, Any]]] = None
    update_frequency: Optional[str] = None


class AutoPricingConfigResponse(BaseModel):
    success: bool
    config: AutoPricingConfig
    message: str


class AutoPricingToggleResponse(BaseModel):
    success: bool
    enabled: bool
    message: str


# --- Competitor Management ---

class CompetitorCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    address: Optional[str] = None
    star_rating: Optional[float] = Field(None, ge=1, le=5)
    room_count: Optional[int] = Field(None, ge=1)
    distance_km: Optional[float] = Field(None, ge=0)
    google_place_id: Optional[str] = None
    booking_com_id: Optional[str] = None
    tripadvisor_id: Optional[str] = None
    notes: Optional[str] = None


class CompetitorUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    address: Optional[str] = None
    star_rating: Optional[float] = Field(None, ge=1, le=5)
    room_count: Optional[int] = Field(None, ge=1)
    distance_km: Optional[float] = Field(None, ge=0)
    google_place_id: Optional[str] = None
    booking_com_id: Optional[str] = None
    tripadvisor_id: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class CompetitorResponse(BaseModel):
    id: int
    name: str
    address: Optional[str]
    star_rating: Optional[float]
    room_count: Optional[int]
    distance_km: Optional[float]
    google_place_id: Optional[str]
    booking_com_id: Optional[str]
    tripadvisor_id: Optional[str]
    is_active: bool
    notes: Optional[str]
    created_at: str
    updated_at: str


class CompetitorsListResponse(BaseModel):
    competitors: List[CompetitorResponse]
    total: int


class CompetitorDeleteResponse(BaseModel):
    success: bool
    competitor_id: int
    message: str


class CompetitorRefreshResponse(BaseModel):
    success: bool
    competitors_updated: int
    rates_scraped: int
    last_refresh: str
    message: str


class CompetitorRateItem(BaseModel):
    date: str
    room_type: Optional[str]
    rate_amount: float
    rate_source: Optional[str]
    captured_at: str


class CompetitorRatesResponse(BaseModel):
    competitor_id: int
    competitor_name: str
    period: Dict[str, str]
    rates: List[CompetitorRateItem]
    average_rate: float
    rate_trend: float


# --- AI Insights ---

class AIInsight(BaseModel):
    id: str
    type: str
    severity: InsightSeverity
    title: str
    message: str
    recommendation: str
    potential_impact: float
    confidence: float
    data: Optional[Dict[str, Any]] = None
    is_read: bool
    is_dismissed: bool
    created_at: str


class AIInsightsResponse(BaseModel):
    insights: List[AIInsight]
    unread_count: int
    critical_count: int
    generated_at: str


class InsightActionResponse(BaseModel):
    success: bool
    insight_id: str
    message: str


# --- Segments ---

class SegmentPerformanceItem(BaseModel):
    segment_name: str
    segment_id: Optional[int]
    revenue: float
    room_nights: int
    bookings: int
    adr: float
    revpar: float
    revenue_contribution_pct: float
    avg_lead_time_days: float
    avg_los: float
    cancellation_rate: float
    yoy_variance_pct: Optional[float]


class SegmentPerformanceResponse(BaseModel):
    period: Dict[str, str]
    segments: List[SegmentPerformanceItem]
    totals: Dict[str, Any]
    top_performer: str
    recommendations: List[str]


# --- Events ---

class EventCreate(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=200)
    event_type: EventType
    start_date: date
    end_date: date
    impact_multiplier: float = Field(1.0, ge=0.5, le=3.0, description="Demand impact factor")
    is_recurring: bool = False
    recurrence_rule: Optional[str] = Field(None, description="RRULE format for recurring events")
    notes: Optional[str] = None


class EventUpdate(BaseModel):
    event_name: Optional[str] = Field(None, min_length=1, max_length=200)
    event_type: Optional[EventType] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    impact_multiplier: Optional[float] = Field(None, ge=0.5, le=3.0)
    is_recurring: Optional[bool] = None
    recurrence_rule: Optional[str] = None
    notes: Optional[str] = None


class EventResponse(BaseModel):
    id: int
    event_name: str
    event_type: str
    start_date: str
    end_date: str
    impact_multiplier: float
    is_recurring: bool
    recurrence_rule: Optional[str]
    notes: Optional[str]
    created_at: str


class EventsListResponse(BaseModel):
    events: List[EventResponse]
    total: int
    upcoming_count: int


class EventCalendarItem(BaseModel):
    date: str
    events: List[Dict[str, Any]]
    combined_impact: float


class EventCalendarResponse(BaseModel):
    period: Dict[str, str]
    calendar: List[EventCalendarItem]
    events_in_period: int


class EventImpactItem(BaseModel):
    event_id: int
    event_name: str
    event_type: str
    start_date: str
    end_date: str
    days_duration: int
    impact_multiplier: float
    estimated_demand_increase: float
    estimated_revenue_impact: float
    recommended_rate_adjustment: float


class EventImpactResponse(BaseModel):
    period: Dict[str, str]
    events: List[EventImpactItem]
    total_revenue_opportunity: float
    recommendations: List[str]


# ==================== ENDPOINTS ====================

@router.get("/kpis", response_model=KPIResponse, tags=["Revenue Intelligence"])
async def get_kpis(
    start_date: Optional[date] = Query(None, description="Start date for KPI calculation"),
    end_date: Optional[date] = Query(None, description="End date for KPI calculation"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get real-time revenue KPIs including RevPAR, ADR, Occupancy, and trends."""
    service = RevenueIntelligenceService(session)
    return await service.get_realtime_kpis(start_date, end_date)


@router.get("/kpis/summary", tags=["Revenue Intelligence"])
async def get_kpi_summary(
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get KPI summary for multiple time periods (today, 7d, 30d, next 7d, next 30d)."""
    service = RevenueIntelligenceService(session)
    return await service.get_kpi_summary()


@router.get("/forecast", response_model=ForecastResponse, tags=["Revenue Intelligence"])
async def get_demand_forecast(
    start_date: Optional[date] = Query(None, description="Forecast start date"),
    end_date: Optional[date] = Query(None, description="Forecast end date"),
    room_type_id: Optional[int] = Query(None, description="Filter by room type"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get AI-powered demand forecast for the specified period."""
    service = RevenueIntelligenceService(session)
    forecasts = await service.get_demand_forecast(start_date, end_date, room_type_id)
    # Normalize confidence to 0-1 so frontend (confidence * 100) shows e.g. 88% not 8876%
    forecasts = _normalize_forecast_confidence_for_display(forecasts)
    return ForecastResponse(forecasts=forecasts)


@router.get("/forecast/high-impact", tags=["Revenue Intelligence"])
async def get_high_impact_days(
    days: int = Query(30, description="Number of days to look ahead"),
    threshold: float = Query(80, description="Occupancy threshold for high impact"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get high-impact days with demand exceeding threshold."""
    service = RevenueIntelligenceService(session)
    forecasts = await service.get_demand_forecast(
        start_date=date.today(),
        end_date=date.today() + __import__('datetime').timedelta(days=days)
    )

    high_impact = [
        f for f in forecasts
        if f.get("forecasted_occupancy", 0) >= threshold
    ]

    return {
        "high_impact_days": high_impact,
        "count": len(high_impact),
        "threshold": threshold
    }


@router.get("/pricing/recommendations", response_model=PricingRecommendationsResponse, tags=["Revenue Intelligence"])
async def get_pricing_recommendations(
    start_date: Optional[date] = Query(None, description="Start date for recommendations"),
    end_date: Optional[date] = Query(None, description="End date for recommendations"),
    room_type_id: Optional[int] = Query(None, description="Filter by room type"),
    priority: Optional[str] = Query(None, description="Filter by priority (critical, high, medium, low)"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get AI-powered pricing recommendations based on demand and market analysis."""
    service = RevenueIntelligenceService(session)
    recommendations = await service.get_pricing_recommendations(start_date, end_date, room_type_id)

    if priority:
        recommendations = [r for r in recommendations if r["priority"] == priority]

    total_opportunity = sum(
        abs(r["recommended_rate"] - r["current_rate"]) * 10
        for r in recommendations
        if r["change_percent"] > 0
    )

    return PricingRecommendationsResponse(
        recommendations=recommendations,
        total_opportunity=round(total_opportunity, 2)
    )


@router.get("/opportunities", response_model=OpportunitiesResponse, tags=["Revenue Intelligence"])
async def get_revenue_opportunities(
    limit: int = Query(20, description="Maximum number of opportunities to return"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get AI-identified revenue opportunities and optimization suggestions."""
    service = RevenueIntelligenceService(session)
    opportunities = await service.get_revenue_opportunities(limit)

    total_opportunity = sum(o.get("revenue_impact", 0) for o in opportunities)

    return OpportunitiesResponse(
        opportunities=opportunities,
        total_opportunity=round(total_opportunity, 2)
    )


@router.get("/alerts", response_model=AlertsResponse, tags=["Revenue Intelligence"])
async def get_revenue_alerts(
    severity: Optional[str] = Query(None, description="Filter by severity (critical, warning, info)"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get revenue-related alerts and warnings."""
    service = RevenueIntelligenceService(session)
    alerts = await service.get_revenue_alerts(severity)

    critical_count = len([a for a in alerts if a["severity"] == "critical"])
    warning_count = len([a for a in alerts if a["severity"] == "warning"])

    return AlertsResponse(
        alerts=alerts,
        critical_count=critical_count,
        warning_count=warning_count
    )


@router.post("/scenarios/simulate", response_model=ScenarioResponse, tags=["Revenue Intelligence"])
async def simulate_scenario(
    request: ScenarioSimulateRequest,
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Simulate a pricing or revenue scenario.

    Supported scenario types:
    - rate_increase / pricing_change: Simulate rate increase with elasticity (parameter: percentage)
    - rate_decrease: Simulate rate decrease with elasticity (parameter: percentage)
    - promotion: Simulate promotional offer (parameters: discount, demand_lift)
    """
    service = RevenueIntelligenceService(session)
    try:
        result = await service.simulate_scenario(
            scenario_type=request.scenario_type,
            parameters=request.parameters
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/channels", response_model=ChannelAnalysisResponse, tags=["Revenue Intelligence"])
async def get_channel_analysis(
    start_date: Optional[date] = Query(None, description="Analysis start date"),
    end_date: Optional[date] = Query(None, description="Analysis end date"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get channel performance analysis with recommendations."""
    service = RevenueIntelligenceService(session)
    return await service.get_channel_analysis(start_date, end_date)


@router.get("/channels/roi", tags=["Revenue Intelligence"])
async def get_channel_roi(
    start_date: Optional[date] = Query(None, description="Analysis start date"),
    end_date: Optional[date] = Query(None, description="Analysis end date"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get channel ROI analysis comparing commission costs vs revenue."""
    service = RevenueIntelligenceService(session)
    analysis = await service.get_channel_analysis(start_date, end_date)

    roi_data = []
    for channel in analysis["channels"]:
        net_margin = channel["net_revenue"] / channel["total_revenue"] * 100 if channel["total_revenue"] > 0 else 0
        roi_data.append({
            "channel": channel["channel"],
            "gross_revenue": channel["total_revenue"],
            "commission_cost": channel["total_commission"],
            "net_revenue": channel["net_revenue"],
            "net_margin_percent": round(net_margin, 1),
            "commission_rate": round(channel["commission_rate"], 1),
            "roi_score": round(100 - channel["commission_rate"], 1)
        })

    # Sort by ROI score
    roi_data.sort(key=lambda x: x["roi_score"], reverse=True)

    return {
        "period": analysis["period"],
        "roi_analysis": roi_data,
        "recommendation": "Focus on channels with ROI score > 85 for higher margins"
    }


@router.get("/competitor-insights", tags=["Revenue Intelligence"])
async def get_competitor_insights(
    start_date: Optional[date] = Query(None, description="Analysis start date"),
    end_date: Optional[date] = Query(None, description="Analysis end date"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get competitor pricing insights and market positioning."""
    from sqlmodel import select, and_
    from app.models.revenue import CompetitorData
    from datetime import timedelta

    if not start_date:
        start_date = date.today() - timedelta(days=30)
    if not end_date:
        end_date = date.today()

    result = await session.exec(
        select(CompetitorData).where(
            and_(
                CompetitorData.date >= start_date,
                CompetitorData.date <= end_date
            )
        )
    )
    competitors = result.all()

    # Aggregate competitor data
    competitor_summary = {}
    for comp in competitors:
        if comp.competitor_name not in competitor_summary:
            competitor_summary[comp.competitor_name] = {
                "name": comp.competitor_name,
                "rates": [],
                "occupancy_estimates": []
            }
        if comp.rate:
            competitor_summary[comp.competitor_name]["rates"].append(comp.rate)
        if comp.occupancy_estimate:
            competitor_summary[comp.competitor_name]["occupancy_estimates"].append(comp.occupancy_estimate)

    # Calculate averages and insights
    insights = []
    for name, data in competitor_summary.items():
        avg_rate = sum(data["rates"]) / len(data["rates"]) if data["rates"] else 0
        avg_occupancy = sum(data["occupancy_estimates"]) / len(data["occupancy_estimates"]) if data["occupancy_estimates"] else 0

        insights.append({
            "competitor": name,
            "avg_rate": round(avg_rate, 2),
            "avg_occupancy": round(avg_occupancy, 1),
            "data_points": len(data["rates"])
        })

    # Calculate market position
    if insights:
        market_avg_rate = sum(i["avg_rate"] for i in insights) / len(insights)
        market_avg_occupancy = sum(i["avg_occupancy"] for i in insights) / len(insights)
    else:
        market_avg_rate = 0
        market_avg_occupancy = 0

    return {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat()
        },
        "competitors": insights,
        "market_averages": {
            "avg_rate": round(market_avg_rate, 2),
            "avg_occupancy": round(market_avg_occupancy, 1)
        },
        "positioning_recommendation": "Price within 5% of market average for optimal competitiveness"
    }


@router.get("/metrics/pickup", tags=["Revenue Intelligence"])
async def get_pickup_metrics(
    days: int = Query(7, description="Number of days to analyze"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get pickup (booking pace) metrics for upcoming dates."""
    from sqlmodel import select, func, and_
    from app.models.reservations import Booking
    from app.models.inventory import Room
    from datetime import timedelta

    today = date.today()
    target_dates = [today + timedelta(days=i) for i in range(days)]

    # Get total rooms once (exclude out_of_service)
    rooms_result = await session.exec(
        select(func.count(Room.id)).where(Room.status != 'out_of_service')
    )
    total_rooms = rooms_result.one() or 70

    pickup_data = []
    for target in target_dates:
        # Count bookings for this arrival date (using Booking table, not legacy Reservation)
        result = await session.exec(
            select(func.count(Booking.id)).where(
                and_(
                    Booking.arrival_date == target,
                    Booking.status.in_(['pending', 'confirmed', 'checked_in', 'booked'])
                )
            )
        )
        booked = result.one() or 0

        remaining = total_rooms - booked
        occupancy = (booked / total_rooms * 100) if total_rooms > 0 else 0

        # Determine pace status
        days_to_arrival = (target - today).days
        expected_occupancy = max(50, 90 - days_to_arrival * 3)  # Expected booking curve

        if occupancy >= expected_occupancy + 10:
            pace = "strong"
        elif occupancy >= expected_occupancy - 10:
            pace = "on_pace"
        else:
            pace = "critical"

        pickup_data.append({
            "date": target.isoformat(),
            "day_of_week": target.strftime("%A"),
            "days_to_arrival": days_to_arrival,
            "booked": booked,
            "remaining": remaining,
            "occupancy": round(occupancy, 1),
            "expected_occupancy": round(expected_occupancy, 1),
            "pace": pace
        })

    # Calculate summary metrics
    strong_days = len([d for d in pickup_data if d["pace"] == "strong"])
    critical_days = len([d for d in pickup_data if d["pace"] == "critical"])
    on_pace_days = len([d for d in pickup_data if d["pace"] == "on_pace"])
    total_remaining = sum(d["remaining"] for d in pickup_data)
    total_booked = sum(d["booked"] for d in pickup_data)
    avg_occupancy = round(sum(d["occupancy"] for d in pickup_data) / len(pickup_data), 1) if pickup_data else 0

    # Generate AI insights based on pickup patterns
    ai_insights = []
    if critical_days > days * 0.4:
        ai_insights.append({
            "type": "warning",
            "priority": "high",
            "title": "Significant Pickup Weakness Detected",
            "message": f"{critical_days} of {days} upcoming days show critical booking pace. Revenue targets are at risk without intervention.",
            "action": "Activate last-minute promotions and consider dynamic rate reductions for underperforming dates."
        })
    if strong_days > days * 0.3:
        ai_insights.append({
            "type": "opportunity",
            "priority": "high",
            "title": "Strong Demand Window Identified",
            "message": f"{strong_days} days show strong booking pace. There may be room to increase rates and maximize revenue.",
            "action": "Review rates for strong-pace dates and consider 5-15% rate increases where demand supports it."
        })
    # Check for near-term gaps (next 7 days with low occupancy)
    near_term_critical = [d for d in pickup_data if d["days_to_arrival"] <= 7 and d["pace"] == "critical"]
    if near_term_critical:
        ai_insights.append({
            "type": "warning",
            "priority": "high",
            "title": "Near-Term Occupancy Gap",
            "message": f"{len(near_term_critical)} dates within the next 7 days have critical pace. Last-minute action is needed.",
            "action": "Deploy flash sales, OTA promotions, or corporate outreach for immediate occupancy lift."
        })
    # Weekend vs weekday pattern
    weekend_data = [d for d in pickup_data if d["day_of_week"] in ("Friday", "Saturday", "Sunday")]
    weekday_data = [d for d in pickup_data if d["day_of_week"] not in ("Friday", "Saturday", "Sunday")]
    if weekend_data and weekday_data:
        weekend_avg = sum(d["occupancy"] for d in weekend_data) / len(weekend_data)
        weekday_avg = sum(d["occupancy"] for d in weekday_data) / len(weekday_data)
        if weekend_avg > weekday_avg + 15:
            ai_insights.append({
                "type": "info",
                "priority": "medium",
                "title": "Weekend Premium Opportunity",
                "message": f"Weekend occupancy ({weekend_avg:.0f}%) significantly outpaces weekdays ({weekday_avg:.0f}%). Consider weekend rate premiums.",
                "action": "Apply weekend surcharge or create midweek promotions to balance demand."
            })
        elif weekday_avg > weekend_avg + 10:
            ai_insights.append({
                "type": "info",
                "priority": "medium",
                "title": "Strong Midweek Demand",
                "message": f"Weekday occupancy ({weekday_avg:.0f}%) exceeds weekends ({weekend_avg:.0f}%). Business travel may be driving demand.",
                "action": "Consider weekend leisure packages to boost weekend bookings."
            })
    if avg_occupancy > 80:
        ai_insights.append({
            "type": "opportunity",
            "priority": "medium",
            "title": "High Overall Demand",
            "message": f"Average forecasted occupancy is {avg_occupancy}%. This is an excellent revenue optimization window.",
            "action": "Review all rate plans and ensure minimum rate thresholds are set appropriately."
        })

    return {
        "next_days": days,
        "pickup_data": pickup_data,
        "summary": {
            "strong_pace_days": strong_days,
            "critical_pace_days": critical_days,
            "on_pace_days": on_pace_days,
            "total_remaining_rooms": total_remaining,
            "total_booked": total_booked,
            "avg_occupancy": avg_occupancy
        },
        "ai_insights": ai_insights
    }


@router.get("/dashboard", tags=["Revenue Intelligence"])
async def get_revenue_dashboard(
    start_date: Optional[str] = Query(None, description="Custom range start (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="Custom range end (YYYY-MM-DD)"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get complete revenue intelligence dashboard data in a single call.

    When start_date and end_date are provided, an additional 'custom' KPI
    bucket is included alongside the standard periods, and the forecast
    and recommendations windows are extended to cover the custom range.
    """
    service = RevenueIntelligenceService(session)

    # Parse optional custom date range
    custom_start: Optional[date] = None
    custom_end: Optional[date] = None
    if start_date and end_date:
        try:
            custom_start = date.fromisoformat(start_date)
            custom_end = date.fromisoformat(end_date)
        except ValueError:
            pass

    # Get all dashboard data in parallel
    kpi_summary = await service.get_kpi_summary()

    # If custom range requested, add a 'custom' KPI bucket with real data
    if custom_start and custom_end:
        custom_kpis = await service.get_realtime_kpis(
            start_date=custom_start,
            end_date=custom_end
        )
        custom_days = (custom_end - custom_start).days or 1
        kpi_summary["custom"] = {
            **custom_kpis,
            "label": f"Custom {custom_days} Days"
        }

    # Extend forecast window to cover custom range if it's longer than 14 days
    forecast_days = 14
    if custom_start and custom_end:
        custom_days = (custom_end - custom_start).days
        if custom_days > forecast_days:
            forecast_days = custom_days

    forecast = await service.get_demand_forecast(
        start_date=date.today(),
        end_date=date.today() + timedelta(days=forecast_days)
    )

    rec_days = 7
    if custom_start and custom_end:
        custom_days = (custom_end - custom_start).days
        if custom_days > rec_days:
            rec_days = custom_days

    recommendations = await service.get_pricing_recommendations(
        start_date=date.today(),
        end_date=date.today() + timedelta(days=rec_days)
    )

    opportunities = await service.get_revenue_opportunities(limit=5)
    alerts = await service.get_revenue_alerts()
    channels = await service.get_channel_analysis()

    # Calculate high impact days
    high_impact_days = [
        f for f in forecast
        if f.get("demand_level") in ["high", "critical"]
    ]
    # Normalize confidence to 0-1 for display (prevents 8876% accurate)
    forecast_for_client = _normalize_forecast_confidence_for_display(forecast[:forecast_days])

    return {
        "kpis": kpi_summary,
        "forecast": forecast_for_client,
        "high_impact_days": high_impact_days[:5],
        "recommendations": recommendations[:10],
        "opportunities": opportunities,
        "alerts": alerts,
        "channels": channels,
        "generated_at": datetime.now().isoformat()
    }


# ==================== PRICING RECOMMENDATION ACTIONS ====================

# Composite ID format from frontend: "{room_type_id}_{date}" e.g. "1_2026-02-14"
_COMPOSITE_REC_ID = re.compile(r"^(\d+)_(\d{4}-\d{2}-\d{2})$")


async def _resolve_recommendation_id(recommendation_id: str, session: AsyncSession) -> int:
    """
    Resolve recommendation_id to an integer index for the service.
    Accepts either a numeric string (e.g. "0", "1") or composite "{room_type_id}_{date}" (e.g. "1_2026-02-14").
    """
    if recommendation_id.isdigit():
        return int(recommendation_id)
    match = _COMPOSITE_REC_ID.match(recommendation_id.strip())
    if not match:
        raise ValueError(f"Invalid recommendation_id: expected integer or 'room_type_id_YYYY-MM-DD', got '{recommendation_id}'")
    room_type_id = int(match.group(1))
    date_str = match.group(2)
    target_date = date.fromisoformat(date_str)
    today = date.today()
    # Search a range that covers both past and future recommendations
    range_start = min(today, target_date)
    range_end = max(today + timedelta(days=30), target_date + timedelta(days=1))
    service = RevenueIntelligenceService(session)
    recommendations = await service.get_pricing_recommendations(range_start, range_end)
    for idx, rec in enumerate(recommendations):
        if rec.get("room_type_id") == room_type_id and rec.get("date") == date_str:
            return idx
    raise ValueError(f"Recommendation not found for room_type_id={room_type_id}, date={date_str}")


@router.post("/pricing/recommendations/{recommendation_id}/accept", response_model=RecommendationAcceptResponse, tags=["Revenue Intelligence"])
async def accept_pricing_recommendation(
    recommendation_id: str = Path(..., description="ID of the recommendation to accept (integer index or 'room_type_id_YYYY-MM-DD')"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Accept a pricing recommendation and apply the suggested rate.

    This will:
    - Update the actual rate in the system
    - Create an audit trail entry
    - Mark the recommendation as accepted
    """
    service = RevenueIntelligenceService(session)
    try:
        match = _COMPOSITE_REC_ID.match(recommendation_id.strip())
        if match:
            # Composite ID: pass room_type_id and date directly to service
            result = await service.accept_pricing_recommendation(
                room_type_id=int(match.group(1)),
                rec_date=match.group(2)
            )
        else:
            # Legacy numeric index
            result = await service.accept_pricing_recommendation(
                recommendation_id=int(recommendation_id)
            )
        return RecommendationAcceptResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to accept recommendation: {str(e)}")


@router.post("/pricing/recommendations/{recommendation_id}/dismiss", response_model=RecommendationDismissResponse, tags=["Revenue Intelligence"])
async def dismiss_pricing_recommendation(
    recommendation_id: str = Path(..., description="ID of the recommendation to dismiss (integer index or 'room_type_id_YYYY-MM-DD')"),
    reason: Optional[str] = Body(None, embed=True, description="Reason for dismissing"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Dismiss a pricing recommendation without applying it."""
    service = RevenueIntelligenceService(session)
    try:
        match = _COMPOSITE_REC_ID.match(recommendation_id.strip())
        resolved_id = int(match.group(1)) if match else int(recommendation_id)
        result = await service.dismiss_pricing_recommendation(resolved_id, reason)
        return RecommendationDismissResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/pricing/recommendations/apply-all", response_model=BulkApplyResponse, tags=["Revenue Intelligence"])
async def apply_all_recommendations(
    start_date: Optional[date] = Query(None, description="Filter by start date"),
    end_date: Optional[date] = Query(None, description="Filter by end date"),
    min_confidence: float = Query(80.0, description="Minimum confidence threshold"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Apply all pending pricing recommendations that meet the confidence threshold.

    This is useful for bulk-accepting high-confidence recommendations.
    """
    service = RevenueIntelligenceService(session)
    result = await service.apply_all_recommendations(start_date, end_date, min_confidence)
    return BulkApplyResponse(**result)


@router.post("/pricing/recommendations/dismiss-all", response_model=BulkDismissResponse, tags=["Revenue Intelligence"])
async def dismiss_all_recommendations(
    start_date: Optional[date] = Query(None, description="Filter by start date"),
    end_date: Optional[date] = Query(None, description="Filter by end date"),
    reason: Optional[str] = Body(None, embed=True, description="Reason for dismissing all"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Dismiss all pending pricing recommendations for the specified period."""
    service = RevenueIntelligenceService(session)
    result = await service.dismiss_all_recommendations(start_date, end_date, reason)
    return BulkDismissResponse(**result)


# ==================== RATE MANAGEMENT ====================

@router.put("/rates/{room_type_id}/{rate_date}", response_model=RateUpdateResponse, tags=["Revenue Intelligence"])
async def update_single_rate(
    room_type_id: int = Path(..., description="Room type ID"),
    rate_date: date = Path(..., description="Date for the rate"),
    request: RateUpdateRequest = Body(...),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Update the rate for a specific room type on a specific date.

    Validates that the rate is within configured min/max bounds and creates an audit trail.
    """
    service = RevenueIntelligenceService(session)
    try:
        result = await service.update_single_rate(
            room_type_id=room_type_id,
            rate_date=rate_date,
            new_rate=request.rate,
            reason=request.reason
        )
        return RateUpdateResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update rate: {str(e)}")


@router.put("/rates/bulk-update", response_model=BulkRateUpdateResponse, tags=["Revenue Intelligence"])
async def bulk_update_rates(
    request: BulkRateUpdateRequest = Body(...),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Update multiple rates in a single operation.

    Each update is validated independently. Partial success is possible.
    """
    service = RevenueIntelligenceService(session)
    result = await service.bulk_update_rates(request.updates, request.reason)
    return BulkRateUpdateResponse(**result)


@router.get("/rates/calendar", response_model=RateCalendarResponse, tags=["Revenue Intelligence"])
async def get_rate_calendar(
    start_date: Optional[date] = Query(None, description="Calendar start date"),
    end_date: Optional[date] = Query(None, description="Calendar end date"),
    room_type_id: Optional[int] = Query(None, description="Filter by room type"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Get rate calendar data showing rates, occupancy, and demand levels for each day.

    Useful for visualizing rate strategy and identifying optimization opportunities.
    """
    service = RevenueIntelligenceService(session)
    result = await service.get_rate_calendar(start_date, end_date, room_type_id)
    return RateCalendarResponse(**result)


# ==================== PRICING RULES CRUD ====================

@router.get("/pricing-rules", response_model=PricingRulesListResponse, tags=["Revenue Intelligence"])
async def list_pricing_rules(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    room_type_id: Optional[int] = Query(None, description="Filter by room type"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get all pricing rules with optional filtering."""
    service = RevenueIntelligenceService(session)
    result = await service.list_pricing_rules(is_active=is_active, room_type_id=room_type_id)
    return PricingRulesListResponse(**result)


@router.post("/pricing-rules", response_model=PricingRuleResponse, tags=["Revenue Intelligence"])
async def create_pricing_rule(
    request: Request,
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Create a new pricing rule. Accepts any body shape; extracts rule_name, conditions, actions (camelCase or snake_case).

    Rules have:
    - Conditions: demand_level, occupancy, day_of_week, lead_time
    - Actions: adjust_percent, set_rate, multiply_by
    - Priority: 1-5, where 1 is highest priority
    """
    try:
        # Parse JSON body manually to completely bypass Pydantic validation (avoid 422)
        try:
            payload = await request.json()
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid JSON body: {str(e)}")
        
        if not isinstance(payload, dict):
            payload = {}
        
        # Parse body leniently to avoid 422 from Pydantic (frontend may send different shapes)
        p = _parse_pricing_rule_body(payload)

        # Validate required fields (return 400, not 422)
        if not (p["rule_name"] or "").strip():
            raise HTTPException(status_code=400, detail="Missing required field: rule_name (or ruleName)")
        if not p.get("conditions") or not isinstance(p["conditions"], list) or len(p["conditions"]) == 0:
            raise HTTPException(status_code=400, detail="Missing required field: conditions (must be a non-empty array)")
        if not p.get("actions") or not isinstance(p["actions"], list) or len(p["actions"]) == 0:
            raise HTTPException(status_code=400, detail="Missing required field: actions (must be a non-empty array)")

        # Validate priority range
        priority = p.get("priority", 3)
        if not isinstance(priority, int) or priority < 1 or priority > 5:
            priority = 3

        # Build the rule data dict
        rule_data = {
            "rule_name": (p["rule_name"] or "").strip(),
            "description": p.get("description") or None,
            "room_type_id": p.get("room_type_id") if p.get("room_type_id") else None,
            "priority": priority,
            "conditions": p["conditions"],
            "actions": p["actions"],
            "is_active": p.get("is_active", True),
            "valid_from": p.get("valid_from"),
            "valid_to": p.get("valid_to"),
        }

        service = RevenueIntelligenceService(session)
        result = await service.create_pricing_rule(rule_data)
        return PricingRuleResponse(**result)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create pricing rule: {str(e)}")


@router.get("/pricing-rules/{rule_id}", response_model=PricingRuleResponse, tags=["Revenue Intelligence"])
async def get_pricing_rule(
    rule_id: int = Path(..., description="Pricing rule ID"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get a single pricing rule by ID."""
    service = RevenueIntelligenceService(session)
    result = await service.get_pricing_rule(rule_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Pricing rule {rule_id} not found")
    return PricingRuleResponse(**result)


@router.put("/pricing-rules/{rule_id}", response_model=PricingRuleResponse, tags=["Revenue Intelligence"])
async def update_pricing_rule(
    rule_id: int = Path(..., description="Pricing rule ID"),
    rule: PricingRuleUpdate = Body(...),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Update an existing pricing rule."""
    service = RevenueIntelligenceService(session)
    try:
        result = await service.update_pricing_rule(rule_id, rule.model_dump(exclude_unset=True))
        if not result:
            raise HTTPException(status_code=404, detail=f"Pricing rule {rule_id} not found")
        return PricingRuleResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/pricing-rules/{rule_id}", tags=["Revenue Intelligence"])
async def delete_pricing_rule(
    rule_id: int = Path(..., description="Pricing rule ID"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Delete a pricing rule."""
    service = RevenueIntelligenceService(session)
    result = await service.delete_pricing_rule(rule_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Pricing rule {rule_id} not found")
    return {
        "success": True,
        "rule_id": result["rule_id"],
        "rule_name": result["rule_name"],
        "message": f"Pricing rule {result['rule_id']} deleted successfully"
    }


async def _toggle_pricing_rule_handler(
    rule_id: int = Path(..., description="Pricing rule ID"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Toggle the active status of a pricing rule."""
    try:
        service = RevenueIntelligenceService(session)
        result = await service.toggle_pricing_rule(rule_id)
        if not result:
            raise HTTPException(status_code=404, detail=f"Pricing rule {rule_id} not found")
        # Validate response structure
        if not isinstance(result, dict):
            raise HTTPException(status_code=500, detail="Invalid response format from service")
        if "success" not in result or "rule_id" not in result or "is_active" not in result:
            raise HTTPException(status_code=500, detail="Incomplete response from service")
        return RuleToggleResponse(**result)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to toggle pricing rule: {str(e)}"
        )


@router.post("/pricing-rules/{rule_id}/toggle", response_model=RuleToggleResponse, tags=["Revenue Intelligence"])
async def toggle_pricing_rule_post(
    rule_id: int = Path(..., description="Pricing rule ID"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Toggle the active status of a pricing rule (POST)."""
    return await _toggle_pricing_rule_handler(rule_id, session)


@router.patch("/pricing-rules/{rule_id}/toggle", response_model=RuleToggleResponse, tags=["Revenue Intelligence"])
async def toggle_pricing_rule_patch(
    rule_id: int = Path(..., description="Pricing rule ID"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Toggle the active status of a pricing rule (PATCH)."""
    return await _toggle_pricing_rule_handler(rule_id, session)


@router.post("/pricing-rules/execute", response_model=RuleExecutionResponse, tags=["Revenue Intelligence"])
async def execute_pricing_rules(
    start_date: Optional[date] = Query(None, description="Start date for rule execution"),
    end_date: Optional[date] = Query(None, description="End date for rule execution"),
    dry_run: bool = Query(False, description="Preview changes without applying"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Execute all active pricing rules against current inventory.

    Rules are executed in priority order (1 = highest).
    Use dry_run=true to preview changes without applying them.
    """
    service = RevenueIntelligenceService(session)
    result = await service.execute_pricing_rules(start_date, end_date, dry_run)
    return RuleExecutionResponse(**result)


# ==================== AUTO-PRICING SETTINGS ====================

@router.get("/settings/auto-pricing", response_model=AutoPricingConfigResponse, tags=["Revenue Intelligence"])
async def get_auto_pricing_settings(
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get current auto-pricing configuration."""
    service = RevenueIntelligenceService(session)
    config = await service.get_auto_pricing_config()
    return AutoPricingConfigResponse(
        success=True,
        config=AutoPricingConfig(**config),
        message="Auto-pricing configuration retrieved successfully"
    )


@router.post("/settings/auto-pricing", response_model=AutoPricingConfigResponse, tags=["Revenue Intelligence"])
async def update_auto_pricing_settings(
    request: AutoPricingUpdateRequest = Body(...),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Update auto-pricing configuration."""
    service = RevenueIntelligenceService(session)
    try:
        config = await service.update_auto_pricing_config(request.model_dump(exclude_unset=True))
        return AutoPricingConfigResponse(
            success=True,
            config=AutoPricingConfig(**config),
            message="Auto-pricing configuration updated successfully"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/settings/auto-pricing/toggle", response_model=AutoPricingToggleResponse, tags=["Revenue Intelligence"])
async def toggle_auto_pricing(
    enabled: Optional[bool] = Body(None, embed=True, description="Enable or disable. If not provided, toggles current state"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Toggle auto-pricing on or off."""
    service = RevenueIntelligenceService(session)
    result = await service.toggle_auto_pricing(enabled)
    return AutoPricingToggleResponse(**result)


# ==================== COMPETITOR MANAGEMENT ====================

@router.get("/competitors", response_model=CompetitorsListResponse, tags=["Revenue Intelligence"])
async def list_competitors(
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """List all tracked competitors."""
    service = RevenueIntelligenceService(session)
    result = await service.list_competitors(is_active)
    return CompetitorsListResponse(**result)


@router.post("/competitors", response_model=CompetitorResponse, tags=["Revenue Intelligence"])
async def add_competitor(
    competitor: CompetitorCreate = Body(...),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Add a new competitor to track."""
    service = RevenueIntelligenceService(session)
    try:
        result = await service.add_competitor(competitor.model_dump())
        return CompetitorResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/competitors/{competitor_id}", response_model=CompetitorDeleteResponse, tags=["Revenue Intelligence"])
async def remove_competitor(
    competitor_id: int = Path(..., description="Competitor ID to remove"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Remove a competitor from tracking."""
    service = RevenueIntelligenceService(session)
    result = await service.remove_competitor(competitor_id)
    if not result["success"]:
        raise HTTPException(status_code=404, detail=f"Competitor {competitor_id} not found")
    return CompetitorDeleteResponse(**result)


@router.put("/competitors/{competitor_id}", response_model=CompetitorResponse, tags=["Revenue Intelligence"])
async def update_competitor(
    competitor_id: int = Path(..., description="Competitor ID to update"),
    payload: CompetitorUpdate = Body(...),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Update an existing competitor."""
    service = RevenueIntelligenceService(session)
    try:
        data = {k: v for k, v in payload.model_dump().items() if v is not None}
        result = await service.update_competitor(competitor_id, data)
        return CompetitorResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/competitors/refresh", response_model=CompetitorRefreshResponse, tags=["Revenue Intelligence"])
async def refresh_competitor_rates(
    competitor_ids: Optional[List[int]] = Body(None, embed=True, description="Specific competitor IDs to refresh, or all if empty"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Trigger a competitor rate scrape/refresh.

    This initiates a background job to fetch the latest rates from competitor data sources.
    """
    service = RevenueIntelligenceService(session)
    result = await service.refresh_competitor_rates(competitor_ids)
    return CompetitorRefreshResponse(**result)


@router.get("/competitors/{competitor_id}/rates", response_model=CompetitorRatesResponse, tags=["Revenue Intelligence"])
async def get_competitor_rate_history(
    competitor_id: int = Path(..., description="Competitor ID"),
    start_date: Optional[date] = Query(None, description="Start date for rate history"),
    end_date: Optional[date] = Query(None, description="End date for rate history"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get historical rate data for a specific competitor."""
    service = RevenueIntelligenceService(session)
    result = await service.get_competitor_rate_history(competitor_id, start_date, end_date)
    if not result:
        raise HTTPException(status_code=404, detail=f"Competitor {competitor_id} not found")
    return CompetitorRatesResponse(**result)


# ==================== AI INSIGHTS ====================

@router.get("/ai/insights", response_model=AIInsightsResponse, tags=["Revenue Intelligence"])
async def get_ai_insights(
    severity: Optional[str] = Query(None, description="Filter by severity: info, warning, critical"),
    unread_only: bool = Query(False, description="Only return unread insights"),
    limit: int = Query(20, description="Maximum number of insights to return"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Get AI-generated insights for revenue optimization.

    Insights are automatically generated based on:
    - Demand patterns and forecasts
    - Pricing opportunities
    - Competitor movements
    - Market trends
    """
    service = RevenueIntelligenceService(session)
    result = await service.get_ai_insights(severity, unread_only, limit)
    return AIInsightsResponse(**result)


@router.post("/ai/insights/{insight_id}/dismiss", response_model=InsightActionResponse, tags=["Revenue Intelligence"])
async def dismiss_ai_insight(
    insight_id: str = Path(..., description="Insight ID to dismiss"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Dismiss an AI insight so it no longer appears in the feed."""
    service = RevenueIntelligenceService(session)
    result = await service.dismiss_ai_insight(insight_id)
    return InsightActionResponse(**result)


@router.post("/ai/insights/{insight_id}/read", response_model=InsightActionResponse, tags=["Revenue Intelligence"])
async def mark_insight_read(
    insight_id: str = Path(..., description="Insight ID to mark as read"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Mark an AI insight as read."""
    service = RevenueIntelligenceService(session)
    result = await service.mark_insight_read(insight_id)
    return InsightActionResponse(**result)


# ==================== SEGMENTS ====================

@router.get("/segments/performance", response_model=SegmentPerformanceResponse, tags=["Revenue Intelligence"])
async def get_segment_performance(
    start_date: Optional[date] = Query(None, description="Analysis start date"),
    end_date: Optional[date] = Query(None, description="Analysis end date"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Get revenue performance breakdown by market segment.

    Analyzes performance across segments like:
    - Leisure
    - Business
    - Group
    - Corporate
    - OTA
    """
    service = RevenueIntelligenceService(session)
    result = await service.get_segment_performance(start_date, end_date)
    return SegmentPerformanceResponse(**result)


# ==================== EVENTS ====================

@router.get("/events", response_model=EventsListResponse, tags=["Revenue Intelligence"])
async def list_events(
    start_date: Optional[date] = Query(None, description="Filter events starting from this date"),
    end_date: Optional[date] = Query(None, description="Filter events ending before this date"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """List all market events that may impact demand."""
    service = RevenueIntelligenceService(session)
    result = await service.list_events(start_date, end_date, event_type)
    return EventsListResponse(**result)


@router.post("/events", response_model=EventResponse, tags=["Revenue Intelligence"])
async def create_event(
    event: EventCreate = Body(...),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Create a new market event.

    Events are used to forecast demand spikes and optimize pricing accordingly.
    """
    service = RevenueIntelligenceService(session)
    try:
        result = await service.create_event(event.model_dump())
        return EventResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/events/{event_id}", tags=["Revenue Intelligence"])
async def delete_event(
    event_id: int,
    session: AsyncSession = Depends(get_tenant_session)
):
    """Delete a market event by ID."""
    service = RevenueIntelligenceService(session)
    try:
        await service.delete_event(event_id)
        return {"message": "Event deleted successfully", "id": event_id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/events/{event_id}", response_model=EventResponse, tags=["Revenue Intelligence"])
async def update_event(
    event_id: int = Path(..., description="Event ID to update"),
    payload: EventUpdate = Body(...),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Update an existing market event."""
    service = RevenueIntelligenceService(session)
    try:
        data = {k: v for k, v in payload.model_dump().items() if v is not None}
        result = await service.update_event(event_id, data)
        return EventResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/events/calendar", response_model=EventCalendarResponse, tags=["Revenue Intelligence"])
async def get_event_calendar(
    start_date: Optional[date] = Query(None, description="Calendar start date"),
    end_date: Optional[date] = Query(None, description="Calendar end date"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Get event calendar view showing events mapped to dates.

    Useful for visualizing demand impact periods.
    """
    service = RevenueIntelligenceService(session)
    result = await service.get_event_calendar(start_date, end_date)
    return EventCalendarResponse(**result)


@router.get("/events/impact", response_model=EventImpactResponse, tags=["Revenue Intelligence"])
async def get_event_demand_impact(
    start_date: Optional[date] = Query(None, description="Analysis start date"),
    end_date: Optional[date] = Query(None, description="Analysis end date"),
    session: AsyncSession = Depends(get_tenant_session)
):
    """
    Get demand impact analysis for upcoming events.

    Shows estimated revenue opportunity and recommended rate adjustments for each event.
    """
    service = RevenueIntelligenceService(session)
    result = await service.get_event_demand_impact(start_date, end_date)
    return EventImpactResponse(**result)
