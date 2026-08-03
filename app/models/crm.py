"""
CRM & Marketing Models
Includes: CRMGuestActivities, CRMSegments, GuestSegments, LoyaltyTiers, LoyaltyTransactions, GuestStayHistory, GuestSpecialRequests, GuestFeedback, Campaigns
"""
from datetime import datetime
from datetime import date as date_type
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class GuestStayHistory(SQLModel, table=True):
    """Detailed stay history for guest profiling (separate from bookings for analytics)"""
    __tablename__ = "guest_stay_history"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True)
    booking_id: Optional[int] = Field(default=None, foreign_key="reservation.id", index=True)
    stay_date: date_type = Field(nullable=False, index=True)
    check_in_date: Optional[date_type] = None
    check_out_date: Optional[date_type] = None
    nights: int = Field(nullable=False)
    room_type: Optional[str] = Field(default=None, index=True)
    room_number: Optional[str] = None
    room_id: Optional[int] = Field(default=None, foreign_key="rooms.id")
    amount: float = Field(nullable=False)
    rating: Optional[int] = None  # 1-5
    review_id: Optional[int] = Field(default=None, foreign_key="reviews.id")
    status: Optional[str] = Field(default=None, index=True)  # completed, cancelled, no_show, current, upcoming
    booking_source: Optional[str] = None
    special_notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CRMGuestActivities(SQLModel, table=True):
    """Track all guest interactions and activities"""
    __tablename__ = "crm_guest_activities"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True)
    activity_type: str = Field(nullable=False, index=True)  # booking, check_in, check_out, review, complaint, inquiry, call, email, sms, visit, upgrade, downgrade, cancellation, loyalty_redemption, profile_update
    activity_category: Optional[str] = Field(default=None, index=True)  # transactional, service, communication, milestone
    description: str = Field(nullable=False)
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[int] = None
    sentiment: Optional[str] = None  # positive, neutral, negative
    importance: Optional[str] = None  # low, medium, high, critical
    performed_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    extra_data: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB (renamed from metadata to avoid SQLAlchemy conflict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class CRMSegments(SQLModel, table=True):
    """Define guest segments for targeted marketing"""
    __tablename__ = "crm_segments"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False, unique=True)
    description: Optional[str] = None
    segment_type: Optional[str] = Field(default=None, index=True)  # demographic, behavioral, value_based, lifecycle
    criteria: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB filter criteria
    is_active: bool = Field(default=True, index=True)
    member_count: int = Field(default=0)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GuestSegments(SQLModel, table=True):
    """Junction table for guest-segment many-to-many relationship"""
    __tablename__ = "guest_segments"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True)
    segment_id: int = Field(foreign_key="crm_segments.id", index=True)
    added_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    added_by: Optional[int] = Field(default=None, foreign_key="users.id")


class LoyaltyTiers(SQLModel, table=True):
    """Define loyalty program tiers"""
    __tablename__ = "loyalty_tiers"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    icon: Optional[str] = None  # emoji/icon identifier
    min_points: int = Field(nullable=False, index=True)
    max_points: Optional[int] = None
    min_revenue: Optional[float] = Field(default=None, index=True)
    benefits: Optional[str] = Field(default=None, sa_column=Column(JSON))  # JSONB
    discount_percentage: Optional[float] = None
    color: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class LoyaltyTransactions(SQLModel, table=True):
    """Track loyalty points transactions"""
    __tablename__ = "loyalty_transactions"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True)
    transaction_type: str = Field(index=True)  # earned, redeemed, expired, adjusted
    points: int = Field(nullable=False)
    balance_after: int = Field(nullable=False)
    reason: Optional[str] = None
    booking_id: Optional[int] = Field(default=None, foreign_key="reservation.id")
    reference_id: Optional[int] = None
    notes: Optional[str] = None
    expires_at: Optional[datetime] = Field(default=None, index=True)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)


class GuestSpecialRequests(SQLModel, table=True):
    """Track recurring guest special requests and preferences"""
    __tablename__ = "guest_special_requests"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True)
    request_category: Optional[str] = Field(default=None, index=True)  # dietary, accessibility, room_preference, service, amenity
    request_type: Optional[str] = None
    request_text: str = Field(nullable=False)
    frequency_count: int = Field(default=1)
    first_requested: Optional[datetime] = None
    last_requested: Optional[datetime] = None
    is_recurring: bool = Field(default=False, index=True)
    always_honor: bool = Field(default=False)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class GuestFeedback(SQLModel, table=True):
    """Track guest feedback, complaints, and compliments"""
    __tablename__ = "guest_feedback"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    feedback_number: Optional[str] = Field(default=None, unique=True, index=True)
    reservation_id: Optional[int] = Field(default=None, foreign_key="reservation.id")
    guest_id: int = Field(foreign_key="guests.id", index=True)
    feedback_type: Optional[str] = Field(default=None, index=True)  # complaint, compliment, suggestion, inquiry, concern
    category: Optional[str] = Field(default=None, index=True)  # service, room, staff, cleanliness, amenities, food, noise, billing
    subcategory: Optional[str] = None
    subject: Optional[str] = None
    description: str = Field(nullable=False)
    urgency: Optional[str] = Field(default=None, index=True)  # low, medium, high, critical
    priority: Optional[str] = None
    status: Optional[str] = Field(default="open", index=True)  # open, acknowledged, in_progress, resolved, closed, escalated
    assigned_to: Optional[int] = Field(default=None, foreign_key="staff.id")
    reported_via: Optional[str] = None
    resolution_target: Optional[datetime] = None
    resolution: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    guest_satisfaction_after: Optional[int] = None  # 1-5
    compensation_offered: Optional[str] = None
    compensation_value: Optional[float] = None
    follow_up_required: bool = Field(default=False)
    follow_up_date: Optional[date_type] = None
    is_public: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Campaigns(SQLModel, table=True):
    """Marketing campaigns"""
    __tablename__ = "campaigns"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(nullable=False)
    campaign_type: Optional[str] = Field(default=None, index=True)  # email, sms, push, in_app
    segment_id: Optional[int] = Field(default=None, foreign_key="crm_segments.id", index=True)
    status: str = Field(default="draft", index=True)  # draft, scheduled, active, completed, cancelled
    scheduled_at: Optional[datetime] = Field(default=None, index=True)
    sent_at: Optional[datetime] = None
    template_id: Optional[int] = None
    subject: Optional[str] = None
    message: Optional[str] = None
    target_count: int = Field(default=0)
    sent_count: int = Field(default=0)
    delivered_count: int = Field(default=0)
    opened_count: int = Field(default=0)
    clicked_count: int = Field(default=0)
    conversion_count: int = Field(default=0)
    unsubscribe_count: int = Field(default=0)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

