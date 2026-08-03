"""
Extended Booking Models
Includes: RoomChanges, BookingAddOns, CorporateAccounts, Packages, BookingNotes (already in reservations.py)
"""
from datetime import datetime
from datetime import date as date_type  # Alias to avoid field name conflicts
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class RoomChanges(SQLModel, table=True):
    """Track room upgrades, downgrades, and changes"""
    __tablename__ = "room_changes"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    reservation_id: int = Field(foreign_key="reservation.id", index=True)
    original_room_type_id: Optional[int] = Field(default=None, foreign_key="room_types.id")
    original_room_id: Optional[int] = Field(default=None, foreign_key="rooms.id")
    new_room_type_id: Optional[int] = Field(default=None, foreign_key="room_types.id")
    new_room_id: Optional[int] = Field(default=None, foreign_key="rooms.id")
    change_type: Optional[str] = Field(default=None, index=True)  # upgrade, downgrade, lateral, emergency_relocation
    reason_category: Optional[str] = None
    reason: Optional[str] = None
    price_adjustment: Optional[float] = None
    approved_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    changed_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    changed_at: datetime = Field(nullable=False, index=True)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BookingAddOns(SQLModel, table=True):
    """Additional services/packages added to bookings"""
    __tablename__ = "booking_add_ons"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    booking_id: int = Field(foreign_key="reservation.id", index=True)
    add_on_type: str = Field(index=True)  # meal_plan, spa, airport_transfer, parking, late_checkout, etc.
    name: str = Field(nullable=False)
    description: Optional[str] = None
    quantity: int = Field(default=1)
    unit_price: float = Field(nullable=False)
    total_price: float = Field(nullable=False)
    currency: str = Field(default="INR")
    date_added: datetime = Field(default_factory=datetime.utcnow, index=True)
    added_by: Optional[int] = Field(default=None, foreign_key="users.id")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CorporateAccounts(SQLModel, table=True):
    """Corporate account management"""
    __tablename__ = "corporate_accounts"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    account_code: str = Field(unique=True, index=True)
    company_name: str = Field(nullable=False, index=True)
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    billing_address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    zip_code: Optional[str] = None
    tax_id: Optional[str] = None
    discount_percentage: Optional[float] = None
    credit_limit: Optional[float] = None
    payment_terms: Optional[str] = None
    contract_start_date: Optional[date_type] = None
    contract_end_date: Optional[date_type] = None
    rate_plan_id: Optional[int] = Field(default=None, foreign_key="rateplan.id")
    total_bookings: int = Field(default=0)
    total_revenue: float = Field(default=0.0)
    status: str = Field(default="active", index=True)  # active, inactive, suspended
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Packages(SQLModel, table=True):
    """Hotel packages and offers"""
    __tablename__ = "packages"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    package_code: str = Field(unique=True, index=True)
    name: str = Field(nullable=False)
    description: Optional[str] = None
    package_type: Optional[str] = Field(default=None, index=True)  # romance, family, business, adventure, wellness
    inclusions: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB array
    room_type_id: Optional[int] = Field(default=None, foreign_key="room_types.id")
    min_nights: int = Field(default=1)
    max_nights: Optional[int] = None
    price: float = Field(nullable=False)
    currency: str = Field(default="INR")
    valid_from: date_type = Field(nullable=False, index=True)
    valid_to: date_type = Field(nullable=False, index=True)
    is_active: bool = Field(default=True, index=True)
    max_guests: Optional[int] = None
    advance_booking_days: Optional[int] = None
    blackout_dates: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB array
    terms_and_conditions: Optional[str] = None
    image_url: Optional[str] = None
    sort_order: int = Field(default=0)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class MarketSegments(SQLModel, table=True):
    """Market segments for business intelligence"""
    __tablename__ = "market_segments"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    segment_code: str = Field(unique=True, index=True)
    name: str = Field(nullable=False)
    description: Optional[str] = None
    segment_category: Optional[str] = Field(default=None, index=True)  # leisure, business, group, corporate
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DailyMetrics(SQLModel, table=True):
    """Daily operational metrics"""
    __tablename__ = "daily_metrics"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    metric_date: date_type = Field(nullable=False, unique=True, index=True)
    total_rooms: int = Field(nullable=False)
    occupied_rooms: int = Field(nullable=False)
    available_rooms: int = Field(nullable=False)
    ooo_rooms: int = Field(default=0)
    occupancy_percentage: float = Field(nullable=False)
    adr: Optional[float] = None  # Average Daily Rate
    revpar: Optional[float] = None  # Revenue Per Available Room
    total_revenue: float = Field(default=0.0)
    room_revenue: float = Field(default=0.0)
    ancillary_revenue: float = Field(default=0.0)
    arrivals: int = Field(default=0)
    departures: int = Field(default=0)
    in_house_guests: int = Field(default=0)
    no_shows: int = Field(default=0)
    cancellations: int = Field(default=0)
    walk_ins: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class RevenueBySource(SQLModel, table=True):
    """Revenue breakdown by source"""
    __tablename__ = "revenue_by_source"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    date: date_type = Field(nullable=False, index=True)
    source: str = Field(nullable=False, index=True)
    bookings_count: int = Field(default=0)
    revenue: float = Field(default=0.0)
    created_at: datetime = Field(default_factory=datetime.utcnow)

