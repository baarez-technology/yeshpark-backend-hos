from datetime import datetime, date
from typing import Optional
from sqlmodel import SQLModel, Field
from app.models.base import TimestampedModel


class PreCheckIn(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    # Support both old reservation and new booking tables
    reservation_id: int = Field(index=True, unique=True)  # FK will be added via migration
    booking_id: Optional[int] = Field(default=None, index=True)  # NEW: FK to bookings table
    guest_id: int = Field(foreign_key="guests.id", index=True)
    
    # Personal Information
    email: str
    phone: str
    address: Optional[str] = None
    city: Optional[str] = None
    zip_code: Optional[str] = None
    country: Optional[str] = None
    
    # Room Preferences
    floor_preference: Optional[str] = None  # low, mid, high, any
    view_preference: Optional[str] = None  # ocean, city, garden, any
    bed_type_preference: Optional[str] = None  # king, queen, twin, any
    quietness_preference: Optional[str] = None  # quiet, moderate, any
    
    # Selected Room (after AI recommendation)
    selected_room_id: Optional[int] = Field(default=None, foreign_key="rooms.id")
    ai_score: Optional[float] = None
    ai_reasoning: Optional[str] = None  # JSON array of reasons
    
    # Travel Details
    arrival_time: Optional[str] = None
    flight_number: Optional[str] = None
    purpose: Optional[str] = None  # business, leisure, event, other
    transportation_needed: bool = False
    
    # Documents
    id_front_url: Optional[str] = None
    id_back_url: Optional[str] = None
    id_type: Optional[str] = None  # passport, drivers_license, national_id
    id_verified: bool = False
    
    # Preferences
    pillow_type: Optional[str] = None  # JSON array
    temperature: Optional[int] = None
    minibar_preferences: Optional[str] = None  # JSON array
    dietary_restrictions: Optional[str] = None  # JSON array
    
    # Special Requests
    special_requests: Optional[str] = None
    early_check_in: bool = False
    late_check_out: bool = False
    
    # Digital Key
    digital_key_id: Optional[str] = None
    digital_key_activated: bool = False
    qr_code: Optional[str] = None
    
    # Status
    status: str = Field(default="in_progress", index=True)  # in_progress, completed, cancelled
    completed_at: Optional[datetime] = None
    
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

