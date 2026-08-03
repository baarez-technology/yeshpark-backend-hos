"""
Runner/Bell Staff Operations Models
Includes: RunnerPickupRequest, RunnerDelivery, RunnerActivityLog
"""
from datetime import datetime
from datetime import date as date_type  # Alias to avoid field name conflicts
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class RunnerPickupRequest(SQLModel, table=True):
    """Track luggage, package, laundry pickup requests by bell staff/runners"""
    __tablename__ = "runner_pickup_requests"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    request_number: str = Field(unique=True, index=True)
    room_id: int = Field(foreign_key="rooms.id", index=True)
    room_number: str = Field(nullable=False, index=True)
    guest_id: Optional[int] = Field(default=None, foreign_key="guests.id", index=True)
    guest_name: str = Field(nullable=False)
    pickup_type: str = Field(nullable=False, index=True)  # luggage, laundry, package, amenity_request, other
    items_description: str = Field(nullable=False)
    item_count: int = Field(default=1)
    pickup_location: str = Field(nullable=False)
    destination: str = Field(nullable=False)
    scheduled_time: Optional[datetime] = Field(default=None, index=True)
    priority: str = Field(default="normal", index=True)  # low, normal, high, urgent
    status: str = Field(default="pending", index=True)  # pending, in_progress, completed, cancelled
    requested_by: Optional[str] = None
    requested_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    assigned_to: Optional[int] = Field(default=None, foreign_key="staff.id", index=True)
    accepted_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    notes: Optional[str] = None
    special_instructions: Optional[str] = None
    photos: Optional[str] = Field(default=None, sa_column=Column("photos", JSON))  # JSONB
    signature_required: bool = Field(default=False)
    signature_url: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RunnerDelivery(SQLModel, table=True):
    """Track deliveries (room service, packages, amenities) by runners"""
    __tablename__ = "runner_deliveries"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    delivery_number: str = Field(unique=True, index=True)
    delivery_type: str = Field(nullable=False, index=True)  # room_service, package, laundry, amenity, other
    room_id: int = Field(foreign_key="rooms.id", index=True)
    room_number: str = Field(nullable=False, index=True)
    guest_id: Optional[int] = Field(default=None, foreign_key="guests.id", index=True)
    guest_name: str = Field(nullable=False)
    items_description: str = Field(nullable=False)
    item_count: int = Field(default=1)
    origin_location: str = Field(nullable=False)
    destination_location: str = Field(nullable=False)
    priority: str = Field(default="normal", index=True)  # low, normal, high, urgent
    status: str = Field(default="pending", index=True)  # pending, in_transit, delivered, cancelled
    ordered_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    assigned_to: Optional[int] = Field(default=None, foreign_key="staff.id", index=True)
    accepted_at: Optional[datetime] = None
    picked_up_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    estimated_delivery_time: Optional[datetime] = Field(default=None, index=True)
    actual_delivery_time: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    special_instructions: Optional[str] = None
    notes: Optional[str] = None
    signature_required: bool = Field(default=False)
    signature_url: Optional[str] = None
    temperature_sensitive: bool = Field(default=False)
    fragile: bool = Field(default=False)
    delivery_confirmation: str = Field(default="none")  # none, signature, photo, both
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class RunnerActivityLog(SQLModel, table=True):
    """Track runner/bell staff daily performance"""
    __tablename__ = "runner_activity_log"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    staff_id: int = Field(foreign_key="staff.id", index=True)
    date: date_type = Field(nullable=False, index=True)
    total_pickups: int = Field(default=0)
    total_deliveries: int = Field(default=0)
    completed_pickups: int = Field(default=0)
    completed_deliveries: int = Field(default=0)
    avg_pickup_time: Optional[int] = None  # minutes
    avg_delivery_time: Optional[int] = None  # minutes
    guest_interactions: int = Field(default=0)
    tips_received: float = Field(default=0.0)
    performance_rating: Optional[float] = None
    on_time_percentage: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

