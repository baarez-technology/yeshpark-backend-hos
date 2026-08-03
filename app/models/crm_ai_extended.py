"""
CRM AI Extended Models - Advanced AI Features
Includes: ABTestExtended, ABTestVariant, ConversionAttempt, DirectMember,
          AISegment, AISegmentMembership, FrequencyCapLog, ChannelPreference
"""
from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field, Column, Index
from sqlalchemy import JSON, Text


class ABTestExtended(SQLModel, table=True):
    """Extended A/B testing model with comprehensive tracking"""
    __tablename__ = "ab_tests_extended"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=255, nullable=False)
    description: Optional[str] = Field(default=None, max_length=1000)
    test_type: str = Field(max_length=50, nullable=False)  # subject_line, offer, template, cta, timing, channel
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaigns.id", index=True)
    status: str = Field(default="draft", max_length=20)  # draft, running, paused, completed, stopped
    variants: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    traffic_split: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    significance_threshold: float = Field(default=0.95)
    min_sample_size: int = Field(default=100)
    started_at: Optional[datetime] = Field(default=None)
    ended_at: Optional[datetime] = Field(default=None)
    winning_variant: Optional[str] = Field(default=None, max_length=50)
    p_value: Optional[float] = Field(default=None)
    statistical_significance: Optional[float] = Field(default=None)
    results_summary: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ABTestVariant(SQLModel, table=True):
    """Individual variants within an A/B test"""
    __tablename__ = "ab_test_variants"

    id: Optional[int] = Field(default=None, primary_key=True)
    ab_test_id: int = Field(foreign_key="ab_tests_extended.id", index=True, nullable=False)
    variant_name: str = Field(max_length=50, nullable=False)  # A, B, C, control, etc.
    variant_label: Optional[str] = Field(default=None, max_length=255)
    content: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    traffic_percentage: float = Field(default=50.0)
    impressions: int = Field(default=0)
    clicks: int = Field(default=0)
    conversions: int = Field(default=0)
    conversion_rate: Optional[float] = Field(default=None)
    revenue: float = Field(default=0.0)
    avg_order_value: Optional[float] = Field(default=None)
    is_control: bool = Field(default=False)
    is_winner: bool = Field(default=False)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ConversionAttempt(SQLModel, table=True):
    """Track OTA to Direct booking conversion attempts"""
    __tablename__ = "conversion_attempts"

    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True, nullable=False)
    original_booking_id: Optional[int] = Field(default=None, foreign_key="bookings.id", index=True)
    original_channel: str = Field(max_length=100, nullable=False)  # booking.com, expedia, hotels.com, etc.
    conversion_probability: float = Field(default=0.0)
    offer_type: Optional[str] = Field(default=None, max_length=50)  # discount, points, upgrade, package
    offer_value: Optional[float] = Field(default=None)
    offer_details: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    message_content: Optional[str] = Field(default=None, sa_column=Column(Text))
    send_channel: Optional[str] = Field(default=None, max_length=20)  # email, sms, whatsapp
    status: str = Field(default="pending", max_length=20, index=True)  # pending, sent, delivered, opened, clicked, converted, failed, expired
    sent_at: Optional[datetime] = Field(default=None)
    delivered_at: Optional[datetime] = Field(default=None)
    opened_at: Optional[datetime] = Field(default=None)
    clicked_at: Optional[datetime] = Field(default=None)
    converted_at: Optional[datetime] = Field(default=None)
    converted_booking_id: Optional[int] = Field(default=None, foreign_key="bookings.id")
    failure_reason: Optional[str] = Field(default=None, max_length=500)
    expires_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class DirectMember(SQLModel, table=True):
    """Direct booking loyalty program members"""
    __tablename__ = "direct_members"

    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", unique=True, index=True, nullable=False)
    member_number: Optional[str] = Field(default=None, max_length=50, unique=True)
    tier: str = Field(default="bronze", max_length=20)  # bronze, silver, gold, platinum, diamond
    tier_points: int = Field(default=0)
    tier_updated_at: Optional[datetime] = Field(default=None)
    next_tier_threshold: Optional[int] = Field(default=None)
    total_direct_bookings: int = Field(default=0)
    total_direct_spend: float = Field(default=0.0)
    total_points_earned: int = Field(default=0)
    total_points_redeemed: int = Field(default=0)
    available_points: int = Field(default=0)
    base_discount_pct: float = Field(default=5.0)
    ltv_bonus_pct: float = Field(default=0.0)
    health_bonus_pct: float = Field(default=0.0)
    max_discount_cap: float = Field(default=30.0)
    converted_from_ota: bool = Field(default=False)
    conversion_date: Optional[datetime] = Field(default=None)
    original_ota: Optional[str] = Field(default=None, max_length=100)
    exclusive_benefits: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    preferences: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    enrolled_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AISegment(SQLModel, table=True):
    """AI-generated guest segments using clustering algorithms"""
    __tablename__ = "ai_segments"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=255, nullable=False)
    description: Optional[str] = Field(default=None, sa_column=Column(Text))
    segment_type: str = Field(default="ai_micro", max_length=50)  # ai_micro, behavioral, spend_based, lifecycle, custom
    clustering_model: str = Field(default="hdbscan", max_length=50)
    model_version: Optional[str] = Field(default=None, max_length=50)
    model_params: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    characteristics: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    feature_importance: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    member_count: int = Field(default=0)
    avg_ltv: Optional[float] = Field(default=None)
    avg_health_score: Optional[float] = Field(default=None)
    avg_churn_risk: Optional[float] = Field(default=None)
    recommended_campaigns: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    auto_refresh: bool = Field(default=True)
    last_refreshed_at: Optional[datetime] = Field(default=None)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AISegmentMembership(SQLModel, table=True):
    """Guest membership in AI-generated segments"""
    __tablename__ = "ai_segment_memberships"

    id: Optional[int] = Field(default=None, primary_key=True)
    ai_segment_id: int = Field(foreign_key="ai_segments.id", index=True, nullable=False)
    guest_id: int = Field(foreign_key="guests.id", index=True, nullable=False)
    membership_score: float = Field(default=1.0)  # Confidence/probability 0-1
    distance_to_centroid: Optional[float] = Field(default=None)
    feature_values: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    is_active: bool = Field(default=True)
    added_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    __table_args__ = (
        Index('idx_segment_guest', 'ai_segment_id', 'guest_id', unique=True),
    )


class FrequencyCapLog(SQLModel, table=True):
    """Track communication frequency to prevent over-messaging"""
    __tablename__ = "frequency_cap_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", index=True, nullable=False)
    channel: str = Field(max_length=20, nullable=False)  # email, sms, whatsapp, push
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaigns.id")
    campaign_type: Optional[str] = Field(default=None, max_length=50)
    sent_at: datetime = Field(default_factory=datetime.utcnow, index=True)

    __table_args__ = (
        Index('idx_guest_channel_sent', 'guest_id', 'channel', 'sent_at'),
    )


class ChannelPreference(SQLModel, table=True):
    """Guest communication channel preferences based on engagement"""
    __tablename__ = "channel_preferences"

    id: Optional[int] = Field(default=None, primary_key=True)
    guest_id: int = Field(foreign_key="guests.id", unique=True, index=True, nullable=False)
    preferred_channel: Optional[str] = Field(default=None, max_length=20)
    email_score: float = Field(default=0.5)
    sms_score: float = Field(default=0.5)
    whatsapp_score: float = Field(default=0.5)
    push_score: float = Field(default=0.5)
    email_opens: int = Field(default=0)
    email_clicks: int = Field(default=0)
    email_sent: int = Field(default=0)
    sms_clicks: int = Field(default=0)
    sms_sent: int = Field(default=0)
    whatsapp_reads: int = Field(default=0)
    whatsapp_replies: int = Field(default=0)
    whatsapp_sent: int = Field(default=0)
    push_opens: int = Field(default=0)
    push_sent: int = Field(default=0)
    last_calculated_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
