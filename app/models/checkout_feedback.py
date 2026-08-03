"""
Checkout Feedback Model
Post-stay guest surveys with category ratings
"""
from datetime import datetime
from typing import Optional, List
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class CheckoutFeedback(SQLModel, table=True):
    """Post-checkout guest feedback with detailed ratings"""
    __tablename__ = "checkout_feedback"

    id: Optional[int] = Field(default=None, primary_key=True)
    reservation_id: int = Field(foreign_key="reservation.id", index=True)
    guest_id: int = Field(foreign_key="guests.id", index=True)

    # Overall rating (1-5 stars)
    overall_rating: int = Field(nullable=False)

    # Category ratings (1-5 stars each)
    cleanliness_rating: Optional[int] = None
    comfort_rating: Optional[int] = None
    staff_rating: Optional[int] = None
    location_rating: Optional[int] = None
    amenities_rating: Optional[int] = None
    value_rating: Optional[int] = None
    dining_rating: Optional[int] = None
    checkin_rating: Optional[int] = None

    # Quick feedback tags selected by guest
    quick_tags: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))

    # Would recommend? (true/false/null)
    would_recommend: Optional[bool] = None

    # Free text comments
    comments: Optional[str] = None

    # Feedback metadata
    submitted_via: str = Field(default="email_link")  # email_link, app, website
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
