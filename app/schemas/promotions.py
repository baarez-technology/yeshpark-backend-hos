"""
Promotions & Discount Management Schemas
Pydantic schemas for Promotion, PromotionApplicability, PromotionUsage, PromotionBlackoutDate, PromotionAnalytics
"""
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============== PROMOTION SCHEMAS ==============

class PromotionBase(BaseModel):
    """Base schema for promotions"""
    promotion_code: Optional[str] = None
    title: str
    description: Optional[str] = None
    discount_type: str  # percentage, fixed, free_night, upgrade, addon
    discount_value: float
    is_active: bool = True
    valid_from: date
    valid_to: date
    min_nights: Optional[int] = None
    max_nights: Optional[int] = None
    min_booking_amount: Optional[float] = None
    max_discount_amount: Optional[float] = None
    usage_limit: Optional[int] = None
    is_stackable: bool = False
    priority: int = 0
    terms_and_conditions: Optional[str] = None


class PromotionCreate(PromotionBase):
    """Schema for creating a promotion"""
    property_id: int
    created_by: Optional[int] = None


class PromotionUpdate(BaseModel):
    """Schema for updating a promotion - all fields optional"""
    promotion_code: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None
    is_active: Optional[bool] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    min_nights: Optional[int] = None
    max_nights: Optional[int] = None
    min_booking_amount: Optional[float] = None
    max_discount_amount: Optional[float] = None
    usage_limit: Optional[int] = None
    is_stackable: Optional[bool] = None
    priority: Optional[int] = None
    terms_and_conditions: Optional[str] = None


class PromotionResponse(PromotionBase):
    """Schema for promotion API responses"""
    id: int
    property_id: int
    usage_count: int = 0
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============== PROMOTION APPLICABILITY SCHEMAS ==============

class PromotionApplicabilityBase(BaseModel):
    """Base schema for promotion applicability"""
    promotion_id: int
    entity_type: str  # room_type, rate_plan, channel, segment
    entity_id: int
    entity_name: Optional[str] = None
    is_included: bool = True  # True = whitelist, False = blacklist


class PromotionApplicabilityCreate(PromotionApplicabilityBase):
    """Schema for creating a promotion applicability rule"""
    property_id: int


class PromotionApplicabilityUpdate(BaseModel):
    """Schema for updating a promotion applicability rule - all fields optional"""
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    entity_name: Optional[str] = None
    is_included: Optional[bool] = None


class PromotionApplicabilityResponse(PromotionApplicabilityBase):
    """Schema for promotion applicability API responses"""
    id: int
    property_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============== PROMOTION USAGE SCHEMAS ==============

class PromotionUsageBase(BaseModel):
    """Base schema for promotion usage"""
    promotion_id: int
    booking_id: int
    guest_id: Optional[int] = None
    discount_amount: float
    original_amount: float
    final_amount: float


class PromotionUsageCreate(PromotionUsageBase):
    """Schema for creating a promotion usage record"""
    property_id: int


class PromotionUsageResponse(PromotionUsageBase):
    """Schema for promotion usage API responses"""
    id: int
    property_id: int
    applied_at: datetime

    class Config:
        from_attributes = True


# ============== PROMOTION BLACKOUT DATE SCHEMAS ==============

class PromotionBlackoutDateBase(BaseModel):
    """Base schema for promotion blackout dates"""
    promotion_id: int
    blackout_start: date
    blackout_end: date
    reason: Optional[str] = None


class PromotionBlackoutDateCreate(PromotionBlackoutDateBase):
    """Schema for creating a promotion blackout date"""
    property_id: int


class PromotionBlackoutDateUpdate(BaseModel):
    """Schema for updating a promotion blackout date - all fields optional"""
    blackout_start: Optional[date] = None
    blackout_end: Optional[date] = None
    reason: Optional[str] = None


class PromotionBlackoutDateResponse(PromotionBlackoutDateBase):
    """Schema for promotion blackout date API responses"""
    id: int
    property_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============== PROMOTION ANALYTICS SCHEMAS ==============

class PromotionAnalyticsBase(BaseModel):
    """Base schema for promotion analytics"""
    promotion_id: int
    analytics_date: date
    redemptions: int = 0
    revenue_generated: float = 0.0
    incremental_revenue: Optional[float] = None
    adr_uplift_pct: Optional[float] = None
    occupancy_impact_pct: Optional[float] = None
    channel_breakdown: Optional[Dict[str, Any]] = None
    room_type_breakdown: Optional[Dict[str, Any]] = None


class PromotionAnalyticsCreate(PromotionAnalyticsBase):
    """Schema for creating a promotion analytics record"""
    property_id: int


class PromotionAnalyticsUpdate(BaseModel):
    """Schema for updating a promotion analytics record - all fields optional"""
    redemptions: Optional[int] = None
    revenue_generated: Optional[float] = None
    incremental_revenue: Optional[float] = None
    adr_uplift_pct: Optional[float] = None
    occupancy_impact_pct: Optional[float] = None
    channel_breakdown: Optional[Dict[str, Any]] = None
    room_type_breakdown: Optional[Dict[str, Any]] = None


class PromotionAnalyticsResponse(PromotionAnalyticsBase):
    """Schema for promotion analytics API responses"""
    id: int
    property_id: int
    created_at: datetime

    class Config:
        from_attributes = True


# ============== LIST RESPONSE SCHEMAS ==============

class PromotionListResponse(BaseModel):
    """Paginated promotion list response"""
    items: List[PromotionResponse]
    total: int
    page: int
    page_size: int


class PromotionUsageListResponse(BaseModel):
    """Paginated promotion usage list response"""
    items: List[PromotionUsageResponse]
    total: int
    page: int
    page_size: int


class PromotionAnalyticsListResponse(BaseModel):
    """Paginated promotion analytics list response"""
    items: List[PromotionAnalyticsResponse]
    total: int
    page: int
    page_size: int


# ============== VALIDATION SCHEMAS ==============

class PromotionValidateRequest(BaseModel):
    """Schema for validating a promotion code"""
    promotion_code: str
    booking_amount: float
    arrival_date: date
    departure_date: date
    room_type_id: Optional[int] = None
    rate_plan_id: Optional[int] = None
    channel: Optional[str] = None


class PromotionValidateResponse(BaseModel):
    """Schema for promotion validation response"""
    valid: bool
    promotion_id: Optional[int] = None
    promotion_code: Optional[str] = None
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None
    calculated_discount: Optional[float] = None
    final_amount: Optional[float] = None
    message: str
    errors: Optional[List[str]] = None


# ============== SUMMARY SCHEMAS ==============

class PromotionSummary(BaseModel):
    """Summary of a promotion's performance"""
    promotion_id: int
    promotion_code: Optional[str] = None
    title: str
    total_redemptions: int
    total_revenue: float
    total_discount_given: float
    avg_discount_per_booking: float
    is_active: bool
    days_remaining: Optional[int] = None


class PromotionDashboardStats(BaseModel):
    """Dashboard statistics for promotions"""
    active_promotions: int
    total_redemptions_today: int
    total_redemptions_month: int
    revenue_from_promotions: float
    top_performing_promotions: List[PromotionSummary]
