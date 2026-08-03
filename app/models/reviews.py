"""
Review Models
Includes: Reviews, OTAStats, ReviewSourcesConfig, SentimentTrends
"""
from datetime import datetime
from datetime import date as date_type  # Alias to avoid field name conflicts
from typing import Optional
from sqlmodel import SQLModel, Field, Column
from sqlalchemy import JSON


class Review(SQLModel, table=True):
    """Guest reviews and ratings"""
    __tablename__ = "reviews"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: Optional[int] = Field(default=None, foreign_key="guests.id", index=True)
    booking_id: Optional[int] = Field(default=None, foreign_key="reservation.id", index=True)
    room_id: Optional[int] = Field(default=None, foreign_key="rooms.id", index=True)
    source: str = Field(index=True)  # direct, google, tripadvisor, booking_com, expedia, etc.
    overall_rating: float = Field(nullable=False, index=True)
    cleanliness_rating: Optional[float] = None
    service_rating: Optional[float] = None
    location_rating: Optional[float] = None
    value_rating: Optional[float] = None
    amenities_rating: Optional[float] = None
    title: Optional[str] = None
    comment: Optional[str] = None
    pros: Optional[str] = None
    cons: Optional[str] = None
    response: Optional[str] = None
    responded_by: Optional[int] = Field(default=None, foreign_key="staff.id")
    responded_at: Optional[datetime] = None
    sentiment: Optional[str] = Field(default=None, index=True)  # positive, neutral, negative
    is_verified: bool = Field(default=False)
    is_featured: bool = Field(default=False)
    is_public: bool = Field(default=True)
    helpful_count: int = Field(default=0)
    review_date: datetime = Field(nullable=False, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OTAStats(SQLModel, table=True):
    """OTA (Online Travel Agency) statistics"""
    __tablename__ = "ota_stats"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    ota_name: str = Field(nullable=False, index=True)
    stat_date: date_type = Field(nullable=False, index=True)
    average_rating: Optional[float] = None
    total_reviews: int = Field(default=0)
    rank: Optional[int] = None
    views: int = Field(default=0)
    bookings: int = Field(default=0)
    conversion_rate: Optional[float] = None
    revenue: Optional[float] = None
    commission: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ReviewSourcesConfig(SQLModel, table=True):
    """Configuration for review sources"""
    __tablename__ = "review_sources_config"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    source_name: str = Field(unique=True, index=True)
    display_name: str = Field(nullable=False)
    api_endpoint: Optional[str] = None
    api_key: Optional[str] = None
    is_active: bool = Field(default=True, index=True)
    sync_enabled: bool = Field(default=False)
    last_sync: Optional[datetime] = None
    sync_frequency_hours: Optional[int] = None
    weight: float = Field(default=1.0)  # For calculating overall rating
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SentimentTrends(SQLModel, table=True):
    """Track sentiment trends over time"""
    __tablename__ = "sentiment_trends"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    date: date_type = Field(nullable=False, index=True)
    category: Optional[str] = Field(default=None, index=True)  # overall, service, cleanliness, food, etc.
    positive_count: int = Field(default=0)
    neutral_count: int = Field(default=0)
    negative_count: int = Field(default=0)
    total_count: int = Field(default=0)
    sentiment_score: Optional[float] = None  # -1 to 1
    average_rating: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

