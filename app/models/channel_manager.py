"""
Channel Manager Models
OTA integrations, room/rate mappings, availability grid, restrictions, and sync logging
"""
from datetime import datetime
from datetime import date as date_type
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON, UniqueConstraint


class OTAConnection(SQLModel, table=True):
    """OTA integration configuration for channel management"""
    __tablename__ = "ota_connections"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(index=True, nullable=False)  # Multi-tenant support

    # OTA identification
    ota_code: str = Field(index=True, nullable=False)  # BOOKING, EXPEDIA, AGODA, AIRBNB, etc.
    ota_name: str = Field(nullable=False)
    logo_url: Optional[str] = None
    brand_color: Optional[str] = None  # Hex color code for UI display

    # Connection status
    connection_status: str = Field(default="disconnected", index=True)  # connected, disconnected, error, syncing
    last_sync_at: Optional[datetime] = None
    next_sync_at: Optional[datetime] = Field(default=None, index=True)
    error_message: Optional[str] = None

    # API credentials (encrypted storage)
    api_username: Optional[str] = None
    api_key_encrypted: Optional[str] = None
    hotel_id_on_ota: Optional[str] = None  # Property ID on the OTA platform

    # Sync configuration
    auto_sync_enabled: bool = Field(default=True, index=True)
    sync_interval_minutes: int = Field(default=15)
    sync_rates: bool = Field(default=True)
    sync_availability: bool = Field(default=True)
    sync_restrictions: bool = Field(default=True)

    # Commercial terms
    commission_rate: Optional[float] = None  # Percentage commission for this OTA

    # Status
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OTARoomMapping(SQLModel, table=True):
    """Map local room types to OTA room types"""
    __tablename__ = "ota_room_mappings"
    __table_args__ = (
        UniqueConstraint("ota_connection_id", "room_type_id", name="uq_ota_room_mapping"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(index=True, nullable=False)  # Multi-tenant support
    ota_connection_id: int = Field(foreign_key="ota_connections.id", index=True, nullable=False)
    room_type_id: int = Field(foreign_key="room_types.id", index=True, nullable=False)

    # OTA room mapping
    ota_room_code: str = Field(nullable=False)  # Room code on OTA platform
    ota_room_name: Optional[str] = None  # Room name on OTA platform

    # Sync status
    is_active: bool = Field(default=True, index=True)
    sync_status: str = Field(default="pending", index=True)  # synced, pending, error
    last_synced_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


class OTARateMapping(SQLModel, table=True):
    """Map local rate plans to OTA rate plans"""
    __tablename__ = "ota_rate_mappings"
    __table_args__ = (
        UniqueConstraint("ota_connection_id", "rate_plan_id", name="uq_ota_rate_mapping"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(index=True, nullable=False)  # Multi-tenant support
    ota_connection_id: int = Field(foreign_key="ota_connections.id", index=True, nullable=False)
    rate_plan_id: int = Field(foreign_key="rateplan.id", index=True, nullable=False)

    # OTA rate mapping
    ota_rate_code: str = Field(nullable=False)  # Rate code on OTA platform
    ota_rate_name: Optional[str] = None  # Rate name on OTA platform

    # Rate adjustment
    markup_percentage: float = Field(default=0.0)  # Percentage markup/markdown for this OTA

    # Status
    is_active: bool = Field(default=True, index=True)
    last_synced_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


class RateOverride(SQLModel, table=True):
    """OTA-specific rate adjustments for specific date ranges"""
    __tablename__ = "rate_overrides"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(index=True, nullable=False)  # Multi-tenant support
    ota_connection_id: int = Field(foreign_key="ota_connections.id", index=True, nullable=False)
    room_type_id: int = Field(foreign_key="room_types.id", index=True, nullable=False)

    # Date range
    start_date: date_type = Field(index=True, nullable=False)
    end_date: date_type = Field(index=True, nullable=False)

    # Adjustment
    adjustment_type: str = Field(default="percentage")  # percentage, fixed
    adjustment_value: float = Field(nullable=False)  # Positive for increase, negative for decrease

    # Metadata
    reason: Optional[str] = None
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")

    # Status
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ChannelRestriction(SQLModel, table=True):
    """Channel-wide or room-specific restrictions (CTA, CTD, Stop Sell, Min/Max Stay)"""
    __tablename__ = "channel_restrictions"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(index=True, nullable=False)  # Multi-tenant support

    # Optional FK - null means applies to all channels/rooms
    ota_connection_id: Optional[int] = Field(default=None, foreign_key="ota_connections.id", index=True)
    room_type_id: Optional[int] = Field(default=None, foreign_key="room_types.id", index=True)

    # Restriction details
    restriction_date: date_type = Field(index=True, nullable=False)
    restriction_type: str = Field(index=True, nullable=False)  # CTA, CTD, stop_sell, min_stay, max_stay
    restriction_value: int = Field(nullable=False)  # Integer: 1/0 for boolean types, nights for stay limits

    # Original date range from user input
    date_range_start: Optional[date_type] = Field(default=None)
    date_range_end: Optional[date_type] = Field(default=None)

    # Group ID to link all rows created from a single restriction
    group_id: Optional[str] = Field(default=None, index=True)

    # Metadata
    reason: Optional[str] = None
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    is_active: bool = Field(default=True, index=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AvailabilityGrid(SQLModel, table=True):
    """Daily availability tracking for room types"""
    __tablename__ = "availability_grid"
    __table_args__ = (
        UniqueConstraint("property_id", "room_type_id", "grid_date", name="uq_availability_grid_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(index=True, nullable=False)  # Multi-tenant support
    room_type_id: int = Field(foreign_key="room_types.id", index=True, nullable=False)
    grid_date: date_type = Field(index=True, nullable=False)

    # Inventory counts
    total_inventory: int = Field(default=0)  # Total rooms of this type
    sold: int = Field(default=0)  # Rooms sold/booked
    blocked: int = Field(default=0)  # Rooms blocked (maintenance, OOO, etc.)
    available: int = Field(default=0)  # Rooms available = total - sold - blocked

    # Rate information
    rate_amount: Optional[float] = None  # Current selling rate
    min_rate: Optional[float] = None  # Minimum allowed rate
    max_rate: Optional[float] = None  # Maximum allowed rate

    # Restriction flags
    cta_flag: bool = Field(default=False)  # Closed to Arrival
    ctd_flag: bool = Field(default=False)  # Closed to Departure
    stop_sell_flag: bool = Field(default=False)  # Stop Sell
    min_stay: Optional[int] = None  # Minimum length of stay
    max_stay: Optional[int] = None  # Maximum length of stay

    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SyncLog(SQLModel, table=True):
    """Channel sync activity log for auditing and debugging"""
    __tablename__ = "sync_logs"
    id: Optional[int] = Field(default=None, primary_key=True)
    property_id: int = Field(index=True, nullable=False)  # Multi-tenant support
    ota_connection_id: int = Field(foreign_key="ota_connections.id", index=True, nullable=False)

    # Sync details
    sync_type: str = Field(index=True, nullable=False)  # rates, availability, bookings, restrictions, full
    sync_direction: str = Field(index=True, nullable=False)  # push, pull
    status: str = Field(index=True, nullable=False)  # success, failed, partial

    # Processing stats
    records_processed: int = Field(default=0)
    records_failed: int = Field(default=0)

    # Error tracking (JSONB for detailed error info)
    error_details: Optional[str] = Field(default=None, sa_column=Column(JSON))

    # Timing
    started_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
