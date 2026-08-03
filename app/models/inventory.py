from datetime import datetime, date, timedelta
from datetime import date as date_type
from typing import Optional, ClassVar
import secrets
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON
from app.models.base import TimestampedModel


class RoomType(SQLModel, table=True):
    """Define categories/types of rooms available"""
    __tablename__ = "room_types"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    slug: str = Field(unique=True, index=True)
    category: Optional[str] = Field(default=None, index=True)  # standard, deluxe, suite, presidential
    description: str = Field(nullable=False)
    short_description: Optional[str] = None
    base_price: float = Field(nullable=False, index=True)
    max_guests: int = Field(nullable=False)
    bed_type: Optional[str] = None
    size_sqft: Optional[int] = None
    amenities: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    features: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    images: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    view_type: Optional[str] = None
    rating: Optional[float] = None
    review_count: int = Field(default=0)
    is_active: bool = Field(default=True, index=True)
    sort_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RoomStatus:
    """Standardized room status values - use these constants across the system"""
    AVAILABLE = "available"  # Room is ready for guests
    OCCUPIED = "occupied"    # Guest currently staying
    CLEAN = "clean"          # Cleaned and ready
    DIRTY = "dirty"          # Needs cleaning
    INSPECTED = "inspected"  # Cleaned and inspected
    CLEANING = "in_progress"    # Cleaning in progress
    MAINTENANCE = "maintenance"  # Under maintenance
    OUT_OF_SERVICE = "out_of_service"  # Temporarily unavailable (minor issues, can be sold if emergency)
    OUT_OF_ORDER = "out_of_order"  # Major issues, CANNOT be sold (plumbing, electrical, renovation)

    # All valid statuses
    ALL = {AVAILABLE, OCCUPIED, CLEAN, DIRTY, INSPECTED, CLEANING, MAINTENANCE, OUT_OF_SERVICE, OUT_OF_ORDER}

    # Statuses that mean room is unavailable for booking
    UNAVAILABLE = {OCCUPIED, MAINTENANCE, OUT_OF_SERVICE, OUT_OF_ORDER}

    # Aliases mapping (normalize inconsistent values)
    ALIASES = {
        "ooo": OUT_OF_ORDER,  # OOO = Out of Order (major issues)
        "oos": OUT_OF_SERVICE,  # OOS = Out of Service (minor issues)
        "cleaning": CLEANING,
        "vacant": AVAILABLE,
    }

    @classmethod
    def normalize(cls, status: str) -> str:
        """Normalize status to standard value"""
        if not status:
            return cls.AVAILABLE
        status_lower = status.lower().strip()
        # Check aliases first
        if status_lower in cls.ALIASES:
            return cls.ALIASES[status_lower]
        # Return as-is if valid
        if status_lower in cls.ALL:
            return status_lower
        # Default to available for unknown
        return cls.AVAILABLE


class Room(SQLModel, table=True):
    """Physical room inventory"""
    __tablename__ = "rooms"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_type_id: int = Field(foreign_key="room_types.id", index=True)
    number: str = Field(index=True, unique=True)
    floor: Optional[int] = Field(default=None, index=True)
    # Valid statuses: available, occupied, clean, dirty, inspected, cleaning, maintenance, out_of_service
    status: str = Field(default="available", index=True)
    # F-03: Compound room statuses — split into occupancy + cleaning dimensions
    occupancy_status: Optional[str] = Field(default="vacant", index=True)  # vacant, occupied, reserved
    cleaning_status: Optional[str] = Field(default="clean", index=True)  # clean, dirty, inspected, in_progress
    condition: Optional[str] = None  # excellent, good, fair, needs_repair
    capacity: int = 2
    max_occupancy: int = 2
    bed_type: Optional[str] = None  # king, queen, twin, double
    view_type: Optional[str] = None  # ocean, city, garden, pool
    size_sqft: Optional[int] = None
    amenities: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    images: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    notes: Optional[str] = None
    is_smoking: bool = Field(default=False)
    is_accessible: bool = Field(default=False)
    price_per_night: Optional[float] = None  # Room-specific price override (falls back to RoomType.base_price if None)
    description: Optional[str] = None  # Room-specific description
    last_cleaned: Optional[datetime] = Field(default=None, index=True)
    last_inspection: Optional[datetime] = None
    last_maintenance: Optional[datetime] = None
    # Out of Order / Out of Service tracking
    ooo_reason: Optional[str] = None  # Reason for OOO status (plumbing, electrical, hvac, renovation, etc.)
    ooo_category: Optional[str] = None  # maintenance, renovation, damage, inspection
    ooo_start_date: Optional[datetime] = None  # When room was marked OOO
    ooo_expected_end: Optional[datetime] = None  # Expected return to service
    ooo_marked_by: Optional[int] = None  # User who marked OOO
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RatePlan(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)  # BAR, CORP, GRP, PKG, EARLY_BIRD, LAST_MINUTE
    name: str
    description: Optional[str] = None
    plan_type: str = Field(default="BAR", index=True)  # BAR, corporate, group, package, seasonal, derived
    currency: str = "INR"
    base_price: float = 0.0
    is_active: bool = Field(default=True, index=True)
    parent_rate_plan_id: Optional[int] = Field(default=None, foreign_key="rateplan.id")  # For derived rates
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RateRestriction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    rate_plan_id: int = Field(foreign_key="rateplan.id", index=True)
    restriction_type: str = Field(index=True)  # min_stay, max_stay, closed_to_arrival, closed_to_departure, advance_booking
    value: Optional[int] = None  # e.g., min nights
    start_date: Optional[date_type] = None
    end_date: Optional[date_type] = None
    day_of_week: Optional[int] = None  # 0=Monday, 6=Sunday
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SeasonalRate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    rate_plan_id: int = Field(foreign_key="rateplan.id", index=True)
    room_type: Optional[str] = Field(default=None, index=True)  # If None, applies to all room types
    start_date: date_type = Field(index=True)
    end_date: date_type = Field(index=True)
    price_adjustment: float = 0.0  # Can be absolute or percentage based on adjustment_type
    adjustment_type: str = Field(default="absolute")  # absolute, percentage
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LengthOfStayRate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    rate_plan_id: int = Field(foreign_key="rateplan.id", index=True)
    room_type: Optional[str] = Field(default=None, index=True)
    min_nights: int = Field(index=True)
    max_nights: Optional[int] = None
    price_adjustment: float = 0.0
    adjustment_type: str = Field(default="absolute")  # absolute, percentage
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DayOfWeekRate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    rate_plan_id: int = Field(foreign_key="rateplan.id", index=True)
    room_type: Optional[str] = Field(default=None, index=True)
    day_of_week: int = Field(index=True)  # 0=Monday, 6=Sunday
    price_adjustment: float = 0.0
    adjustment_type: str = Field(default="absolute")  # absolute, percentage
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class PromoCode(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True, unique=True)
    name: str
    description: Optional[str] = None
    discount_type: str = Field(default="percentage")  # percentage, fixed_amount
    discount_value: float
    min_stay: Optional[int] = None
    max_stay: Optional[int] = None
    valid_from: date_type = Field(index=True)
    valid_until: date_type = Field(index=True)
    usage_limit: Optional[int] = None
    usage_count: int = 0
    is_active: bool = Field(default=True, index=True)
    applicable_rate_plans: Optional[str] = None  # JSON array of rate plan IDs
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RoomHold(SQLModel, table=True):
    """
    Temporary room holds during booking process.
    Prevents race conditions by reserving inventory for 15 minutes
    while guest completes booking flow.
    """
    __tablename__ = "room_holds"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_type_id: int = Field(foreign_key="room_types.id", index=True)
    room_id: Optional[int] = Field(default=None, foreign_key="rooms.id", index=True)
    arrival_date: date_type = Field(index=True)
    departure_date: date_type = Field(index=True)
    hold_token: str = Field(unique=True, index=True)  # Unique token for this hold
    expires_at: datetime = Field(index=True)  # Hold expires after configured duration
    reservation_id: Optional[int] = Field(default=None, foreign_key="reservation.id")  # Set when converted to booking
    status: str = Field(default="active", index=True)  # active, converted, expired, cancelled
    guest_session_id: Optional[str] = None  # Browser session ID for tracking
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Configuration - ClassVar to prevent SQLModel treating it as a column
    HOLD_DURATION_MINUTES: ClassVar[int] = 15

    @classmethod
    def create_hold(
        cls,
        room_type_id: int,
        arrival_date: date_type,
        departure_date: date_type,
        room_id: Optional[int] = None,
        guest_session_id: Optional[str] = None,
        hold_duration_minutes: Optional[int] = None
    ) -> "RoomHold":
        """Factory method to create a new room hold with proper expiration."""
        duration = hold_duration_minutes or cls.HOLD_DURATION_MINUTES
        return cls(
            room_type_id=room_type_id,
            room_id=room_id,
            arrival_date=arrival_date,
            departure_date=departure_date,
            hold_token=secrets.token_urlsafe(32),
            expires_at=datetime.utcnow() + timedelta(minutes=duration),
            guest_session_id=guest_session_id
        )

    def is_expired(self) -> bool:
        """Check if this hold has expired."""
        return datetime.utcnow() > self.expires_at or self.status in ("expired", "cancelled")

    def is_active(self) -> bool:
        """Check if this hold is still active and valid."""
        return self.status == "active" and not self.is_expired()

    def convert_to_reservation(self, reservation_id: int) -> None:
        """Mark this hold as converted to a confirmed reservation."""
        self.reservation_id = reservation_id
        self.status = "converted"

    def cancel(self) -> None:
        """Cancel this hold, releasing the inventory."""
        self.status = "cancelled"

    def extend(self, additional_minutes: int = 5) -> None:
        """Extend the hold duration (e.g., when guest is actively booking)."""
        if self.is_active():
            self.expires_at = datetime.utcnow() + timedelta(minutes=additional_minutes)


class RoomBlock(SQLModel, table=True):
    """
    Room blocks for maintenance, events, or administrative purposes.
    Blocks rooms from availability without creating a reservation.
    """
    __tablename__ = "room_blocks"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_type_id: Optional[int] = Field(default=None, foreign_key="room_types.id", index=True)  # If None, applies to specific rooms
    room_id: Optional[int] = Field(default=None, foreign_key="rooms.id", index=True)  # Specific room (optional)
    start_date: date_type = Field(index=True, nullable=False)
    end_date: date_type = Field(index=True, nullable=False)

    # Block details
    block_type: str = Field(default="maintenance", index=True)  # maintenance, renovation, event, overbooking_buffer, manual
    reason: str = Field(nullable=False)  # Human-readable reason for the block
    notes: Optional[str] = None  # Additional notes
    quantity: int = Field(default=1)  # Number of rooms to block (if room_type_id is set)

    # Status tracking
    status: str = Field(default="active", index=True)  # active, completed, cancelled
    priority: int = Field(default=0)  # Higher priority blocks take precedence

    # User tracking
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    cancelled_by: Optional[int] = Field(default=None, foreign_key="users.id")
    cancelled_at: Optional[datetime] = None
    cancellation_reason: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def is_active(self) -> bool:
        """Check if this block is currently active."""
        return self.status == "active" and self.end_date >= date.today()

    def cancel(self, user_id: Optional[int] = None, reason: Optional[str] = None) -> None:
        """Cancel this block."""
        self.status = "cancelled"
        self.cancelled_by = user_id
        self.cancelled_at = datetime.utcnow()
        self.cancellation_reason = reason


class DailyAvailability(SQLModel, table=True):
    """
    Daily availability snapshot for CMS availability management.
    Tracks sold, blocked, and available inventory per room type per day.
    """
    __tablename__ = "daily_availability"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_type_id: int = Field(foreign_key="room_types.id", index=True, nullable=False)
    date: date_type = Field(index=True, nullable=False)

    # Inventory counts
    total_rooms: int = Field(default=0)  # Total physical rooms
    sold: int = Field(default=0)  # Rooms sold/booked
    blocked: int = Field(default=0)  # Rooms blocked
    available: int = Field(default=0)  # Calculated: total - sold - blocked

    # Restrictions
    is_closed: bool = Field(default=False, index=True)  # Stop sell
    min_stay: int = Field(default=1)  # Minimum length of stay
    max_stay: Optional[int] = None  # Maximum length of stay
    closed_to_arrival: bool = Field(default=False)  # CTA
    closed_to_departure: bool = Field(default=False)  # CTD

    # Pricing (optional - for quick reference)
    base_rate: Optional[float] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OverbookingAlert(SQLModel, table=True):
    """
    Track overbooking alerts and their resolution.
    Created when a booking causes overbooking beyond the configured threshold.
    """
    __tablename__ = "overbooking_alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_type_id: int = Field(foreign_key="room_types.id", index=True)
    alert_date: date = Field(index=True)  # The date with overbooking

    # Overbooking metrics
    total_rooms: int = Field(default=0)  # Total physical rooms of this type
    booked_count: int = Field(default=0)  # Number of bookings for this date
    overbooking_count: int = Field(default=0)  # Number of overbooked rooms
    overbooking_percent: float = Field(default=0.0)  # Percentage overbooked

    # Threshold info
    configured_limit_percent: float = Field(default=0.0)
    exceeded_by_percent: float = Field(default=0.0)  # How much over the limit

    # Alert details
    severity: str = Field(default="warning", index=True)  # warning, critical
    alert_type: str = Field(default="threshold_exceeded")  # threshold_exceeded, dynamic_adjusted, manual
    message: str = Field(nullable=False)

    # Related bookings that caused overbooking
    triggering_booking_id: Optional[int] = Field(default=None, index=True)
    affected_bookings: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSON array of booking IDs

    # Resolution
    status: str = Field(default="active", index=True)  # active, acknowledged, resolved, auto_resolved
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = Field(default=None, foreign_key="users.id")
    resolution_method: Optional[str] = None  # relocated, cancelled, waitlisted, no_action_needed
    resolution_notes: Optional[str] = None

    # Notifications
    notification_sent: bool = Field(default=False)
    notification_sent_at: Optional[datetime] = None
    notified_users: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSON array of user IDs

    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OverbookingConfig(SQLModel, table=True):
    """
    Global overbooking configuration and policies.
    Provides property-wide defaults that can be overridden per room type.
    """
    __tablename__ = "overbooking_config"

    id: Optional[int] = Field(default=None, primary_key=True)

    # Global settings
    overbooking_enabled: bool = Field(default=True)
    default_limit_percent: float = Field(default=5.0)  # Default 5% overbooking
    max_limit_percent: float = Field(default=15.0)  # Maximum allowed overbooking

    # Dynamic adjustment settings
    dynamic_overbooking_enabled: bool = Field(default=False)
    historical_lookback_days: int = Field(default=90)  # Days to analyze for no-show rates
    min_data_points: int = Field(default=30)  # Minimum bookings needed for dynamic calc

    # Alert thresholds
    warning_threshold_percent: float = Field(default=80.0)  # Alert at 80% of limit
    critical_threshold_percent: float = Field(default=100.0)  # Critical at 100% of limit

    # Notification settings
    alert_managers: bool = Field(default=True)
    alert_front_desk: bool = Field(default=True)
    email_notifications: bool = Field(default=True)

    # Compensation policy
    relocation_compensation_percent: float = Field(default=100.0)  # % of rate to comp if relocated
    upgrade_when_relocating: bool = Field(default=True)  # Try to upgrade relocated guests

    # Auto-actions
    auto_waitlist_when_full: bool = Field(default=True)
    block_new_bookings_at_limit: bool = Field(default=False)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DailyRate(SQLModel, table=True):
    """
    Daily rate storage for inventory management.
    Stores the rate for each room type + rate plan combination per day.
    """
    __tablename__ = "daily_rates"

    id: Optional[int] = Field(default=None, primary_key=True)
    room_type_id: int = Field(foreign_key="room_types.id", index=True)
    rate_plan_id: int = Field(foreign_key="rateplan.id", index=True)
    date: date_type = Field(index=True)

    # Rate information
    base_rate: float = Field(nullable=False)  # Base rate in cents or currency units
    calculated_rate: Optional[float] = None  # After adjustments
    override_rate: Optional[float] = None  # Manual override
    override_reason: Optional[str] = None
    override_by: Optional[int] = Field(default=None, foreign_key="users.id")

    # Rate status
    is_active: bool = Field(default=True)
    is_derived: bool = Field(default=False)  # Derived from parent rate plan

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class InventorySyncQueue(SQLModel, table=True):
    """
    Queue for pending inventory sync operations.
    Used to batch and schedule sync operations to OTAs.
    """
    __tablename__ = "inventory_sync_queue"

    id: Optional[int] = Field(default=None, primary_key=True)
    ota_channel_id: Optional[int] = Field(default=None, foreign_key="ota_connections.id", index=True)  # None = all OTAs
    room_type_id: Optional[int] = Field(default=None, foreign_key="room_types.id", index=True)  # None = all room types

    # What to sync
    sync_type: str = Field(index=True)  # availability, rates, restrictions
    date: date_type = Field(index=True)

    # Change details
    change_type: str = Field(default="update")  # update, override, bulk
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    changed_by: Optional[int] = Field(default=None, foreign_key="users.id")

    # Queue status
    status: str = Field(default="pending", index=True)  # pending, processing, completed, failed
    priority: int = Field(default=0)  # Higher = more urgent
    retry_count: int = Field(default=0)
    max_retries: int = Field(default=3)

    # Processing timestamps
    queued_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    processed_at: Optional[datetime] = None
    error_message: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


