"""
Channel Manager Schemas
Pydantic schemas for OTAConnection, OTARoomMapping, OTARateMapping, RateOverride, ChannelRestriction, AvailabilityGrid, SyncLog
"""
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============== OTA CONNECTION SCHEMAS ==============

class OTAConnectionBase(BaseModel):
    """Base schema for OTA connections"""
    ota_code: str  # BOOKING, EXPEDIA, AGODA, AIRBNB, etc.
    ota_name: str
    logo_url: Optional[str] = None
    brand_color: Optional[str] = None
    api_username: Optional[str] = None
    api_key_encrypted: Optional[str] = None
    hotel_id_on_ota: Optional[str] = None
    auto_sync_enabled: bool = True
    sync_interval_minutes: int = 15
    sync_rates: bool = True
    sync_availability: bool = True
    sync_restrictions: bool = True
    commission_rate: Optional[float] = None
    is_active: bool = True


class OTAConnectionCreate(OTAConnectionBase):
    """Schema for creating an OTA connection"""
    property_id: int


class OTAConnectionUpdate(BaseModel):
    """Schema for updating an OTA connection - all fields optional"""
    ota_name: Optional[str] = None
    logo_url: Optional[str] = None
    brand_color: Optional[str] = None
    connection_status: Optional[str] = None
    api_username: Optional[str] = None
    api_key_encrypted: Optional[str] = None
    hotel_id_on_ota: Optional[str] = None
    auto_sync_enabled: Optional[bool] = None
    sync_interval_minutes: Optional[int] = None
    sync_rates: Optional[bool] = None
    sync_availability: Optional[bool] = None
    sync_restrictions: Optional[bool] = None
    commission_rate: Optional[float] = None
    is_active: Optional[bool] = None
    error_message: Optional[str] = None


class OTAConnectionResponse(OTAConnectionBase):
    """Schema for OTA connection API responses"""
    id: int
    property_id: int
    connection_status: str = "disconnected"
    last_sync_at: Optional[datetime] = None
    next_sync_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============== OTA ROOM MAPPING SCHEMAS ==============

class OTARoomMappingBase(BaseModel):
    """Base schema for OTA room mappings"""
    ota_connection_id: int
    room_type_id: int
    ota_room_code: str
    ota_room_name: Optional[str] = None
    is_active: bool = True


class OTARoomMappingCreate(OTARoomMappingBase):
    """Schema for creating an OTA room mapping"""
    property_id: int


class OTARoomMappingUpdate(BaseModel):
    """Schema for updating an OTA room mapping - all fields optional"""
    ota_room_code: Optional[str] = None
    ota_room_name: Optional[str] = None
    is_active: Optional[bool] = None
    sync_status: Optional[str] = None


class OTARoomMappingResponse(OTARoomMappingBase):
    """Schema for OTA room mapping API responses"""
    id: int
    property_id: int
    sync_status: str = "pending"
    last_synced_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============== OTA RATE MAPPING SCHEMAS ==============

class OTARateMappingBase(BaseModel):
    """Base schema for OTA rate mappings"""
    ota_connection_id: int
    rate_plan_id: int
    ota_rate_code: str
    ota_rate_name: Optional[str] = None
    markup_percentage: float = 0.0
    is_active: bool = True


class OTARateMappingCreate(OTARateMappingBase):
    """Schema for creating an OTA rate mapping"""
    property_id: int


class OTARateMappingUpdate(BaseModel):
    """Schema for updating an OTA rate mapping - all fields optional"""
    ota_rate_code: Optional[str] = None
    ota_rate_name: Optional[str] = None
    markup_percentage: Optional[float] = None
    is_active: Optional[bool] = None


class OTARateMappingResponse(OTARateMappingBase):
    """Schema for OTA rate mapping API responses"""
    id: int
    property_id: int
    last_synced_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============== RATE OVERRIDE SCHEMAS ==============

class RateOverrideBase(BaseModel):
    """Base schema for rate overrides"""
    ota_connection_id: int
    room_type_id: int
    start_date: date
    end_date: date
    adjustment_type: str = "percentage"  # percentage, fixed
    adjustment_value: float
    reason: Optional[str] = None
    is_active: bool = True


class RateOverrideCreate(RateOverrideBase):
    """Schema for creating a rate override"""
    property_id: int
    created_by: Optional[int] = None


class RateOverrideUpdate(BaseModel):
    """Schema for updating a rate override - all fields optional"""
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    adjustment_type: Optional[str] = None
    adjustment_value: Optional[float] = None
    reason: Optional[str] = None
    is_active: Optional[bool] = None


class RateOverrideResponse(RateOverrideBase):
    """Schema for rate override API responses"""
    id: int
    property_id: int
    created_by: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


# ============== CHANNEL RESTRICTION SCHEMAS ==============

class ChannelRestrictionBase(BaseModel):
    """Base schema for channel restrictions"""
    ota_connection_id: Optional[int] = None
    room_type_id: Optional[int] = None
    restriction_date: date
    restriction_type: str  # CTA, CTD, stop_sell, min_stay, max_stay
    restriction_value: int
    reason: Optional[str] = None
    is_active: bool = True


class ChannelRestrictionCreate(ChannelRestrictionBase):
    """Schema for creating a channel restriction"""
    property_id: int
    created_by: Optional[int] = None


class ChannelRestrictionUpdate(BaseModel):
    """Schema for updating a channel restriction - all fields optional"""
    restriction_date: Optional[date] = None
    restriction_type: Optional[str] = None
    restriction_value: Optional[int] = None
    reason: Optional[str] = None
    is_active: Optional[bool] = None


class ChannelRestrictionResponse(ChannelRestrictionBase):
    """Schema for channel restriction API responses"""
    id: int
    property_id: int
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ============== AVAILABILITY GRID SCHEMAS ==============

class AvailabilityGridBase(BaseModel):
    """Base schema for availability grid"""
    room_type_id: int
    grid_date: date
    total_inventory: int = 0
    sold: int = 0
    blocked: int = 0
    available: int = 0
    rate_amount: Optional[float] = None
    min_rate: Optional[float] = None
    max_rate: Optional[float] = None
    cta_flag: bool = False
    ctd_flag: bool = False
    stop_sell_flag: bool = False
    min_stay: Optional[int] = None
    max_stay: Optional[int] = None


class AvailabilityGridCreate(AvailabilityGridBase):
    """Schema for creating an availability grid entry"""
    property_id: int


class AvailabilityGridUpdate(BaseModel):
    """Schema for updating an availability grid entry - all fields optional"""
    total_inventory: Optional[int] = None
    sold: Optional[int] = None
    blocked: Optional[int] = None
    available: Optional[int] = None
    rate_amount: Optional[float] = None
    min_rate: Optional[float] = None
    max_rate: Optional[float] = None
    cta_flag: Optional[bool] = None
    ctd_flag: Optional[bool] = None
    stop_sell_flag: Optional[bool] = None
    min_stay: Optional[int] = None
    max_stay: Optional[int] = None


class AvailabilityGridResponse(AvailabilityGridBase):
    """Schema for availability grid API responses"""
    id: int
    property_id: int
    updated_at: datetime

    class Config:
        from_attributes = True


# ============== SYNC LOG SCHEMAS ==============

class SyncLogBase(BaseModel):
    """Base schema for sync logs"""
    ota_connection_id: int
    sync_type: str  # rates, availability, bookings, restrictions, full
    sync_direction: str  # push, pull
    status: str  # success, failed, partial
    records_processed: int = 0
    records_failed: int = 0
    error_details: Optional[Dict[str, Any]] = None


class SyncLogCreate(SyncLogBase):
    """Schema for creating a sync log"""
    property_id: int


class SyncLogResponse(SyncLogBase):
    """Schema for sync log API responses"""
    id: int
    property_id: int
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    class Config:
        from_attributes = True


# ============== LIST RESPONSE SCHEMAS ==============

class OTAConnectionListResponse(BaseModel):
    """Paginated OTA connection list response"""
    items: List[OTAConnectionResponse]
    total: int
    page: int
    page_size: int


class AvailabilityGridListResponse(BaseModel):
    """Paginated availability grid list response"""
    items: List[AvailabilityGridResponse]
    total: int
    page: int
    page_size: int


class SyncLogListResponse(BaseModel):
    """Paginated sync log list response"""
    items: List[SyncLogResponse]
    total: int
    page: int
    page_size: int


# ============== BULK OPERATION SCHEMAS ==============

class BulkAvailabilityUpdate(BaseModel):
    """Schema for bulk availability updates"""
    room_type_id: int
    start_date: date
    end_date: date
    available: Optional[int] = None
    rate_amount: Optional[float] = None
    cta_flag: Optional[bool] = None
    ctd_flag: Optional[bool] = None
    stop_sell_flag: Optional[bool] = None
    min_stay: Optional[int] = None
    max_stay: Optional[int] = None


class BulkRestrictionUpdate(BaseModel):
    """Schema for bulk restriction updates"""
    ota_connection_id: Optional[int] = None
    room_type_id: Optional[int] = None
    start_date: date
    end_date: date
    restriction_type: str
    restriction_value: int
    reason: Optional[str] = None
